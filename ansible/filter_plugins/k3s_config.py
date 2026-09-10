"""Strict non-secret deployment contract, also testable without Ansible."""

import hashlib
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit


def require(condition):
    if not condition:
        raise ValueError("Invalid or unreviewed K3s configuration; check the documented input contract.")


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def address(value):
    require(isinstance(value, str))
    try:
        result = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError("An explicit IPv4 address is required.") from None
    require(not (result.is_loopback or result.is_unspecified or result.is_multicast or result.is_link_local))
    return result


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or value == "localhost":
        return False
    try:
        address(value)
        return True
    except ValueError:
        return "." in value and not re.fullmatch(r"[0-9.]+", value) and all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in value.split("."))


def resolve_environment(value):
    """Resolve explicit whole-value references; never interpolate arbitrary text."""
    if isinstance(value, dict):
        if '$env' in value or '$env_json' in value:
            require(len(value) == 1)
            kind = next(iter(value))
            key = value[kind]
            require(matches(key, r'[A-Z][A-Z0-9_]*'))
            raw = os.environ.get(key)
            require(raw is not None and raw.strip() != '')
            if kind == '$env':
                return raw
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError('Invalid environment JSON input; values are not displayed.') from None
        return {key: resolve_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_environment(item) for item in value]
    return value


