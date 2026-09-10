#!/usr/bin/env python3
"""Read-only checks for Git-owned manifests and bootstrap inputs; never generates files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
import yaml

CHART_VERSION = "10.8.2"
CHART_REPO = "https://argoproj.github.io/argo-helm"
ROOT_PATH = "gitops/clusters/oci-a1/root"
SETTINGS_PATH = "gitops/clusters/oci-a1/bootstrap.json"
BASE_PATH = "gitops/platform/argocd/base.values.yaml"
ACCOUNTS_PATH = "gitops/platform/argocd/accounts.values.yaml"
ENV_PATH = "gitops/clusters/oci-a1/argocd.values.yaml"
NAMESPACE = "argocd"
ISTIO_MANIFEST_PATH = "gitops/clusters/oci-a1/istio"
ISTIO_REPO = "https://blob.istio.io/istio-release/charts"
ISTIO_VERSION = "1.30.4"
INGRESS_VALUES_PATH = "gitops/clusters/oci-a1/ingress.values.yaml"
K3S_SETTINGS_PATH = "ansible/inventories/oci-a1/settings.json"


def require(condition):
    if not condition:
        raise ValueError("Invalid GitOps declaration or bootstrap input; values are not displayed.")


def match(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def validate(config):
    require(isinstance(config, dict) and set(config) == {
        "reviewed", "repo_url", "revision", "kube_version", "auth", "doppler", "secret_env"})
    require(config["reviewed"] is True)
    require(isinstance(config["repo_url"], str))
    try:
        url = urlsplit(config["repo_url"])
        require(url.scheme == "https" and url.hostname and "." in url.hostname and url.port in (None, 443))
        require(not (url.username or url.password or url.query or url.fragment))
        require(match(url.path, r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.git"))
    except (ValueError, TypeError):
        raise ValueError("Invalid HTTPS Git repository URL.") from None
    require(match(config["revision"], r"[A-Za-z][A-Za-z0-9_/-]{0,127}") and config["revision"] != "HEAD")
    require(not config["revision"].endswith("/") and "//" not in config["revision"])
    require(match(config["kube_version"], r"1\.[0-9]+\.[0-9]+"))
    auth = config["auth"]
    require(isinstance(auth, dict) and set(auth) == {"mode", "username_env", "password_env"})
    require(auth["mode"] in ("public", "https-token"))
    doppler = config["doppler"]
    require(isinstance(doppler, dict) and set(doppler) == {"project", "config"})
    require(all(match(v, r"[a-z][a-z0-9_-]{0,63}") for v in doppler.values()))
    refs = config["secret_env"]
    require(isinstance(refs, dict) and set(refs) == {"admin_password_hash", "server_secretkey", "redis_auth"})
    names = list(refs.values()) + [auth["username_env"], auth["password_env"]]
    require(all(match(v, r"[A-Z][A-Z0-9_]{0,127}") for v in names))
    require(len(set(names)) == len(names))
    return config


def identity(config):
    validate(config)
    return hashlib.sha256((config["repo_url"] + "\n" + ROOT_PATH).encode()).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def read_json(path):
    """Read legacy JSON inputs or YAML declarations, rejecting duplicate keys."""
    path = Path(path)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    class Loader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        loader.flatten_mapping(node)
        return unique((loader.construct_object(k), loader.construct_object(v)) for k, v in node.value)
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
    except yaml.YAMLError:
        raise ValueError("Invalid YAML declaration; values suppressed") from None


def check_files(root, files):
    """Retained for the Doppler/account vendor contracts, not general generation."""
    return all(read_json(root / path) == value for path, value in files.items())


def read_repository(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted((root / "gitops").rglob("*")):
        if path.is_file() and path.suffix in (".json", ".yaml", ".yml"):
            require(not path.is_symlink() and path.resolve().is_relative_to(root))
            files[str(path.relative_to(root))] = read_json(path)
    return files


def resources_at(root, directory, stack=()):
    """Follow local resources only. Kustomize itself remains the render authority."""
    root = Path(root).resolve()
    directory = Path(directory).resolve()
    require(directory.is_relative_to(root / "gitops") and directory not in stack)
    kustomization = read_json(directory / "kustomization.yaml")
    require(kustomization.get("kind") == "Kustomization")
    require(set(kustomization).issubset({"apiVersion", "kind", "resources", "patchesStrategicMerge"}))
    objects = []
    for resource in kustomization.get("resources", []):
        require(isinstance(resource, str) and "://" not in resource)
        path = (directory / resource).resolve()
        require(path.is_relative_to(root / "gitops"))
        if path.is_dir():
            objects.extend(resources_at(root, path, (*stack, directory)))
        else:
            objects.append(read_json(path))
    if kustomization.get("patchesStrategicMerge"):
        for patch in kustomization["patchesStrategicMerge"]:
            require(isinstance(patch, str) and "://" not in patch)
            path = (directory / patch).resolve()
            require(path.is_relative_to(directory) and path.is_file())
        # Let native Kustomize perform patch merging; do not implement a renderer.
        result = subprocess.run(["kubectl", "kustomize", str(directory)],
                                capture_output=True, text=True, timeout=30, check=False)
        require(result.returncode == 0)
        objects = [o for o in yaml.safe_load_all(result.stdout) if o]
    return objects


def validate_repository(root):
    root = Path(root).resolve()
    config = validate(read_json(root / SETTINGS_PATH))
    files = read_repository(root)
    root_objects = resources_at(root, root / ROOT_PATH)
    # A file left in root but removed from its resource list would silently orphan an app.
    require({o["metadata"]["name"] for o in root_objects} == {
        o["metadata"]["name"] for path, o in files.items()
        if str(Path(path).parent) == ROOT_PATH and o.get("kind") in ("Application", "AppProject")})
    projects = {o["metadata"]["name"]: o["spec"] for o in root_objects if o.get("kind") == "AppProject"}
    active = []
    for app in (o for o in root_objects if o.get("kind") == "Application"):
        spec = app["spec"]
        policy = spec["syncPolicy"]
        require(policy["automated"] == {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False})
        require({"ServerSideApply=true", "FailOnSharedResource=true"}.issubset(policy["syncOptions"]))
        require(not app["metadata"].get("finalizers"))
        project = projects[spec["project"]]
        require(spec["destination"] in project["destinations"])
        sources = spec.get("sources", [spec.get("source")])
        for source in sources:
            require(source["repoURL"] in project["sourceRepos"])
            if "chart" in source:
                require(match(source["targetRevision"], r"v?[0-9]+\.[0-9]+\.[0-9]+"))
                require(source.get("helm", {}).get("kubeVersion") == config["kube_version"])
                for value in source.get("helm", {}).get("valueFiles", []):
                    require(value.startswith("$values/") and value[8:] in files)
            else:
                require(source["repoURL"] == config["repo_url"] and source["targetRevision"] == config["revision"])
            if "path" not in source:
                continue
            objects = resources_at(root, root / source["path"])
            active.extend(objects)
            seen = set()
            for obj in objects:
                group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
                namespace = obj["metadata"].get("namespace")
                scope = "namespace" if namespace else "cluster"
                require({"group": group, "kind": obj["kind"]} in project[scope + "ResourceWhitelist"])
                if namespace:
                    require(dict(spec["destination"], namespace=namespace) in project["destinations"])
                identity = (group, obj["kind"], namespace, obj["metadata"]["name"])
                require(identity not in seen)
                seen.add(identity)
    # Check effective draft overlays too, not partial patch objects or stale base fields.
    patch_paths = {str(Path(path).parent / patch) for path, obj in files.items()
                   if obj.get("kind") == "Kustomization" for patch in obj.get("patchesStrategicMerge", [])}
    def key(obj):
        return (obj["apiVersion"], obj["kind"], obj["metadata"].get("namespace"), obj["metadata"]["name"])
    declarations = {key(o): o for path, o in files.items()
                    if path not in patch_paths and "metadata" in o and "kind" in o}
    for path, obj in files.items():
        if obj.get("kind") == "Kustomization" and obj.get("patchesStrategicMerge"):
            declarations.update({key(o): o for o in resources_at(root, root / Path(path).parent)})
    for obj in declarations.values():
        kind = obj.get("kind")
        require(kind != "Secret")
        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            pod = obj["spec"]["template"]["spec"]
            for container in pod.get("containers", []) + pod.get("initContainers", []):
                require(match(container["image"], r".+@sha256:[a-f0-9]{64}"))
            if kind == "StatefulSet" and obj["spec"].get("volumeClaimTemplates"):
                require(obj["spec"]["persistentVolumeClaimRetentionPolicy"]["whenDeleted"] == "Retain")
        if kind == "DopplerSecret":
            require(obj["spec"]["verifyTLS"] is True)
        if kind == "Gateway":
            for server in obj["spec"]["servers"]:
                require(all("*" not in host for host in server["hosts"]))
                if server["port"]["number"] == 80:
                    require(server.get("tls", {}).get("httpsRedirect") is True)
                if server.get("tls", {}).get("mode") == "SIMPLE":
                    cert = next(o for o in declarations.values() if o.get("kind") == "Certificate"
                                and o["metadata"].get("namespace") == obj["metadata"].get("namespace")
                                and o["spec"]["secretName"] == server["tls"]["credentialName"])
                    require({h.removeprefix("./") for h in server["hosts"]}.issubset(cert["spec"]["dnsNames"]))
        if kind == "HorizontalPodAutoscaler":
            hpa = obj["spec"]
            require(1 <= hpa["minReplicas"] <= hpa["maxReplicas"])
            target = hpa["scaleTargetRef"]
            deployment = next(o for o in declarations.values() if o.get("kind") == target["kind"]
                              and o["metadata"]["name"] == target["name"]
                              and o["metadata"].get("namespace") == obj["metadata"].get("namespace"))
            require("replicas" not in deployment["spec"])
            require(any(rule.get("name") == target["name"] and "/spec/replicas" in rule.get("jsonPointers", [])
                        for a in root_objects if a.get("kind") == "Application"
                        and "RespectIgnoreDifferences=true" in a["spec"]["syncPolicy"]["syncOptions"]
                        for rule in a["spec"].get("ignoreDifferences", [])))
    issuers = {o["metadata"]["name"]: o for o in active if o["kind"] == "ClusterIssuer"}
    for cert in (o for o in active if o["kind"] == "Certificate"):
        issuer = issuers[cert["spec"]["issuerRef"]["name"]]["spec"]["acme"]
        names = {name for solver in issuer["solvers"] for name in solver.get("selector", {}).get("dnsNames", [])}
        require(set(cert["spec"]["dnsNames"]).issubset(names))
    base = files[BASE_PATH]
    require(base["configs"]["params"]["server.insecure"] is False)
    require(base["configs"]["secret"]["createSecret"] is False)
    require(files[ROOT_PATH + "/root.yaml"]["spec"]["source"]["path"] == ROOT_PATH)
    for name in ("argocd", "istio", "cert-manager"):
        lock = files["gitops/platform/" + name + "/versions.json"]
        app = files[ROOT_PATH + "/" + name + ".yaml"]
        for source in app["spec"]["sources"]:
            if "chart" in source:
                require(source["targetRevision"] == lock["version"] and source["repoURL"] == lock["repository"])
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_repository(args.repo_root)
        print("Git-owned declarations validated. No files or cluster state changed.")
        return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        print("GitOps validation failed; check declarations, references and safety policies. Values suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
