"""CNPG foundation is operator-only and cannot silently abandon ownership."""
import hashlib
import os
from pathlib import Path
import subprocess
import unittest

import yaml
from test_argocd_gitops import manifest_files, layout, ROOT


class CNPGTests(unittest.TestCase):
    def test_operator_does_not_create_databases_or_credentials(self):
        module = layout("cnpg")
        files = manifest_files("cnpg")
        self.assertEqual({x["kind"] for x in files.values()},
                         {"Application", "AppProject", "Namespace", "Kustomization"})
        app = files[module.ROOT + "/cnpg.yaml"]["spec"]
        self.assertEqual(app["sources"][0]["targetRevision"], "0.29.0")
        self.assertFalse(app["syncPolicy"]["automated"]["prune"])
        project = files[module.ROOT + "/cnpg-project.yaml"]["spec"]
        self.assertNotIn("Secret", [r["kind"] for r in project["namespaceResourceWhitelist"]])


    @unittest.skipUnless(os.environ.get("CNPG_TEST_CHART") and os.environ.get("HELM_TEST_BINARY"),
                         "Pinned CNPG chart and Helm required")
    def test_official_chart_renders_only_permitted_operator_resources(self):
        chart = Path(os.environ["CNPG_TEST_CHART"])
        self.assertEqual(hashlib.sha256(chart.read_bytes()).hexdigest(),
                         "668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f")
        module = layout("cnpg")
        rendered = subprocess.check_output([os.environ["HELM_TEST_BINARY"], "template", "cnpg", str(chart),
                    "--namespace", module.NAMESPACE, "--kube-version", "1.36.4", "--include-crds",
                    "-f", str(ROOT / module.VALUES)], text=True)
        docs = [d for d in yaml.safe_load_all(rendered) if d]
        project = manifest_files()[module.ROOT + "/cnpg-project.yaml"]["spec"]
        allowed = {(r["group"], r["kind"]) for key in ("namespaceResourceWhitelist", "clusterResourceWhitelist") for r in project[key]}
        for doc in docs:
            group = doc["apiVersion"].split("/")[0] if "/" in doc["apiVersion"] else ""
            self.assertIn((group, doc["kind"]), allowed)
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        spec = deployment["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeSelector"]["kubernetes.io/arch"], "arm64")
        self.assertIn("@sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb", spec["containers"][0]["image"])