def validate(config):
    config = resolve_environment(config)
    required = {
        "reviewed", "network_reviewed", "version", "sha256", "datastore", "pod_cidr",
        "service_cidr", "cluster_dns", "endpoint", "tls_sans", "servicelb", "token_env", "nodes",
    }
    require(isinstance(config, dict) and required <= set(config) <= required | {"bootstrap_server", "backup"})
    require(config["reviewed"] is True and config["network_reviewed"] is True)
    require(matches(config["version"], r"v1\.[0-9]+\.[0-9]+\+k3s[0-9]+"))
    require(matches(config["sha256"], r"[0-9a-f]{64}"))
    require(config["datastore"] in ("sqlite", "etcd") and type(config["servicelb"]) is bool)
    if "backup" in config:
        backup = config["backup"]
        require(config["datastore"] == "etcd" and isinstance(backup, dict))
        require(type(backup.get("enabled")) is bool)
        if backup["enabled"]:
            require(set(backup) == {"enabled", "endpoint", "region", "bucket", "folder", "schedule", "local_retention", "remote_retention"})
            require(matches(backup["region"], r"[a-z]+-[a-z]+-[0-9]+"))
            require(backup["endpoint"] == 's3.' + backup["region"] + '.wasabisys.com' or (backup["region"] == 'us-east-1' and backup["endpoint"] == 's3.wasabisys.com'))
            require(matches(backup["bucket"], r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"))
            require(matches(backup["folder"], r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*"))
            # Deliberately accept only fixed daily hours; reject malformed cron before restart.
            require(matches(backup["schedule"], r"(?:[0-9]|[1-5][0-9]) (?:[0-9]|1[0-9]|2[0-3])(?:,(?:[0-9]|1[0-9]|2[0-3]))* \* \* \*"))
            for key in ('local_retention', 'remote_retention'):
                require(type(backup[key]) is int and 1 <= backup[key] <= 10000)
        else:
            require(set(backup) == {"enabled"})
    token_keys = {"server", "agent"} | ({"server_join"} if config["datastore"] == "etcd" else set())
    require(isinstance(config["token_env"], dict) and set(config["token_env"]) == token_keys)
    require(all(matches(key, r"[A-Z][A-Z0-9_]{0,127}") for key in config["token_env"].values()))
    require(len(set(config["token_env"].values())) == len(token_keys))
    try:
        pods = ipaddress.IPv4Network(config["pod_cidr"], strict=True)
        services = ipaddress.IPv4Network(config["service_cidr"], strict=True)
        dns = address(config["cluster_dns"])
        endpoint = urlsplit(config["endpoint"])
        require(endpoint.scheme == "https" and endpoint.port == 6443 and hostname(endpoint.hostname))
        require(not (endpoint.username or endpoint.password or endpoint.path or endpoint.query or endpoint.fragment))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid cluster network or API endpoint configuration.") from None
    require(8 <= pods.prefixlen <= 24 and 8 <= services.prefixlen <= 24)
    require(not pods.overlaps(services) and dns in services)
    require(dns not in (services.network_address, services.broadcast_address, services.network_address + 1))
    sans = config["tls_sans"]
    require(isinstance(sans, list) and len(sans) > 0 and all(hostname(san) for san in sans))
    require(len(set(sans)) == len(sans) and endpoint.hostname in sans)
    nodes = config["nodes"]
    require(isinstance(nodes, dict) and len(nodes) > 0)
    server_count, ips, ssh_hosts = 0, set(), set()
    for name, node in nodes.items():
        require(matches(name, r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*") and len(name) <= 63)
        require(isinstance(node, dict) and set(node) == {
            "role", "ssh_host", "ssh_user", "node_ip", "flannel_iface", "os_distribution", "os_version",
        })
        require(node["role"] in ("server", "agent"))
        server_count += node["role"] == "server"
        ip = address(node["node_ip"])
        require(ip not in pods and ip not in services and ip not in ips)
        ips.add(ip)
        require(hostname(node["ssh_host"]) and node["ssh_host"] not in ssh_hosts)
        ssh_hosts.add(node["ssh_host"])
        require(matches(node["ssh_user"], r"[a-z_][a-z0-9_-]{0,31}"))
        require(matches(node["flannel_iface"], r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,14}"))
        require(node["os_distribution"] == "Ubuntu" and matches(node["os_version"], r"[0-9]{2}\.[0-9]{2}"))
    if config["datastore"] == "sqlite":
        require(server_count == 1 and "bootstrap_server" not in config)
    else:
        require(server_count >= 1)
        require(isinstance(config.get("bootstrap_server"), str))
        require(config["bootstrap_server"] in nodes and nodes[config["bootstrap_server"]]["role"] == "server")
    return config


def render_node(config, name):
    config = validate(config)
    require(isinstance(name, str) and name in config["nodes"])
    node = config["nodes"][name]
    role = node["role"]
    joining_server = role == "server" and config["datastore"] == "etcd" and name != config["bootstrap_server"]
    values = {
        "node-name": name, "node-ip": node["node_ip"], "flannel-iface": node["flannel_iface"],
        "token-file": "/etc/rancher/k3s/bootstrap-token",
    }
    if role == "server":
        values.update({
            "disable": ["traefik"] + ([] if config["servicelb"] else ["servicelb"]),
            "write-kubeconfig-mode": "0600", "secrets-encryption": True,
            "cluster-cidr": config["pod_cidr"], "service-cidr": config["service_cidr"],
            "cluster-dns": config["cluster_dns"], "tls-san": sorted(config["tls_sans"]),
            "flannel-backend": "vxlan",
        })
        if config["datastore"] == "etcd":
            if "backup" in config:
                backup = config["backup"]
                values.update({"etcd-disable-snapshots": not backup["enabled"], "etcd-s3": backup["enabled"]})
                if backup["enabled"]:
                    values.update({"etcd-snapshot-schedule-cron": backup["schedule"],
                                   "etcd-snapshot-retention": backup["local_retention"],
                                   "etcd-s3-retention": backup["remote_retention"],
                                   "etcd-snapshot-compress": True,
                                   **{'etcd-s3-' + key: backup[key] for key in ('endpoint', 'region', 'bucket', 'folder')}})
            if joining_server:
                values["server"] = config["endpoint"]
            else:
                values["cluster-init"] = True
    else:
        values["server"] = config["endpoint"]
    result = {
        "node": dict(node), "name": name, "config": values,
        "version": config["version"], "sha256": config["sha256"],
        "token_env": config["token_env"]["server_join" if joining_server else role],
        "service": "k3s" if role == "server" else "k3s-agent",
        "url": "https://github.com/k3s-io/k3s/releases/download/" + config["version"] + "/k3s-arm64",
        # Bump contract schema when changing installation behavior/unit.
        "schema": 1,
    }
    result["fingerprint"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def inventory(config):
    config = validate(config)
    groups = {"k3s_servers": {"hosts": {}}, "k3s_agents": {"hosts": {}}}
    groups.update({"k3s_bootstrap": {"hosts": {}}, "k3s_joining_servers": {"hosts": {}}})
    for name, node in sorted(config["nodes"].items()):
        group = "k3s_servers" if node["role"] == "server" else "k3s_agents"
        groups[group]["hosts"][name] = {
            "ansible_host": node["ssh_host"], "ansible_user": node["ssh_user"],
            "ansible_connection": "ssh", "ansible_python_interpreter": "/usr/bin/python3",
        }
        if node["role"] == "server":
            bootstrap = config.get("bootstrap_server", name)
            subgroup = "k3s_bootstrap" if name == bootstrap else "k3s_joining_servers"
            groups[subgroup]["hosts"][name] = {}
    return {"all": {"vars": {"k3s_config": config}, "children": groups}}


class FilterModule:
    def filters(self):
        return {"k3s_render_node": render_node, "k3s_inventory": inventory}
