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
import ssl
import subprocess
import tempfile
import time
from doppler_runtime import Cluster


class RedisError(Exception):
    pass


class Client:
    def __init__(self, port, tls=None):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=10)
        if tls:
            try:
                self.socket = tls[0].wrap_socket(self.socket, server_hostname=tls[1])
            except Exception:
                self.socket.close()
                raise
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
def forwarded(cluster, name, tls=None):
    process = subprocess.Popen(cluster.prefix + ["-n", "databases", "port-forward", "service/" + name,
        "--address=127.0.0.1", ":6379"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env=cluster.environment)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "Port-forward not ready"
            match = re.search(r"127\.0\.0\.1:(\d+)", process.stdout.readline())
            assert match, "Port-forward failed"
        client = Client(int(match.group(1)), tls)
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


@contextlib.contextmanager
def tls_contexts():
    # ssl requires PEM paths. Generated runtime copies are owner-only and removed on exit.
    import os
    from redis_pki import new_ca, leaf, pem
    ca = private("infrastructure", "REDIS_TLS_CA_CERT")
    with tempfile.TemporaryDirectory(prefix="redis-mtls-") as directory:
        def context(label, cert=None, key=None, trusted=True):
            ctx = ssl.create_default_context(cadata=ca) if trusted else ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            if cert:
                paths = []
                for suffix, value in [("crt", cert), ("key", key)]:
                    path = Path(directory) / (label + "." + suffix)
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as stream:
                        stream.write(value)
                    paths.append(str(path))
                ctx.load_cert_chain(*paths)
            return ctx
        app_cert, app_key = [private("auth", k) for k in ["REDIS_TLS_CERT", "REDIS_TLS_KEY"]]
        ops_cert, ops_key = [private("infrastructure", k) for k in ["REDIS_OPERATIONS_TLS_CERT", "REDIS_OPERATIONS_TLS_KEY"]]
        rogue_key, rogue_ca = new_ca()
        rogue = pem(leaf(rogue_key, rogue_ca))
        yield {"app": context("app", app_cert, app_key), "ops": context("ops", ops_cert, ops_key),
               "missing": context("missing"), "untrusted_server": context("untrusted", app_cert, app_key, False),
               "untrusted_client": context("rogue", rogue["CERT"], rogue["KEY"])}


def transport_denied(port, tls=None):
    client = None
    try:
        client = Client(port, tls)
        client.command("PING")
    except (ssl.SSLError, ConnectionResetError, RuntimeError):
        return
    finally:
        if client:
            client.close()
    raise AssertionError("Forbidden transport accepted")


def verify(run):
    cluster = Cluster(run)
    username, password, prefix = [private("auth", k) for k in ["REDIS_USERNAME", "REDIS_PASSWORD", "REDIS_KEY_PREFIX"]]
    admin, admin_password = [private("infrastructure", k) for k in ["REDIS_ADMIN_USERNAME", "REDIS_ADMIN_PASSWORD"]]
    master_host, replica_host = [private("infrastructure", k) for k in ["REDIS_HOST", "REDIS_REPLICA_HOST"]]
    with tls_contexts() as contexts, forwarded(cluster, "shared-redis-master", (contexts["app"], master_host)) as master, \
            forwarded(cluster, "shared-redis-replica", (contexts["app"], replica_host)) as replica:
        for client, host in [(master, master_host), (replica, replica_host)]:
            denied(client, "NOAUTH", "PING")
            with contextlib.closing(Client(client.socket.getpeername()[1], (contexts["ops"], host))) as operator:
                assert operator.command("AUTH", admin, admin_password) == "OK"
                assert operator.command("CONFIG", "GET", "maxmemory") == ["maxmemory", "134217728"]
                assert operator.command("CONFIG", "GET", "appendonly") == ["appendonly", "yes"]
                for option, expected in [("port", "0"), ("tls-port", "6379"), ("tls-auth-clients", "yes"), ("tls-replication", "yes")]:
                    assert operator.command("CONFIG", "GET", option) == [option, expected]
                expected = "role:master" if client is master else "master_link_status:up"
                assert expected in operator.command("INFO", "replication")
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
        # A rejected stream can close a kubectl forward. Isolate every negative case,
        # and prove that same forward accepts a valid mTLS client immediately first.
        for role, host in [("master", master_host), ("replica", replica_host)]:
            for mode in ["plaintext", "missing", "untrusted_client", "untrusted_server", "wrong_hostname"]:
                with forwarded(cluster, "shared-redis-" + role, (contexts["app"], host)) as control:
                    assert control.command("AUTH", username, password) == "OK"
                    assert control.command("PING") == "PONG"
                    candidate = None if mode == "plaintext" else (
                        contexts["app"] if mode == "wrong_hostname" else contexts[mode],
                        "wrong.example.invalid" if mode == "wrong_hostname" else host)
                    transport_denied(control.socket.getpeername()[1], candidate)
    print(json.dumps({"authenticated_ping": True, "master_to_replica": True, "replica_read_only": True,
        "unauthenticated_denied": True, "foreign_keys_and_admin_denied": True, "maxmemory_bytes": 134217728,
        "aof_enabled": True, "mtls_verified": True, "plaintext_denied": True, "missing_and_untrusted_certificate_denied": True,
        "server_hostname_verified": True, "values_displayed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(json.loads(args.run_config.read_text()))
    except Exception:
        raise SystemExit("Redis verification failed; private error details suppressed.")
