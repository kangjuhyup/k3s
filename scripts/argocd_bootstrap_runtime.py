#!/usr/bin/env python3
"""Restricted fresh-cluster Argo CD seed. Invoked by Ansible with JSON on stdin.

No Helm operations, apply/patch/delete, secret output or automatic cleanup.
"""
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time

NS = "argocd"
OWNER = "infrastructure.local/bootstrap-id"
CLUSTER_KINDS = {"CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding"}
NAMESPACED_KINDS = {"ConfigMap", "Service", "ServiceAccount", "Role", "RoleBinding",
                    "Deployment", "StatefulSet", "NetworkPolicy"}


def require(condition, message="Bootstrap contract rejected; no input values are displayed."):
    if not condition:
        raise ValueError(message)


def validate_bundle(bundle):
    require(isinstance(bundle, dict) and bundle.get("schema") == 1)
    require(re.fullmatch(r"[0-9a-f]{40}", bundle.get("expected_revision", "")) is not None)
    require(re.fullmatch(r"[0-9a-f]{64}", bundle.get("identity", "")) is not None)
    seen = set()
    for obj in bundle["resources"]:
        kind, meta = obj.get("kind"), obj.get("metadata", {})
        require(kind in CLUSTER_KINDS | NAMESPACED_KINDS)
        name = meta.get("name", "")
        if kind == "CustomResourceDefinition":
            require(name in {"applications.argoproj.io", "applicationsets.argoproj.io", "appprojects.argoproj.io"})
        else:
            require(name.startswith("argocd-") or name == "argocd")
        require(meta.get("namespace", "") == ("" if kind in CLUSTER_KINDS else NS))
        require(not meta.get("annotations", {}).get("helm.sh/hook"))
        key = (kind, name)
        require(key not in seen)
        seen.add(key)
    require(("Deployment", "argocd-server") in seen and ("StatefulSet", "argocd-application-controller") in seen)
    require(bundle["root"]["metadata"]["name"] == "oci-a1-root")
    require(bundle["self"]["metadata"]["name"] == "argocd")
    require([p["metadata"]["name"] for p in bundle["projects"]] == ["bootstrap-root", "platform-argocd"])
    for obj in [bundle["root"], bundle["self"], *bundle["projects"]]:
        require(obj["apiVersion"] == "argoproj.io/v1alpha1" and obj["metadata"].get("namespace") == NS)
        require(obj["kind"] == ("AppProject" if obj in bundle["projects"] else "Application"))
    config = bundle["config"]
    expected_id = hashlib.sha256((config["repo_url"] + "\ngitops/clusters/oci-a1/root").encode()).hexdigest()
    require(bundle["identity"] == expected_id)
    require(bundle["root"]["spec"]["source"] == {
        "repoURL": config["repo_url"], "targetRevision": config["revision"], "path": "gitops/clusters/oci-a1/root"})
    for app in [bundle["root"], bundle["self"]]:
        require(app["spec"]["destination"] == {"server": "https://kubernetes.default.svc", "namespace": NS})


def handoff_ready(app, expected, revisions):
    if not app or app.get("operation"):
        return False
    spec, desired = app.get("spec", {}), expected["spec"]
    keys = ["project", "destination", "syncPolicy", "sources" if "sources" in desired else "source"]
    if any(spec.get(key) != desired[key] for key in keys):
        return False
    status = app.get("status", {})
    sync, operation = status.get("sync", {}), status.get("operationState", {})
    if sync.get("status") != "Synced" or status.get("health", {}).get("status") != "Healthy":
        return False
    if operation.get("phase") != "Succeeded" or any(c.get("type", "").endswith("Error") for c in status.get("conditions", [])):
        return False
    compared = sync.get("comparedTo", {})
    if any(compared.get(key) != desired[key] for key in keys if key not in ("project", "syncPolicy")):
        return False
    result = operation.get("syncResult", {})
    if "sources" in desired:
        return sync.get("revisions") == revisions and result.get("revisions") == revisions
    return sync.get("revision") == revisions[0] and result.get("revision") == revisions[0]


def secrets(config, values):
    require(set(values) == {"admin_password_hash", "server_secretkey", "redis_auth", "git_username", "git_password"})
    require(all(isinstance(value, str) for value in values.values()))
    require(re.fullmatch(r"\$2[aby]\$(?:1[0-6])\$[./A-Za-z0-9]{53}", values["admin_password_hash"]) is not None)
    require(all(32 <= len(values[key]) <= 4096 and "\n" not in values[key] for key in ["server_secretkey", "redis_auth"]))
    def secret(name, data, labels=None):
        return {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                "metadata": {"name": name, "namespace": NS,
                             "labels": labels or {"app.kubernetes.io/part-of": "argocd"}}, "stringData": data}
    result = [secret("argocd-secret", {
        "admin.password": values["admin_password_hash"],
        "admin.passwordMtime": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "server.secretkey": values["server_secretkey"]}), secret("argocd-redis", {"auth": values["redis_auth"]})]
    if config["auth"]["mode"] == "https-token":
        require(all(0 < len(values[key]) <= 8192 and "\n" not in values[key] for key in ["git_username", "git_password"]))
        result.append(secret("infra-git", {"type": "git", "url": config["repo_url"],
                                            "username": values["git_username"], "password": values["git_password"]},
                             {"argocd.argoproj.io/secret-type": "repository"}))
    return result


