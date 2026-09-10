"""Official chart rendering and a synthetic local Git checkout, never deployment."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture, load


class BundleNativeTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get("HELM_TEST_BINARY") or not os.environ.get("ARGOCD_TEST_CHART"):
            self.skipTest("Explicit local Helm/chart not supplied; optional native check")
        self.helm = Path(os.environ["HELM_TEST_BINARY"]).resolve()
        self.chart = Path(os.environ["ARGOCD_TEST_CHART"]).resolve()
        self.module = load("argocd_bundle")

    def populate(self, root):
        config = fixture()
        files = self.module.gitops.render(config)
        files[self.module.gitops.SETTINGS_PATH] = config
        for path in [self.module.gitops.BASE_PATH, self.module.gitops.ACCOUNTS_PATH,
                     "gitops/platform/argocd/accounts.json", "gitops/platform/argocd/versions.json"]:
            files[path] = json.loads((ROOT / path).read_text())
        for path, value in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.module.gitops.encoded(value), encoding="utf-8")
        return config

    def git(self, root, *args):
        environment = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        result = subprocess.run(["git", *args], cwd=root, env=environment,
                                text=True, capture_output=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_full_official_chart_satisfies_bootstrap_and_project_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.populate(root)
            resources = self.module.render_chart(root, self.helm, self.chart, config)
            self.assertGreater(len(resources), 15)
            self.assertNotIn("Secret", {obj["kind"] for obj in resources})
            self.assertNotIn("Job", {obj["kind"] for obj in resources})
            files = self.module.gitops.render(config)
            project = files[self.module.gitops.ROOT_PATH + "/platform-project.json"]["spec"]
            for obj in resources:
                group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
                allowed = project["namespaceResourceWhitelist"] if obj["metadata"].get("namespace") else project["clusterResourceWhitelist"]
                self.assertIn({"group": group, "kind": obj["kind"]}, allowed)
            params = next(obj for obj in resources if obj["metadata"]["name"] == "argocd-cmd-params-cm")
            self.assertEqual(params["data"]["server.insecure"], "false")

    def test_bundle_requires_matching_committed_generated_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.populate(root)
            self.git(root, "-c", "init.templateDir=", "init", "--initial-branch=main")
            self.git(root, "add", "gitops")
            self.git(root, "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgSign=false", "commit", "-m", "Synthetic fixture")
            revision = self.git(root, "rev-parse", "HEAD")
            bundle = self.module.prepare(root, self.helm, self.chart, revision)
            self.assertEqual(bundle["expected_revision"], revision)
            self.assertTrue(bundle["initial_accounts"])
            with self.assertRaises(ValueError):
                self.module.prepare(root, self.helm, self.chart, "0" * 40)
            target = root / self.module.gitops.ENV_PATH
            target.write_text('{}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                self.module.prepare(root, self.helm, self.chart, revision)

    def test_wrong_chart_checksum_fails_before_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.populate(root)
            fake_chart = root / "wrong-chart.tgz"
            fake_chart.write_bytes(b"synthetic invalid archive")
            with self.assertRaises(ValueError):
                self.module.render_chart(root, self.helm, fake_chart, config)


if __name__ == "__main__":
    unittest.main()
