#!/usr/bin/env python3
"""Generate reviewed Argo CD and optional Istio declarations; no cluster access."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

CHART_VERSION = "10.8.2"
CHART_REPO = "https://argoproj.github.io/argo-helm"
ROOT_PATH = "gitops/clusters/oci-a1/root"
SETTINGS_PATH = "gitops/clusters/oci-a1/bootstrap.json"
BASE_PATH = "gitops/platform/argocd/base.values.json"
ACCOUNTS_PATH = "gitops/platform/argocd/accounts.values.json"
ENV_PATH = "gitops/clusters/oci-a1/argocd.values.json"
NAMESPACE = "argocd"
ISTIO_SETTINGS_PATH = "gitops/clusters/oci-a1/istio.json"
ISTIO_MANIFEST_PATH = "gitops/clusters/oci-a1/istio"
ISTIO_REPO = "https://blob.istio.io/istio-release/charts"
ISTIO_VERSION = "1.30.4"
INGRESS_SETTINGS_PATH = "gitops/clusters/oci-a1/ingress.json"
INGRESS_VALUES_PATH = "gitops/clusters/oci-a1/ingress.values.json"
K3S_SETTINGS_PATH = "ansible/inventories/oci-a1/settings.json"


def require(condition):
    if not condition:
        raise ValueError("Invalid or unreviewed Argo CD bootstrap input; values are not displayed.")


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


def resource(kind, name, spec, wave="0"):
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": kind,
            "metadata": {"name": name, "namespace": NAMESPACE,
                         "annotations": {"argocd.argoproj.io/sync-wave": wave}}, "spec": spec}


def sync_policy():
    return {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
            "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"]}


def render_istio(config, settings):
    require(isinstance(settings, dict) and set(settings) == {
        "enabled", "reviewed", "mode", "namespace", "gateway_service_type"})
    require(type(settings["enabled"]) is bool and type(settings["reviewed"]) is bool)
    require(settings["mode"] == "sidecar" and settings["namespace"] == "istio-system")
    require(settings["gateway_service_type"] == "ClusterIP")
    if not settings["enabled"]:
        return {}, {}
    require(settings["reviewed"] is True)
    require(32 <= int(config["kube_version"].split(".")[1]) <= 36)
    destination = {"server": "https://kubernetes.default.svc", "namespace": settings["namespace"]}
    project = resource("AppProject", "platform-istio", {
        "description": "Administrator-only Istio CRDs, admission and cluster RBAC",
        "sourceRepos": [config["repo_url"], ISTIO_REPO], "destinations": [destination],
        "clusterResourceWhitelist": [{"group": group, "kind": kind} for group, kind in [
            ("", "Namespace"), ("apiextensions.k8s.io", "CustomResourceDefinition"),
            ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
            ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
            ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration")]],
        "namespaceResourceWhitelist": [{"group": group, "kind": kind} for group, kind in [
            ("", "ServiceAccount"), ("", "Service"), ("", "ConfigMap"), ("apps", "Deployment"),
            ("rbac.authorization.k8s.io", "Role"), ("rbac.authorization.k8s.io", "RoleBinding")]],
    }, "-10")
    sources = [{"repoURL": ISTIO_REPO, "chart": chart, "targetRevision": ISTIO_VERSION,
                "helm": {"releaseName": release, "kubeVersion": config["kube_version"],
                         "valueFiles": ["$values/gitops/platform/istio/" + chart + ".values.json"]}}
               for chart, release in [("base", "istio-base"), ("istiod", "istiod"), ("gateway", "istio-ingress")]]
    sources.append({"repoURL": config["repo_url"], "targetRevision": config["revision"],
                    "ref": "values", "path": ISTIO_MANIFEST_PATH})
    policy = sync_policy()
    policy["syncOptions"].append("RespectIgnoreDifferences=true")
    app = resource("Application", "istio", {
        "project": "platform-istio", "destination": destination, "sources": sources,
        "syncPolicy": policy,
        # CA bundles are generated/rotated by istiod, never pinned in Git.
        "ignoreDifferences": [{"group": "admissionregistration.k8s.io", "kind": kind,
                               "jqPathExpressions": [".webhooks[]?.clientConfig.caBundle"]}
                              for kind in ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"]],
    }, "20")
    ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {
        "name": settings["namespace"], "annotations": {
            "argocd.argoproj.io/sync-wave": "-20", "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}}}
    return {"istio-project.json": project, "istio.json": app}, {
        ISTIO_MANIFEST_PATH + "/namespace.json": ns,
        ISTIO_MANIFEST_PATH + "/kustomization.yaml": {
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["namespace.json"]}}


def ingress_enabled(settings):
    require(isinstance(settings, dict) and set(settings) == {
        "enabled", "reviewed", "exposure", "network_reviewed", "tls_ready_reviewed", "mesh_namespaces", "routes"})
    require(all(type(settings[key]) is bool for key in ["enabled", "reviewed", "network_reviewed", "tls_ready_reviewed"]))
    require(settings["exposure"] == "k3s-servicelb")
    require(isinstance(settings["mesh_namespaces"], list) and isinstance(settings["routes"], list))
    if not settings["enabled"]:
        return False
    require(all(settings[key] for key in ["reviewed", "network_reviewed", "tls_ready_reviewed"]))
    namespaces = settings["mesh_namespaces"]
    dns_label = r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
    require(namespaces and all(match(n, dns_label) and not n.startswith("kube-") and n not in
                              {"default", "argocd", "istio-system"} for n in namespaces))
    require(len(set(namespaces)) == len(namespaces) and settings["routes"])
    names, hosts, backends = set(), set(), set()
    for route in settings["routes"]:
        require(isinstance(route, dict) and set(route) == {
            "name", "host", "tls_secret", "backend_namespace", "backend_service", "backend_port", "path_prefix"})
        require(match(route["name"], r"[a-z][a-z0-9-]{0,39}") and not route["name"].endswith("-"))
        require(match(route["tls_secret"], dns_label) and match(route["backend_service"], dns_label))
        host = route["host"]
        require(isinstance(host, str) and len(host) <= 253 and "." in host)
        require(all(match(label, dns_label) for label in host.split(".")))
        require(isinstance(route["backend_namespace"], str) and route["backend_namespace"] in namespaces)
        require(type(route["backend_port"]) is int and 1 <= route["backend_port"] <= 65535)
        require(match(route["path_prefix"], r"/[A-Za-z0-9/_~.-]*") and ".." not in route["path_prefix"])
        require(route["name"] not in names and host not in hosts)
        backend = (route["backend_namespace"], route["backend_service"])
        # One rule per backend: duplicate DestinationRules have ambiguous merging.
        require(backend not in backends)
        names.add(route["name"])
        hosts.add(host)
        backends.add(backend)
    return True


def add_ingress(files, settings):
    require(ROOT_PATH + "/istio.json" in files)
    project = files[ROOT_PATH + "/istio-project.json"]["spec"]
    for namespace in sorted(settings["mesh_namespaces"]):
        project["destinations"].append({"server": "https://kubernetes.default.svc", "namespace": namespace})
    project["namespaceResourceWhitelist"] += [
        {"group": "networking.istio.io", "kind": kind} for kind in ["Gateway", "VirtualService", "DestinationRule"]] + [
        {"group": "security.istio.io", "kind": "PeerAuthentication"}]
    expose_gateway(files)

    def add(name, obj, namespace=None, wave="30"):
        meta = obj.setdefault("metadata", {})
        meta["name"] = name
        if namespace:
            meta["namespace"] = namespace
        meta["annotations"] = {"argocd.argoproj.io/sync-wave": wave}
        filename = name + "-" + obj["kind"].lower() + ".json"
        files[ISTIO_MANIFEST_PATH + "/" + filename] = obj
        files[ISTIO_MANIFEST_PATH + "/kustomization.yaml"]["resources"].append(filename)

    for namespace in sorted(settings["mesh_namespaces"]):
        add(namespace, {"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "labels": {"istio-injection": "enabled"}}}, wave="15")
        files[ISTIO_MANIFEST_PATH + "/" + namespace + "-namespace.json"]["metadata"]["annotations"][
            "argocd.argoproj.io/sync-options"] = "Prune=false,Delete=false"
        add("require-mtls-" + namespace, {"apiVersion": "security.istio.io/v1", "kind": "PeerAuthentication",
            "spec": {"mtls": {"mode": "STRICT"}}}, namespace)
    for route in sorted(settings["routes"], key=lambda r: r["name"]):
        name, host = "external-" + route["name"], route["host"]
        backend = route["backend_service"] + "." + route["backend_namespace"] + ".svc.cluster.local"
        add(name, {"apiVersion": "networking.istio.io/v1", "kind": "DestinationRule", "spec": {
            "host": backend, "exportTo": ["."], "workloadSelector": {"matchLabels": {"app": "istio-ingress"}},
            "trafficPolicy": {"tls": {"mode": "ISTIO_MUTUAL"}}}}, "istio-system")
        add(name, {"apiVersion": "networking.istio.io/v1", "kind": "Gateway", "spec": {
            "selector": {"app": "istio-ingress"}, "servers": [
                {"port": {"number": 80, "name": "http", "protocol": "HTTP"},
                 "hosts": ["./" + host], "tls": {"httpsRedirect": True}},
                {"port": {"number": 443, "name": "https", "protocol": "HTTPS"}, "hosts": ["./" + host],
                 "tls": {"mode": "SIMPLE", "credentialName": route["tls_secret"], "minProtocolVersion": "TLSV1_2"}}]}},
            "istio-system", "40")
        add(name, {"apiVersion": "networking.istio.io/v1", "kind": "VirtualService", "spec": {
            "hosts": [host], "gateways": [name], "exportTo": ["."], "http": [
                {"match": [{"port": 80}], "redirect": {"scheme": "https", "port": 443}},
                {"match": [{"port": 443, "uri": {"prefix": route["path_prefix"]}}],
                 "route": [{"destination": {"host": backend, "port": {"number": route["backend_port"]}}}]}]}},
            "istio-system", "40")
    files[ISTIO_MANIFEST_PATH + "/kustomization.yaml"]["resources"].sort()


def expose_gateway(files):
    source = files[ROOT_PATH + "/istio.json"]["spec"]["sources"][2]
    reference = "$values/" + INGRESS_VALUES_PATH
    if reference not in source["helm"]["valueFiles"]:
        source["helm"]["valueFiles"].append(reference)
    files[INGRESS_VALUES_PATH] = {"service": {
        "type": "LoadBalancer", "allocateLoadBalancerNodePorts": False,
        "externalTrafficPolicy": "Cluster", "ports": [
            {"name": "http2", "port": 80, "protocol": "TCP", "targetPort": 80},
            {"name": "https", "port": 443, "protocol": "TCP", "targetPort": 443}]}}


def render(config, istio=None, ingress=None):
    validate(config)
    destination = {"server": "https://kubernetes.default.svc", "namespace": NAMESPACE}
    root_project = resource("AppProject", "bootstrap-root", {
        "description": "Administrator-only root Application ownership",
        "sourceRepos": [config["repo_url"]], "destinations": [destination],
        "clusterResourceWhitelist": [],
        "namespaceResourceWhitelist": [{"group": "argoproj.io", "kind": k} for k in ["Application", "AppProject"]],
    }, "-20")
    platform_project = resource("AppProject", "platform-argocd", {
        "description": "Administrator-only Argo CD installation; cluster RBAC is privileged",
        "sourceRepos": [config["repo_url"], CHART_REPO], "destinations": [destination],
        "clusterResourceWhitelist": [
            {"group": "apiextensions.k8s.io", "kind": "CustomResourceDefinition"},
            {"group": "rbac.authorization.k8s.io", "kind": "ClusterRole"},
            {"group": "rbac.authorization.k8s.io", "kind": "ClusterRoleBinding"}],
        "namespaceResourceWhitelist": [
            {"group": "", "kind": k} for k in ["ConfigMap", "Service", "ServiceAccount"]] + [
            {"group": "apps", "kind": k} for k in ["Deployment", "StatefulSet"]] + [
            {"group": "rbac.authorization.k8s.io", "kind": k} for k in ["Role", "RoleBinding"]] + [
            {"group": "networking.k8s.io", "kind": "NetworkPolicy"}],
    }, "-10")
    root = resource("Application", "oci-a1-root", {
        "project": "bootstrap-root", "destination": destination,
        "source": {"repoURL": config["repo_url"], "targetRevision": config["revision"], "path": ROOT_PATH},
        "syncPolicy": sync_policy(),
    })
    application = resource("Application", "argocd", {
        "project": "platform-argocd", "destination": destination,
        "sources": [
            {"repoURL": CHART_REPO, "chart": "argo-cd", "targetRevision": CHART_VERSION,
             "helm": {"releaseName": "argocd", "kubeVersion": config["kube_version"],
                      "valueFiles": ["$values/" + p for p in [BASE_PATH, ENV_PATH, ACCOUNTS_PATH]]}},
            {"repoURL": config["repo_url"], "targetRevision": config["revision"], "ref": "values"}],
        "syncPolicy": sync_policy(),
    }, "10")
    resources = {"root-project.json": root_project, "platform-project.json": platform_project,
                 "root.json": root, "argocd.json": application}
    additions, files = render_istio(config, istio) if istio is not None else ({}, {})
    resources.update(additions)
    files.update({ROOT_PATH + "/" + name: value for name, value in resources.items()})
    files[ROOT_PATH + "/kustomization.yaml"] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": sorted(resources)}
    files[ENV_PATH] = {"kubeVersionOverride": config["kube_version"]}
    if ingress is not None and ingress_enabled(ingress):
        add_ingress(files, ingress)
    return files


def render_repository(root):
    path = root / ISTIO_SETTINGS_PATH
    ingress_path = root / INGRESS_SETTINGS_PATH
    ingress = read_json(ingress_path) if ingress_path.exists() else None
    config = validate(read_json(root / SETTINGS_PATH))
    if ingress is not None and ingress_enabled(ingress):
        # Check the same Git-owned first-install settings; never read tokens or SSH.
        k3s = read_json(root / K3S_SETTINGS_PATH)
        module_path = Path(__file__).resolve().parents[1] / "ansible/filter_plugins/k3s_config.py"
        spec = importlib.util.spec_from_file_location("k3s_config", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        k3s = module.validate(k3s)
        require(k3s["servicelb"] is True and k3s["network_reviewed"] is True)
        require(k3s["version"].split("+")[0].removeprefix("v") == config["kube_version"])
    files = render(config, read_json(path) if path.exists() else None, ingress)
    doppler_spec = importlib.util.spec_from_file_location("doppler_gitops", Path(__file__).with_name("doppler_gitops.py"))
    doppler = importlib.util.module_from_spec(doppler_spec)
    doppler_spec.loader.exec_module(doppler)
    doppler_path = root / doppler.SETTINGS
    additions = doppler.render(config, read_json(doppler_path)) if doppler_path.exists() else {}
    doppler.check_previous(root, additions, read_json)
    files.update(additions)
    for name in ["doppler-project.json", "doppler.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    cert_spec = importlib.util.spec_from_file_location("cert_manager_gitops", Path(__file__).with_name("cert_manager_gitops.py"))
    cert = importlib.util.module_from_spec(cert_spec)
    cert_spec.loader.exec_module(cert)
    cert_path = root / cert.SETTINGS
    additions = cert.render(config, read_json(cert_path)) if cert_path.exists() else {}
    require(not (root / ROOT_PATH / "cert-manager.json").exists() or ROOT_PATH + "/cert-manager.json" in additions)
    files.update(additions)
    for name in ["cert-manager-project.json", "cert-manager.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    cnpg_spec = importlib.util.spec_from_file_location("cnpg_gitops", Path(__file__).with_name("cnpg_gitops.py"))
    cnpg = importlib.util.module_from_spec(cnpg_spec)
    cnpg_spec.loader.exec_module(cnpg)
    cnpg_path = root / cnpg.SETTINGS
    additions = cnpg.render(config, read_json(cnpg_path)) if cnpg_path.exists() else {}
    require(not (root / ROOT_PATH / "cnpg.json").exists() or ROOT_PATH + "/cnpg.json" in additions)
    files.update(additions)
    for name in ["cnpg-project.json", "cnpg.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    pg_spec = importlib.util.spec_from_file_location("postgresql_gitops", Path(__file__).with_name("postgresql_gitops.py"))
    pg = importlib.util.module_from_spec(pg_spec)
    pg_spec.loader.exec_module(pg)
    pg_path = root / pg.SETTINGS
    additions = pg.render(config, read_json(pg_path)) if pg_path.exists() else {}
    require(not (root / ROOT_PATH / "postgresql.json").exists() or ROOT_PATH + "/postgresql.json" in additions)
    require(not (root / pg.PATH / "cluster.json").exists() or pg.PATH + "/cluster.json" in additions)
    files.update(additions)
    for name in ["postgresql-project.json", "postgresql.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    redis_spec = importlib.util.spec_from_file_location("redis_gitops", Path(__file__).with_name("redis_gitops.py"))
    redis = importlib.util.module_from_spec(redis_spec)
    redis_spec.loader.exec_module(redis)
    redis_path = root / redis.SETTINGS
    additions = redis.render(config, read_json(redis_path)) if redis_path.exists() else {}
    require(not (root / ROOT_PATH / "redis.json").exists() or ROOT_PATH + "/redis.json" in additions)
    files.update(additions)
    for name in ["redis-project.json", "redis.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    monitoring_spec = importlib.util.spec_from_file_location("monitoring_gitops", Path(__file__).with_name("monitoring_gitops.py"))
    monitoring = importlib.util.module_from_spec(monitoring_spec)
    monitoring_spec.loader.exec_module(monitoring)
    monitoring_path = root / monitoring.SETTINGS
    additions = monitoring.render(config, read_json(monitoring_path)) if monitoring_path.exists() else {}
    require(not (root / ROOT_PATH / "monitoring.json").exists() or ROOT_PATH + "/monitoring.json" in additions)
    previous_monitoring = root / ROOT_PATH / "monitoring.json"
    if previous_monitoring.exists() and "sources" in read_json(previous_monitoring).get("spec", {}):
        require("sources" in additions[ROOT_PATH + "/monitoring.json"]["spec"])
    files.update(additions)
    for name in ["monitoring-project.json", "monitoring.json"]:
        if ROOT_PATH + "/" + name in additions:
            files[ROOT_PATH + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT_PATH + "/kustomization.yaml"]["resources"].sort()
    public_spec = importlib.util.spec_from_file_location("argocd_ingress_gitops", Path(__file__).with_name("argocd_ingress_gitops.py"))
    public = importlib.util.module_from_spec(public_spec)
    public_spec.loader.exec_module(public)
    public_path = root / public.SETTINGS
    if public_path.exists():
        public.add(root, config, read_json(public_path), files, read_json, expose_gateway)
    require(not (root / ROOT_PATH / "argocd-ingress.json").exists() or ROOT_PATH + "/argocd-ingress.json" in files)
    old_kustomization = root / ISTIO_MANIFEST_PATH / "kustomization.yaml"
    if old_kustomization.exists():
        # prune=false is not uninstall: refuse to silently leave old public routes active.
        previous = read_json(old_kustomization)["resources"]
        current = files.get(ISTIO_MANIFEST_PATH + "/kustomization.yaml", {}).get("resources", [])
        require(set(previous).issubset(set(current)))
    return files


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def encoded(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def check_files(root, files):
    return all((root / path).is_file() and (root / path).read_text() == encoded(value) for path, value in files.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve()
        files = render_repository(root)
        # Do not silently orphan a previously generated installation when disabling it.
        previous_istio = root / ROOT_PATH / "istio.json"
        require(not previous_istio.exists() or ROOT_PATH + "/istio.json" in files)
        for path in files:
            target = root / path
            require(target.resolve().is_relative_to(root) and not target.is_symlink())
            require(not any(parent.is_symlink() for parent in target.parents if parent.is_relative_to(root)))
        if args.write:
            for path, value in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as temporary:
                    try:
                        temporary.write(encoded(value))
                        temporary.flush()
                        os.replace(temporary.name, target)
                    finally:
                        if os.path.exists(temporary.name):
                            os.unlink(temporary.name)
            print("GitOps declarations generated; review and commit separately. No deployment occurred.")
        else:
            require(check_files(root, files))
            print("GitOps declarations match reviewed input.")
        return 0
    except (ValueError, TypeError, OSError):
        print("GitOps generation blocked: missing, invalid or mismatched input. Values are not displayed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