class Kubectl:
    def __init__(self):
        self.prefix = ["/usr/local/bin/k3s", "kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml",
                       "--context=default", "--namespace=" + NS, "--request-timeout=30s"]

    def run(self, args, document=None, timeout=60):
        # Do not inherit KUBECONFIG, proxy or tool auth variables.
        result = subprocess.run(self.prefix + args, input=None if document is None else json.dumps(document),
                                text=True, capture_output=True, timeout=timeout, check=False,
                                env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
        require(result.returncode == 0, "Kubernetes operation failed; inspect the scoped resource without dumping secrets.")
        return result.stdout

    def get(self, kind, name):
        raw = self.run(["get", kind, name, "--ignore-not-found", "-o", "json"])
        return json.loads(raw) if raw.strip() else None

    def create(self, obj):
        # Create, never overwrite. Field manager is shared with the eventual SSA owner.
        self.run(["create", "--field-manager=argocd-controller", "-f", "-"], obj)

    def wait_crds(self):
        for name in ["applications.argoproj.io", "appprojects.argoproj.io", "applicationsets.argoproj.io"]:
            self.run(["wait", "--for=condition=Established", "crd/" + name, "--timeout=120s"], timeout=150)

    def rollouts(self):
        for resource in ["statefulset/argocd-application-controller", "deployment/argocd-server",
                         "deployment/argocd-repo-server", "deployment/argocd-redis"]:
            self.run(["rollout", "status", resource, "--timeout=180s"], timeout=210)

    def check_api(self, version):
        self.run(["get", "--raw=/readyz"])
        actual = json.loads(self.run(["version", "-o", "json"]))["serverVersion"]["gitVersion"]
        require(actual.split("+")[0] == "v" + version, "Kubernetes version differs from the reviewed render target.")


def bootstrap(bundle, secret_values, client, attempts=120, pause=time.sleep):
    validate_bundle(bundle)
    client.check_api(bundle["config"]["kube_version"])
    namespace = client.get("namespace", NS)
    fresh = namespace is None
    if not fresh:
        require(namespace.get("metadata", {}).get("annotations", {}).get(OWNER) == bundle["identity"],
                "Existing namespace is not owned by this bootstrap; no writes performed.")
    else:
        require(bundle["initial_accounts"], "Fresh bootstrap requires bootstrap-phase accounts with no enabled personal accounts.")
        # Validate every secret and all globally conflicting names before first mutation.
        initial_secrets = secrets(bundle["config"], secret_values)
        for obj in bundle["resources"]:
            if obj["kind"] in CLUSTER_KINDS:
                require(client.get(obj["kind"], obj["metadata"]["name"]) is None,
                        "Existing cluster-scoped Argo CD resource found; no writes performed.")
        client.create({"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": NS, "annotations": {OWNER: bundle["identity"]}}})
        for obj in initial_secrets:
            client.create(obj)
        crds = [obj for obj in bundle["resources"] if obj["kind"] == "CustomResourceDefinition"]
        for obj in crds:
            client.create(obj)
        client.wait_crds()
        for obj in bundle["resources"]:
            if obj["kind"] != "CustomResourceDefinition":
                client.create(obj)
        client.rollouts()
        for project in bundle["projects"]:
            client.create(project)
        client.create(bundle["root"])
        # Root controller, not Ansible, creates the self-management Application.
    for _ in range(attempts):
        root = client.get("applications.argoproj.io", "oci-a1-root")
        app = client.get("applications.argoproj.io", "argocd")
        if handoff_ready(root, bundle["root"], [bundle["expected_revision"]]) and handoff_ready(
                app, bundle["self"], ["10.8.2", bundle["expected_revision"]]):
            client.rollouts()
            return {"changed": fresh, "handoff": "verified", "revision": bundle["expected_revision"]}
        pause(5)
    raise ValueError("GitOps handoff not verified; no overwrite or cleanup was attempted. Inspect scoped sync/health and partial bootstrap state.")


def main():
    try:
        require(os.geteuid() == 0 and platform.system() == "Linux" and platform.machine() == "aarch64")
        payload = json.load(sys.stdin)
        require(set(payload) == {"bundle", "secrets"})
        result = bootstrap(payload["bundle"], payload["secrets"], Kubectl())
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print("Bootstrap failed or handoff unverified. No automatic rollback/deletion; inspect scoped status without exposing secrets.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
