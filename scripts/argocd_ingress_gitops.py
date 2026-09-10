"""Argo CD HTTPS passthrough with Cloudflare DNS-01; no secret values or API calls."""
import re

SETTINGS = "gitops/clusters/oci-a1/argocd-ingress.json"
PATH = "gitops/clusters/oci-a1/argocd-ingress"
ROOT = "gitops/clusters/oci-a1/root"
ENV = "gitops/clusters/oci-a1/argocd.values.json"
TOKEN_SECRET = "cloudflare-dns-api-token"
ISSUER = "argocd-cloudflare"


def require(condition):
    if not condition:
        raise ValueError("Invalid Argo CD public ingress or missing Git dependency; values are not displayed.")


def add(root, bootstrap, config, files, read, expose_gateway):
    require(isinstance(config, dict) and set(config) == {"enabled", "host", "dns_zone"})
    require(type(config["enabled"]) is bool)
    for field in ("host", "dns_zone"):
        value = config[field]
        require(isinstance(value, str) and len(value) <= 253 and "." in value)
        require(all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in value.split(".")))
    host, zone = config["host"], config["dns_zone"]
    require(host == zone or host.endswith("." + zone))
    if not config["enabled"]:
        return
    require(ROOT + "/istio.json" in files and ROOT + "/cert-manager.json" in files)
    k3s = read(root / "ansible/inventories/oci-a1/settings.json")
    require(k3s.get("servicelb") is True and k3s.get("network_reviewed") is True)
    ingress = read(root / "gitops/clusters/oci-a1/ingress.json")
    require(not ingress["enabled"] or host not in {r["host"] for r in ingress["routes"]})
    doppler = read(root / "gitops/clusters/oci-a1/doppler.json")
    require(doppler["enabled"] and doppler["sync_enabled"])
    require(any(m["target_namespace"] == "cert-manager" and m["target_secret"] == TOKEN_SECRET
                and m["type"] == "Opaque" and m["keys"] == {"CLOUDFLARE_DNS_API_TOKEN_": "api-token"}
                for m in doppler["mappings"]))
    require(not any(m["target_namespace"] == "argocd" and m["target_secret"] == "argocd-server-tls"
                    for m in doppler["mappings"]))
    base = read(root / "gitops/platform/argocd/base.values.json")
    require(base["configs"]["params"]["server.insecure"] is False)
    require(base["fullnameOverride"] == "argocd" and base["server"]["service"]["type"] == "ClusterIP")
    expose_gateway(files)
    files[ENV].update({"global": {"domain": host}, "configs": {"cm": {"url": "https://" + host}}})
    resources = []

    def resource(filename, api, kind, name, namespace, spec, wave):
        metadata = {"name": name, "annotations": {"argocd.argoproj.io/sync-wave": str(wave)}}
        if namespace:
            metadata["namespace"] = namespace
        files[PATH + "/" + filename] = {"apiVersion": api, "kind": kind, "metadata": metadata, "spec": spec}
        resources.append(filename)

    # Account registration needs no personal email; cert-manager owns the account key.
    resource("issuer.json", "cert-manager.io/v1", "ClusterIssuer", ISSUER, None, {"acme": {
        "server": "https://acme-v02.api.letsencrypt.org/directory",
        "privateKeySecretRef": {"name": "argocd-acme-account"},
        "solvers": [{"selector": {"dnsNames": [host]}, "dns01": {"cloudflare": {
            "apiTokenSecretRef": {"name": TOKEN_SECRET, "key": "api-token"}}}}]}}, 0)
    resource("certificate.json", "cert-manager.io/v1", "Certificate", "argocd-server", "argocd", {
        "secretName": "argocd-server-tls", "dnsNames": [host],
        "issuerRef": {"name": ISSUER, "kind": "ClusterIssuer", "group": "cert-manager.io"},
        "privateKey": {"rotationPolicy": "Always", "algorithm": "RSA", "size": 2048}}, 10)
    resource("gateway.json", "networking.istio.io/v1", "Gateway", "argocd-public", "istio-system", {
        "selector": {"app": "istio-ingress"}, "servers": [
            {"port": {"number": 80, "name": "http-argocd", "protocol": "HTTP"},
             "hosts": ["./" + host], "tls": {"httpsRedirect": True}},
            {"port": {"number": 443, "name": "tls-argocd", "protocol": "TLS"},
             "hosts": ["./" + host], "tls": {"mode": "PASSTHROUGH"}}]}, 20)
    resource("virtual-service.json", "networking.istio.io/v1", "VirtualService", "argocd-public", "istio-system", {
        "hosts": [host], "gateways": ["argocd-public"], "exportTo": ["."],
        "http": [{"match": [{"port": 80}], "redirect": {"scheme": "https", "port": 443}}],
        "tls": [{"match": [{"port": 443, "sniHosts": [host]}], "route": [{"destination": {
            "host": "argocd-server.argocd.svc.cluster.local", "port": {"number": 443}}}]}]}, 20)
    # The payload already carries end-to-end application TLS. No sidecar enrollment of argocd.
    resource("destination-rule.json", "networking.istio.io/v1", "DestinationRule", "argocd-public", "istio-system", {
        "host": "argocd-server.argocd.svc.cluster.local", "exportTo": ["."],
        "workloadSelector": {"matchLabels": {"app": "istio-ingress"}},
        "trafficPolicy": {"tls": {"mode": "DISABLE"}}}, 20)
    files[PATH + "/kustomization.yaml"] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": sorted(resources)}
    destination = {"server": "https://kubernetes.default.svc", "namespace": "argocd"}
    project = {"apiVersion": "argoproj.io/v1alpha1", "kind": "AppProject",
        "metadata": {"name": "platform-argocd-ingress", "namespace": "argocd",
                     "annotations": {"argocd.argoproj.io/sync-wave": "-10"}}, "spec": {
            "description": "Argo CD public TLS and certificate issuance; administrator-only",
            "sourceRepos": [bootstrap["repo_url"]], "destinations": [destination,
                {"server": destination["server"], "namespace": "istio-system"}],
            "clusterResourceWhitelist": [{"group": "cert-manager.io", "kind": "ClusterIssuer"}],
            "namespaceResourceWhitelist": [{"group": "cert-manager.io", "kind": "Certificate"}] + [
                {"group": "networking.istio.io", "kind": k} for k in ("Gateway", "VirtualService", "DestinationRule")]}}
    app = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "argocd-ingress", "namespace": "argocd",
                     "annotations": {"argocd.argoproj.io/sync-wave": "40"}}, "spec": {
            "project": "platform-argocd-ingress", "destination": destination,
            "source": {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "path": PATH},
            "syncPolicy": {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
                "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"],
                "retry": {"limit": 5, "backoff": {"duration": "10s", "factor": 2, "maxDuration": "3m"}}}}}
    for name, obj in (("argocd-ingress-project.json", project), ("argocd-ingress.json", app)):
        files[ROOT + "/" + name] = obj
        files[ROOT + "/kustomization.yaml"]["resources"].append(name)
    files[ROOT + "/kustomization.yaml"]["resources"].sort()
    previous = root / PATH / "kustomization.yaml"
    if previous.exists():
        require(set(read(previous)["resources"]).issubset(resources))
