#!/usr/bin/env python3
"""Strict, value-free Doppler contracts and Argo CD declarations (stdlib only)."""
import re
import argparse
import json
from pathlib import Path
import yaml

SETTINGS = "gitops/clusters/oci-a1/doppler.json"
PATH = "gitops/clusters/oci-a1/doppler"
INSTALL = "gitops/platform/doppler/install"
ROOT = "gitops/clusters/oci-a1/root"
NAMESPACE = "doppler-operator-system"
SERVICE_ACCOUNT = "doppler-operator-controller-manager"
DNS = r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
ENV = r"[A-Z][A-Z0-9_]{0,127}"


def require(condition):
    if not condition:
        raise ValueError("Doppler configuration or ownership check failed; values are not displayed.")


def match(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def validate(config):
    require(isinstance(config, dict) and set(config) == {
        "enabled", "reviewed", "sync_enabled", "auth_ready_reviewed", "targets_ready_reviewed", "mappings"})
    flags = ["enabled", "reviewed", "sync_enabled", "auth_ready_reviewed", "targets_ready_reviewed"]
    require(all(type(config[k]) is bool for k in flags))
    require(isinstance(config["mappings"], list))
    require(not config["enabled"] or config["reviewed"])
    require(not config["sync_enabled"] or all(config[k] for k in flags))
    require(not config["sync_enabled"] or config["mappings"])
    names, targets, tokens, envs = set(), set(), {}, {}
    for mapping in config["mappings"]:
        require(isinstance(mapping, dict) and set(mapping) == {
            "name", "project", "config", "token_secret", "token_env", "target_namespace", "target_secret",
            "type", "resync_seconds", "keys"})
        require(all(match(mapping[k], DNS) for k in ["name", "token_secret", "target_namespace", "target_secret"]))
        require(mapping["token_secret"].startswith("doppler-auth-"))
        require(match(mapping["token_env"], ENV))
        require(all(match(mapping[k], r"[a-z][a-z0-9_-]{0,63}") for k in ["project", "config"]))
        require(mapping["target_namespace"] not in {NAMESPACE, "argocd", "default"})
        require(not mapping["target_namespace"].startswith("kube-"))
        require(mapping["target_secret"] not in {"cacerts", "istio-ca-secret", "istio-ca-root-cert"})
        require(not mapping["target_secret"].startswith(("doppler-auth-", "sh.helm.release.")))
        require(mapping["type"] in {"Opaque", "kubernetes.io/tls", "kubernetes.io/basic-auth"})
        require(mapping["target_namespace"] != "istio-system" or mapping["type"] == "kubernetes.io/tls")
        require(type(mapping["resync_seconds"]) is int and 60 <= mapping["resync_seconds"] <= 3600)
        keys = mapping["keys"]
        require(isinstance(keys, dict) and 0 < len(keys) <= 100)
        require(all(match(k, ENV) and not k.startswith("DOPPLER_") and
                    match(v, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}") and not v.startswith("DOPPLER_")
                    for k, v in keys.items()))
        require(len(set(keys.values())) == len(keys))
        if mapping["type"] == "kubernetes.io/tls":
            require(set(keys.values()) == {"tls.crt", "tls.key"})
        if mapping["type"] == "kubernetes.io/basic-auth":
            require(set(keys.values()) == {"username", "password"})
        name, target = mapping["name"], (mapping["target_namespace"], mapping["target_secret"])
        require(name not in names and target not in targets)
        names.add(name)
        targets.add(target)
        token = mapping["token_secret"]
        identity = (mapping["project"], mapping["config"], mapping["token_env"])
        require(token not in tokens or tokens[token] == identity)
        require(mapping["token_env"] not in envs or envs[mapping["token_env"]] == token)
        tokens[token], envs[mapping["token_env"]] = identity, token
    return config


def resource(api, kind, name, namespace=None, wave="0", **fields):
    metadata = {"name": name, "annotations": {"argocd.argoproj.io/sync-wave": wave}}
    if namespace:
        metadata["namespace"] = namespace
    return {"apiVersion": api, "kind": kind, "metadata": metadata, **fields}


def render(bootstrap, config):
    validate(config)
    if not config["enabled"]:
        return {}
    namespaces = sorted({m["target_namespace"] for m in config["mappings"]}) if config["sync_enabled"] else []
    policy = {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
              "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"]}
    destination = {"server": "https://kubernetes.default.svc", "namespace": NAMESPACE}
    project = resource("argoproj.io/v1alpha1", "AppProject", "platform-doppler", "argocd", "-10", spec={
        "description": "Administrator-only secret delivery controller; Secret data is not Git-owned",
        "sourceRepos": [bootstrap["repo_url"]],
        "destinations": [destination] + [{"server": destination["server"], "namespace": n} for n in namespaces],
        "clusterResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "Namespace"), ("apiextensions.k8s.io", "CustomResourceDefinition"),
            ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding")]],
        "namespaceResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "ServiceAccount"), ("", "ConfigMap"), ("apps", "Deployment"),
            ("rbac.authorization.k8s.io", "Role"), ("rbac.authorization.k8s.io", "RoleBinding"),
            ("secrets.doppler.com", "DopplerSecret")]]})
    app = resource("argoproj.io/v1alpha1", "Application", "doppler", "argocd", "30", spec={
        "project": "platform-doppler", "destination": destination,
        "source": {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "path": PATH},
        "syncPolicy": policy})
    files = {ROOT + "/doppler-project.yaml": project, ROOT + "/doppler.yaml": app}
    resources = ["../../../platform/doppler/install"]

    def add(filename, obj):
        files[PATH + "/" + filename] = obj
        resources.append(filename)

    for namespace in namespaces:
        targets = sorted(m["target_secret"] for m in config["mappings"] if m["target_namespace"] == namespace)
        add(namespace + "-role.yaml", resource("rbac.authorization.k8s.io/v1", "Role", "doppler-secret-writer",
            namespace, rules=[
                {"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]},
                {"apiGroups": [""], "resources": ["secrets"], "verbs": ["update"], "resourceNames": targets}]))
        add(namespace + "-binding.yaml", resource("rbac.authorization.k8s.io/v1", "RoleBinding", "doppler-secret-writer",
            namespace, subjects=[{"kind": "ServiceAccount", "name": SERVICE_ACCOUNT, "namespace": NAMESPACE}],
            roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "doppler-secret-writer"}))
    if config["sync_enabled"]:
        for mapping in sorted(config["mappings"], key=lambda m: m["name"]):
            add(mapping["name"] + "-sync.yaml", resource("secrets.doppler.com/v1alpha1", "DopplerSecret",
                mapping["name"], NAMESPACE, "20", spec={
                    "tokenSecret": {"name": mapping["token_secret"], "namespace": NAMESPACE},
                    "managedSecret": {"name": mapping["target_secret"], "namespace": mapping["target_namespace"],
                                      "type": mapping["type"]},
                    "project": mapping["project"], "config": mapping["config"],
                    "host": "https://api.doppler.com", "verifyTLS": True,
                    "resyncSeconds": mapping["resync_seconds"], "secrets": sorted(mapping["keys"]),
                    "processors": {k: {"type": "plain", "asName": v} for k, v in sorted(mapping["keys"].items())}}))
    files[PATH + "/kustomization.yaml"] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources}
    return files


