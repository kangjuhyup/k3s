#!/usr/bin/env python3
"""Explicit-context Doppler auth bootstrap or read-only delivery check; never prints values."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


doppler, gitops = load("doppler_gitops"), load("gitops_validate")
require = doppler.require
OWNER = "infra.oci-a1.example/doppler-auth-owner"


def validate_run(config):
    require(isinstance(config, dict) and set(config) == {
        "expected_revision", "kubectl", "kubeconfig", "context", "api_server", "chart"})
    require(all(isinstance(v, str) and v for v in config.values()))
    require(doppler.match(config["expected_revision"], r"[0-9a-f]{40}"))
    require(doppler.match(config["context"], r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,253}"))
    url = urlsplit(config["api_server"])
    require(url.scheme == "https" and url.hostname and not (url.username or url.password or url.query or url.fragment))
    require(url.path in {"", "/"})
    for key in ["kubectl", "kubeconfig", "chart"]:
        require(Path(config[key]).is_absolute() and Path(config[key]).is_file())
    return config


class Cluster:
    def __init__(self, run):
        self.prefix = [run["kubectl"], "--kubeconfig", run["kubeconfig"], "--context", run["context"], "--request-timeout=20s"]
        self.environment = {"PATH": os.defpath}
        if "HOME" in os.environ:
            self.environment["HOME"] = os.environ["HOME"]
        view = self.execute(["config", "view", "--minify", "-o", "json"])
        require(view.get("current-context") == run["context"] and len(view.get("clusters", [])) == 1)
        cluster = view["clusters"][0]["cluster"]
        require(cluster["server"].rstrip("/") == run["api_server"].rstrip("/"))
        require(not cluster.get("insecure-skip-tls-verify") and not cluster.get("proxy-url"))

    def execute(self, args, obj=None):
        result = subprocess.run(self.prefix + args, input=json.dumps(obj) if obj is not None else None,
                                text=True, capture_output=True, timeout=45, check=False, env=self.environment)
        require(result.returncode == 0)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def get(self, kind, name, namespace=None, optional=False):
        args = ["get", kind, name, "-o", "json"]
        if namespace:
            args += ["--namespace", namespace]
        if optional:
            args.append("--ignore-not-found=true")
        return self.execute(args)

    def create(self, obj):
        # Token goes only through stdin. Captured output/errors are never printed.
        self.execute(["create", "--namespace", doppler.NAMESPACE, "-f", "-", "-o", "json"], obj)


def application_ready(cluster, expected, revision, require_healthy=True):
    actual = cluster.get("application", expected["metadata"]["name"], "argocd")
    spec, status = actual.get("spec", {}), actual.get("status", {})
    require(all(spec.get(k) == v for k, v in expected["spec"].items()))
    sync = status.get("sync", {})
    require(sync.get("status") == "Synced" and sync.get("revision") == revision)
    require(not require_healthy or status.get("health", {}).get("status") == "Healthy")
    require(not any(c.get("type", "").endswith("Error") for c in status.get("conditions", [])))
    require(status.get("operationState", {}).get("phase") == "Succeeded" and not actual.get("operation"))


def untracked_secret(obj):
    metadata = obj.get("metadata", {})
    annotations = metadata.get("annotations", {})
    require(not metadata.get("deletionTimestamp") and not metadata.get("ownerReferences"))
    require(not any(k in annotations for k in ["argocd.argoproj.io/tracking-id", "meta.helm.sh/release-name"]))


def target_safe(cluster, mapping):
    namespace, name = mapping["target_namespace"], mapping["target_secret"]
    cluster.get("namespace", namespace)
    existing = cluster.get("secret", name, namespace, optional=True)
    if existing is not None:
        untracked_secret(existing)
        require(existing.get("type") == mapping["type"] and not existing.get("immutable", False))
        require(existing.get("metadata", {}).get("annotations", {}).get("secrets.doppler.com/managed-by") ==
                doppler.NAMESPACE + "/" + mapping["name"])
    return existing


def bootstrap_tokens(cluster, bootstrap, config, environment, token_env=None):
    doppler.validate(config)
    require(config["enabled"] and config["mappings"])
    require(not config["sync_enabled"] or token_env)
    mappings = [m for m in config["mappings"] if not token_env or m["token_env"] == token_env]
    require(mappings)
    pending, checked = [], set()
    # Validate ALL inputs and existing targets before the first write.
    for mapping in mappings:
        target_safe(cluster, mapping)
        name = mapping["token_secret"]
        if name in checked:
            continue
        checked.add(name)
        token = environment.get(mapping["token_env"], "")
        require(doppler.match(token, r"dp\.st\.[A-Za-z0-9_.-]{20,512}"))
        identity = hashlib.sha256(json.dumps([
            bootstrap["repo_url"], doppler.PATH, name, mapping["project"], mapping["config"]]).encode()).hexdigest()
        data = {"serviceToken": base64.b64encode(token.encode()).decode()}
        existing = cluster.get("secret", name, doppler.NAMESPACE, optional=True)
        if existing is not None:
            untracked_secret(existing)
            require(existing.get("type") == "Opaque")
            require(existing.get("metadata", {}).get("annotations", {}).get(OWNER) == identity)
            require(existing.get("data") == data)
        else:
            pending.append({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                            "metadata": {"name": name, "namespace": doppler.NAMESPACE,
                                         "annotations": {OWNER: identity}}, "data": data})
    for obj in pending:
        cluster.create(obj)
    return len(pending)


def verify_delivery(cluster, bootstrap, config):
    doppler.validate(config)
    require(config["enabled"] and config["sync_enabled"])
    desired = {o["metadata"]["name"]: o for o in doppler.render(bootstrap, config).values() if o.get("kind") == "DopplerSecret"}
    for mapping in config["mappings"]:
        cr = cluster.get("dopplersecret", mapping["name"], doppler.NAMESPACE)
        expected = desired[mapping["name"]]["spec"]
        require(all(cr.get("spec", {}).get(k) == v for k, v in expected.items()))
        require(any(c.get("type") == "secrets.doppler.com/SecretSyncReady" and c.get("status") == "True"
                    for c in cr.get("status", {}).get("conditions", [])))
        secret = target_safe(cluster, mapping)
        require(secret is not None)
        for key in mapping["keys"].values():
            require(key in secret.get("data", {}))
            require(bool(base64.b64decode(secret["data"][key], validate=True)))
    return len(config["mappings"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bootstrap-auth", "verify"])
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-config", type=Path, required=True)
    parser.add_argument("--token-env", default="", help="Explicit single config authentication bootstrap; never a token value")
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        require(root == Path(__file__).resolve().parents[1])
        run = validate_run(gitops.read_json(args.run_config))
        load("argocd_bundle").verify_checkout(root, run["expected_revision"])
        bootstrap = gitops.validate(gitops.read_json(root / gitops.SETTINGS_PATH))
        config = doppler.validate(gitops.read_json(root / doppler.SETTINGS))
        require(config["enabled"])
        files = gitops.validate_repository(root)
        require(gitops.check_files(root, doppler.render(bootstrap, config)))
        require(gitops.check_files(root, load("doppler_vendor").render(Path(run["chart"]))))
        cluster = Cluster(run)
        for name in ["root", "doppler"]:
            incremental = args.action == "bootstrap-auth" and bool(args.token_env) and config["sync_enabled"]
            application_ready(cluster, files[gitops.ROOT_PATH + "/" + name + ".yaml"], run["expected_revision"],
                              require_healthy=not (incremental and name == "doppler"))
        if incremental:
            # A newly declared config has no auth yet. Existing config delivery must remain healthy.
            others = {**config, "mappings": [m for m in config["mappings"] if m["token_env"] != args.token_env]}
            if others["mappings"]:
                verify_delivery(cluster, bootstrap, others)
        if args.action == "bootstrap-auth":
            count = bootstrap_tokens(cluster, bootstrap, config, os.environ, args.token_env or None)
            print(json.dumps({"created": count, "unchanged": count == 0}))
        else:
            count = verify_delivery(cluster, bootstrap, config)
            print(json.dumps({"checked_mappings": count, "values_displayed": False,
                              "freshness_verified": False, "tls_validity_verified": False}))
        return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print("Doppler operation blocked or failed. Values are not displayed; inspect target, ownership and status safely.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
