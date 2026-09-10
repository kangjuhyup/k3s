"""Pinned upstream Helm and Argo CD health execution; no API/network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture as bootstrap, load
from test_doppler_gitops import fixture


class DopplerNativeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HELM_TEST_BINARY") and os.environ.get("DOPPLER_TEST_CHART"), "local Helm/chart not supplied")
    def test_upstream_render_crd_and_project(self):
        import yaml
        result = subprocess.run([os.environ["HELM_TEST_BINARY"], "template", "doppler", os.environ["DOPPLER_TEST_CHART"],
                                 "--namespace", "doppler-operator-system", "--include-crds", "--kube-version", "1.35.1"],
                                text=True, capture_output=True, timeout=30, check=False, env={"PATH": os.defpath})
        self.assertEqual(result.returncode, 0, result.stderr)
        official = [o for o in yaml.safe_load_all(result.stdout) if o]
        self.assertEqual(len(official), 9)
        vendor = load("doppler_vendor").render(Path(os.environ["DOPPLER_TEST_CHART"]))
        rendered = load("doppler_gitops").render(bootstrap(), fixture())
        project = next(o["spec"] for o in rendered.values() if o.get("kind") == "AppProject")
        crd = next(o for o in official if o["kind"] == "CustomResourceDefinition")
        schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]

        def check(value, shape):
            for required in shape.get("required", []):
                self.assertIn(required, value)
            if isinstance(value, dict):
                for key, item in value.items():
                    child = shape.get("properties", {}).get(key, shape.get("additionalProperties"))
                    self.assertIsInstance(child, dict, key)
                    check(item, child)
            elif isinstance(value, list):
                for item in value:
                    check(item, shape["items"])
            elif "enum" in shape:
                self.assertIn(value, shape["enum"])

        for obj in list(vendor.values()) + list(rendered.values()):
            if obj.get("kind") in {"Kustomization", "Application", "AppProject"}:
                continue
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            scope = "namespace" if obj["metadata"].get("namespace") else "cluster"
            self.assertIn({"group": group, "kind": obj["kind"]}, project[scope + "ResourceWhitelist"])
            if obj["kind"] == "DopplerSecret":
                check(obj["spec"], schema)

    @unittest.skipUnless(os.environ.get("ARGOCD_TEST_BINARY"), "local Argo CD CLI not supplied")
    def test_real_lua_does_not_echo_operator_error_messages(self):
        key = "resource.customizations.health.secrets.doppler.com_DopplerSecret"
        script = json.loads((ROOT / "gitops/platform/argocd/base.values.json").read_text())["configs"]["cm"][key]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cm, secret, resource = [folder / (name + ".json") for name in ["cm", "secret", "resource"]]
            cm.write_text(json.dumps({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "argocd-cm"}, "data": {key: script}}))
            secret.write_text(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "argocd-secret"}}))
            for status, expected in [(None, "Progressing"), ("True", "Healthy"), ("False", "Degraded")]:
                obj = {"apiVersion": "secrets.doppler.com/v1alpha1", "kind": "DopplerSecret", "metadata": {"name": "test"}}
                if status:
                    obj["status"] = {"conditions": [{"type": "secrets.doppler.com/SecretSyncReady", "status": status,
                                                    "message": "SYNTHETIC_DO_NOT_ECHO"}]}
                resource.write_text(json.dumps(obj))
                result = subprocess.run([os.environ["ARGOCD_TEST_BINARY"], "admin", "settings", "resource-overrides", "health", str(resource),
                    "--argocd-cm-path", str(cm), "--argocd-secret-path", str(secret), "--config", str(folder / "absent-config"),
                    "--kubeconfig", str(folder / "absent-kubeconfig"), "--context", "offline", "--namespace", "argocd"],
                    text=True, capture_output=True, check=False, timeout=30,
                    env={"PATH": os.defpath, **({"HOME": os.environ["HOME"]} if "HOME" in os.environ else {})})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("SYNTHETIC_DO_NOT_ECHO", result.stdout + result.stderr)
