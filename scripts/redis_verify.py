#!/usr/bin/env python3
"""Bounded ACL/replication smoke test; values remain in memory, never argv/output."""
import argparse
import contextlib
import json
from pathlib import Path
import re
import secrets
import selectors
import socket
import subprocess
import time
from doppler_runtime import Cluster


class RedisError(Exception):
    pass


class Client:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.stream = self.socket.makefile("rb")

    def close(self):
        self.stream.close()
        self.socket.close()

    def command(self, *args):
        encoded = [str(a).encode() for a in args]
        self.socket.sendall(b"*%d\r\n" % len(encoded) + b"".join(b"$%d\r\n" % len(a) + a + b"\r\n" for a in encoded))
        return self.read()

    def read(self):
        line = self.stream.readline()
        if not line:
            raise RuntimeError("Redis disconnected")
        kind, value = line[:1], line[1:-2]
        if kind == b"-":
            # Preserve only the public error code, never a key or identity from the message.
            raise RedisError(value.split(b" ", 1)[0].decode())
        if kind == b"+":
            return value.decode()
        if kind == b":":
            return int(value)
        if kind == b"$":
            length = int(value)
            if length == -1:
                return None
            data = self.stream.read(length)
            assert self.stream.read(2) == b"\r\n"
            return data.decode()
        if kind == b"*":
            return [self.read() for _ in range(int(value))]
        raise RuntimeError("Unexpected Redis response")


@contextlib.contextmanager
def forwarded(cluster, name):
    process = subprocess.Popen(cluster.prefix + ["-n", "databases", "port-forward", "service/" + name,
        "--address=127.0.0.1", ":6379"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env=cluster.environment)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "Port-forward not ready"
            match = re.search(r"127\.0\.0\.1:(\d+)", process.stdout.readline())
            assert match, "Port-forward failed"
        client = Client(int(match.group(1)))
        try:
            yield client
        finally:
            client.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def private(project, key):
    result = subprocess.run(["doppler", "secrets", "get", key, "--plain", "--project", project,
        "--config", "prd", "--no-check-version"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Doppler read failed"
    return result.stdout.strip()


def denied(client, code, *command):
    try:
        client.command(*command)
    except RedisError as error:
        assert str(error) == code, "Unexpected denial"
        return
    raise AssertionError("Forbidden operation accepted")


def verify(run):
    cluster = Cluster(run)
    username, password, prefix = [private("auth", k) for k in ["REDIS_USERNAME", "REDIS_PASSWORD", "REDIS_KEY_PREFIX"]]
    admin, admin_password = [private("infrastructure", k) for k in ["REDIS_ADMIN_USERNAME", "REDIS_ADMIN_PASSWORD"]]
    with forwarded(cluster, "shared-redis-master") as master, forwarded(cluster, "shared-redis-replica") as replica:
        for client in [master, replica]:
            denied(client, "NOAUTH", "PING")
            assert client.command("AUTH", admin, admin_password) == "OK"
            assert client.command("CONFIG", "GET", "maxmemory") == ["maxmemory", "134217728"]
            assert client.command("CONFIG", "GET", "appendonly") == ["appendonly", "yes"]
        assert "role:master" in master.command("INFO", "replication")
        assert "master_link_status:up" in replica.command("INFO", "replication")
        for client in [master, replica]:
            assert client.command("AUTH", username, password) == "OK"
            assert client.command("PING") == "PONG"
            for command in [("GET", "verification-other:" + secrets.token_hex(8)), ("KEYS", "*"),
                            ("SCAN", "0"), ("FLUSHALL",), ("CONFIG", "GET", "maxmemory"),
                            ("ACL", "LIST"), ("EVAL", "return 1", "0"), ("PUBLISH", "other", "test")]:
                denied(client, "NOPERM", *command)
        key = prefix + "verification:" + secrets.token_hex(12)
        try:
            assert master.command("SET", key, "replication-test", "EX", "60", "NX") == "OK"
            assert master.command("GET", key) == "replication-test"
            deadline = time.monotonic() + 10
            while replica.command("GET", key) != "replication-test":
                assert time.monotonic() < deadline, "Replication timed out"
                time.sleep(0.2)
            denied(replica, "READONLY", "SET", key, "forbidden")
        finally:
            master.command("DEL", key)
    print(json.dumps({"authenticated_ping": True, "master_to_replica": True, "replica_read_only": True,
        "unauthenticated_denied": True, "foreign_keys_and_admin_denied": True, "maxmemory_bytes": 134217728,
        "aof_enabled": True, "values_displayed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(json.loads(args.run_config.read_text()))
    except Exception:
        raise SystemExit("Redis verification failed; private error details suppressed.")