def check_previous(root, files, read):
    """prune=false cannot retire old writers or retarget a mapping safely."""
    require(not (root / ROOT / "doppler.yaml").exists() or ROOT + "/doppler.yaml" in files)
    previous = root / PATH / "kustomization.yaml"
    if not previous.exists():
        return
    current = files.get(PATH + "/kustomization.yaml", {}).get("resources", [])
    old = read(previous)["resources"]
    require(set(old).issubset(set(current)))
    for filename in old:
        if not filename.endswith("-sync.yaml"):
            continue
        before = read(root / PATH / filename)["spec"]
        after = files[PATH + "/" + filename]["spec"]
        # New names/explicit migration are required for source or ownership changes.
        require(all(before[k] == after[k] for k in ["managedSecret", "project", "config"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Update only Doppler declarations locally")
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        def read(path):
            return yaml.safe_load(path.read_text())
        files = render(read(root / "gitops/clusters/oci-a1/bootstrap.json"), read(root / SETTINGS))
        check_previous(root, files, read)
        for path, value in files.items():
            target = root / path
            require(target.resolve().is_relative_to(root) and not target.is_symlink())
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True))
            else:
                require(read(target) == value)
        print("Doppler declarations " + ("updated locally." if args.write else "match the key mapping."))
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        print("Doppler declaration check failed; values suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
