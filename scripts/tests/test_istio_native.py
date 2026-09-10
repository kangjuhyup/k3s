"""Official Helm render and Argo CD Lua health checks; local files only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture, load
from test_istio_gitops import istio_fixture
from test_istio_ingress import ingress_fixture


class IstioNativeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("ISTIO_TEST_CHART_DIR"), "local Helm/charts not supplied")
    def test_servicelb_render_and_istio_crd_fields(self):
        module = load("istio_validate")
        gitops = load("argocd_gitops")
        objects = module.render(ROOT, Path(os.environ["HELM_TEST_BINARY"]), Path(os.environ["ISTIO_TEST_CHART_DIR"]), "1.35.1", ingress_fixture())
        service = next(o for o in objects if o["kind"] == "Service" and o["metadata"]["name"] == "istio-ingress")
        self.assertEqual(service["spec"]["type"], "LoadBalancer")
        deployment = next(o for o in objects if o["kind"] == "Deployment" and o["metadata"]["name"] == "istio-ingress")
        self.assertEqual(deployment["spec"]["template"]["metadata"]["labels"]["app"], "istio-ingress")
        files = gitops.render(fixture(), istio_fixture(), ingress_fixture())
        # Validate each generated Istio spec against the exact pinned CRD's schema.
        crds = {o["spec"]["names"]["kind"]: o for o in objects if o["kind"] == "CustomResourceDefinition"}
        for obj in files.values():
            if obj.get("kind") not in ["Gateway", "VirtualService", "DestinationRule", "PeerAuthentication"]:
                continue
            versions = crds[obj["kind"]]["spec"]["versions"]
            schema = next(v for v in versions if v["name"] == "v1")["schema"]["openAPIV3Schema"]
            def check(value, shape):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in shape.get("properties", {}):
                            check(item, shape["properties"][key])
                        else:
                            self.assertTrue(shape.get("additionalProperties") or shape.get("x-kubernetes-preserve-unknown-fields"), key)
                elif isinstance(value, list):
                    for item in value:
                        check(item, shape["items"])
                elif "enum" in shape:
                    self.assertIn(value, shape["enum"])
            check(obj["spec"], schema["properties"]["spec"])

    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("ISTIO_TEST_CHART_DIR"), "local Helm/charts not supplied")
    def test_render_and_project_permissions(self):
        module = load("istio_validate")
        config = load("argocd_gitops")
        objects = module.render(ROOT, Path(os.environ["HELM_TEST_BINARY"]), Path(os.environ["ISTIO_TEST_CHART_DIR"]), "1.35.1")
        project = config.render(fixture(), istio_fixture())[config.ROOT_PATH + "/istio-project.json"]["spec"]
        for obj in objects:
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            scope = "namespace" if obj["metadata"].get("namespace") else "cluster"
            self.assertIn({"group": group, "kind": obj["kind"]}, project[scope + "ResourceWhitelist"])
        crds = [o for o in objects if o["kind"] == "CustomResourceDefinition"]
        self.assertTrue(all(int(o["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-wave", "0")) < 10 for o in crds))
        with tempfile.TemporaryDirectory() as directory, self.assertRaises((OSError, ValueError)):
            module.render(ROOT, Path(os.environ["HELM_TEST_BINARY"]), Path(directory), "1.35.1")

    @unittest.skipUnless(os.environ.get("ARGOCD_TEST_BINARY"), "local Argo CD CLI not supplied")
    def test_crd_health_real_lua(self):
        cm_values = json.loads((ROOT / "gitops/platform/argocd/base.values.json").read_text())["configs"]["cm"]
        key = "resource.customizations.health.apiextensions.k8s.io_CustomResourceDefinition"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cm = folder / "cm.json"
            cm.write_text(json.dumps({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "argocd-cm"}, "data": {key: cm_values[key]}}))
            secret = folder / "secret.json"
            secret.write_text(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "argocd-secret"}}))
            resource = folder / "crd.json"
            established = {"type": "Established", "status": "True"}
            for conditions, expected in [([], "Progressing"), ([established], "Healthy"),
                    ([established, {"type": "NamesAccepted", "status": "False"}], "Degraded"),
                    ([{ "type": "Terminating", "status": "True"}, established], "Degraded")]:
                resource.write_text(json.dumps({"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition",
                    "metadata": {"name": "synthetic.example.invalid"}, "status": {"conditions": conditions}}))
                result = subprocess.run([os.environ["ARGOCD_TEST_BINARY"], "admin", "settings", "resource-overrides", "health", str(resource),
                    "--argocd-cm-path", str(cm), "--argocd-secret-path", str(secret), "--config", str(folder / "absent-config"),
                    "--kubeconfig", str(folder / "absent-kubeconfig"), "--context", "offline", "--namespace", "argocd"],
                    text=True, capture_output=True, check=False, timeout=30,
                    env={"PATH": os.defpath, **({"HOME": os.environ["HOME"]} if "HOME" in os.environ else {})})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
