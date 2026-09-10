"""Public Argo CD TLS, certificate ownership and Git dependency boundaries."""
import os
from pathlib import Path
import subprocess
import unittest

from test_argocd_gitops import manifest_files, layout, ROOT, load


class ArgoCDPublicIngressTests(unittest.TestCase):
    def setUp(self):
        self.gitops = load("gitops_validate")
        self.public = layout("argocd-ingress")

    def manifests(self):
        return manifest_files()

    def test_only_requested_sni_reaches_argocd_over_existing_tls(self):
        files = self.manifests()
        gateway = files[self.public.PATH + "/gateway.yaml"]["spec"]
        self.assertEqual(gateway["servers"][1]["tls"], {"mode": "PASSTHROUGH"})
        self.assertEqual(gateway["servers"][1]["hosts"], ["./argo.rvkang.app"])
        route = files[self.public.PATH + "/virtual-service.yaml"]["spec"]
        self.assertEqual(route["tls"][0]["match"], [{"port": 443, "sniHosts": ["argo.rvkang.app"]}])
        self.assertEqual(route["tls"][0]["route"][0]["destination"], {
            "host": "argocd-server.argocd.svc.cluster.local", "port": {"number": 443}})
        self.assertEqual(route["http"][0]["redirect"], {"scheme": "https", "port": 443})
        self.assertEqual(files[self.public.ENV]["configs"]["cm"]["url"], "https://argo.rvkang.app")
        self.assertFalse(any(o.get("kind") in {"PeerAuthentication", "Secret"} for o in files.values()))

    def test_certificate_is_issued_before_public_routes_and_owned_only_by_cert_manager(self):
        files = self.manifests()
        certificate = files[self.public.PATH + "/certificate.yaml"]
        self.assertEqual(certificate["spec"]["secretName"], "argocd-server-tls")
        self.assertEqual(certificate["spec"]["secretTemplate"]["labels"], {"app.kubernetes.io/part-of": "argocd"})
        self.assertEqual(certificate["spec"]["dnsNames"], ["argo.rvkang.app"])
        self.assertEqual(certificate["spec"]["privateKey"]["rotationPolicy"], "Always")
        self.assertLess(int(certificate["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                        int(files[self.public.PATH + "/gateway.yaml"]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
        issuer = files[self.public.PATH + "/issuer.yaml"]["spec"]["acme"]
        self.assertEqual(issuer["solvers"][0]["selector"], {"dnsNames": ["argo.rvkang.app", "grafana.rvkang.app", "auth.rvkang.app"]})
        self.assertEqual(issuer["solvers"][0]["dns01"]["cloudflare"]["apiTokenSecretRef"],
                         {"name": "cloudflare-dns-api-token", "key": "api-token"})
        project = files[self.public.ROOT + "/argocd-ingress-project.yaml"]["spec"]
        self.assertNotIn({"group": "", "kind": "Secret"}, project["namespaceResourceWhitelist"])


    def test_servicelb_overlay_is_shared_without_duplicate_values(self):
        files = self.manifests()
        values = files[self.gitops.ROOT_PATH + "/istio.yaml"]["spec"]["sources"][2]["helm"]["valueFiles"]
        self.assertEqual(values.count("$values/" + self.gitops.INGRESS_VALUES_PATH), 1)
        service = files[self.gitops.INGRESS_VALUES_PATH]["service"]
        self.assertEqual([p["port"] for p in service["ports"]], [80, 443])
        self.assertFalse(service["allocateLoadBalancerNodePorts"])

    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("CERT_MANAGER_TEST_CHART")
                         and os.environ.get("ISTIO_TEST_CHART_DIR") and os.environ.get("ARGOCD_TEST_CHART"), "pinned local charts not supplied")
    def test_public_resources_match_pinned_crds_and_chart_backend(self):
        import yaml
        helm = os.environ["HELM_TEST_BINARY"]
        def render(chart, release, namespace, values=()):
            args = [helm, "template", release, str(chart), "--namespace", namespace, "--kube-version", "1.36.4"]
            for value in values:
                args += ["--values", str(ROOT / value)]
            result = subprocess.run(args, capture_output=True, text=True, check=True, timeout=60)
            return [o for o in yaml.safe_load_all(result.stdout) if o]
        objects = render(Path(os.environ["ISTIO_TEST_CHART_DIR"]) / "base-1.30.4.tgz", "istio-base", "istio-system")
        objects += render(os.environ["CERT_MANAGER_TEST_CHART"], "cert-manager", "cert-manager",
                          ["gitops/platform/cert-manager/base.values.yaml"])
        crds = {o["spec"]["names"]["kind"]: o for o in objects if o["kind"] == "CustomResourceDefinition"}
        def check(value, schema):
            if isinstance(value, dict):
                self.assertTrue(set(schema.get("required", [])).issubset(value))
                for key, item in value.items():
                    shape = schema.get("properties", {}).get(key)
                    if shape is None:
                        self.assertTrue(schema.get("additionalProperties") or schema.get("x-kubernetes-preserve-unknown-fields"), key)
                    else:
                        check(item, shape)
            elif isinstance(value, list):
                for item in value:
                    check(item, schema["items"])
            elif "enum" in schema:
                self.assertIn(value, schema["enum"])
        files = self.manifests()
        for path, obj in files.items():
            if path.startswith(self.public.PATH + "/") and obj["kind"] in crds:
                versions = crds[obj["kind"]]["spec"]["versions"]
                schema = next(v for v in versions if v["name"] == "v1")["schema"]["openAPIV3Schema"]
                check(obj["spec"], schema["properties"]["spec"])
        objects = render(os.environ["ARGOCD_TEST_CHART"], "argocd", "argocd", [
            "gitops/platform/argocd/base.values.yaml", self.public.ENV, "gitops/platform/argocd/accounts.values.yaml"])
        service = next(o for o in objects if o["kind"] == "Service" and o["metadata"]["name"] == "argocd-server")
        self.assertEqual(next(p for p in service["spec"]["ports"] if p["port"] == 443)["targetPort"], 8080)
        cm = next(o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "argocd-cmd-params-cm")
        self.assertEqual(cm["data"]["server.insecure"], "false")
