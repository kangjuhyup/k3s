"""CNPG foundation is operator-only and cannot silently abandon ownership."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from test_argocd_gitops import ROOT, fixture, load


class CNPGTests(unittest.TestCase):
    def test_operator_does_not_create_databases_or_credentials(self):
        module = load("cnpg_gitops")
        files = module.render(fixture(), {"enabled": True, "reviewed": True})
        self.assertEqual({x["kind"] for x in files.values()},
                         {"Application", "AppProject", "Namespace", "Kustomization"})
        app = files[module.ROOT + "/cnpg.json"]["spec"]
        self.assertEqual(app["sources"][0]["targetRevision"], "0.29.0")
        self.assertFalse(app["syncPolicy"]["automated"]["prune"])
        project = files[module.ROOT + "/cnpg-project.json"]["spec"]
        self.assertNotIn("Secret", [r["kind"] for r in project["namespaceResourceWhitelist"]])

    def test_unsupported_or_unreviewed_install_is_rejected(self):
        module = load("cnpg_gitops")
        for version, reviewed in [("1.33.9", True), ("1.37.0", True), ("1.36.4", False)]:
            bootstrap = fixture()
            bootstrap["kube_version"] = version
            with self.assertRaises(ValueError):
                module.render(bootstrap, {"enabled": True, "reviewed": reviewed})
        self.assertEqual(module.render(fixture(), {"enabled": False, "reviewed": False}), {})

    def test_installed_operator_cannot_be_silently_disabled(self):
        module = load("argocd_gitops")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in [(module.SETTINGS_PATH, fixture()),
                                (module.ROOT_PATH + "/cnpg.json", {}),
                                ("gitops/clusters/oci-a1/cnpg.json", {"enabled": False, "reviewed": False})]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                module.render_repository(root)

    @unittest.skipUnless(os.environ.get("CNPG_TEST_CHART") and os.environ.get("HELM_TEST_BINARY"),
                         "Pinned CNPG chart and Helm required")
    def test_official_chart_renders_only_permitted_operator_resources(self):
        chart = Path(os.environ["CNPG_TEST_CHART"])
        self.assertEqual(hashlib.sha256(chart.read_bytes()).hexdigest(),
                         "668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f")
        module = load("cnpg_gitops")
        rendered = subprocess.check_output([os.environ["HELM_TEST_BINARY"], "template", "cnpg", str(chart),
                    "--namespace", module.NAMESPACE, "--kube-version", "1.36.4", "--include-crds",
                    "-f", str(ROOT / module.VALUES)], text=True)
        docs = [d for d in yaml.safe_load_all(rendered) if d]
        project = module.render(fixture(), {"enabled": True, "reviewed": True})[module.ROOT + "/cnpg-project.json"]["spec"]
        allowed = {(r["group"], r["kind"]) for key in ("namespaceResourceWhitelist", "clusterResourceWhitelist") for r in project[key]}
        for doc in docs:
            group = doc["apiVersion"].split("/")[0] if "/" in doc["apiVersion"] else ""
            self.assertIn((group, doc["kind"]), allowed)
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        spec = deployment["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeSelector"]["kubernetes.io/arch"], "arm64")
        self.assertIn("@sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb", spec["containers"][0]["image"])
