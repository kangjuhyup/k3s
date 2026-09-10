"""Stage-three contracts: no cluster access or actual deployment."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture, load


def istio_fixture():
    return {"enabled": True, "reviewed": True, "mode": "sidecar",
            "namespace": "istio-system", "gateway_service_type": "ClusterIP"}


class IstioGitOpsTests(unittest.TestCase):
    def setUp(self):
        self.module = load("argocd_gitops")

    def test_disabled_input_does_not_activate_istio(self):
        config = dict(istio_fixture(), enabled=False, reviewed=False)
        files = self.module.render(fixture(), config)
        self.assertFalse(any("istio" in path for path in files))

    def test_unreviewed_unsupported_or_unknown_inputs_fail_closed(self):
        for change in [{"reviewed": False}, {"mode": "ambient"}, {"namespace": "kube-system"},
                       {"gateway_service_type": "LoadBalancer"}, {"enabled": "true"},
                       {"unexpected_secret": "DO_NOT_ECHO"}]:
            config = istio_fixture()
            config.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.render(fixture(), config)
        for kube in ["1.31.9", "1.37.0"]:
            config = fixture()
            config["kube_version"] = kube
            with self.assertRaises(ValueError):
                self.module.render(config, istio_fixture())

    def test_single_application_owns_all_components(self):
        files = self.module.render(fixture(), istio_fixture())
        app = files[self.module.ROOT_PATH + "/istio.json"]
        sources = app["spec"]["sources"]
        self.assertEqual([s["chart"] for s in sources if "chart" in s], ["base", "istiod", "gateway"])
        self.assertTrue(all(s["targetRevision"] == "1.30.4" for s in sources if "chart" in s))
        self.assertEqual(app["spec"]["destination"]["namespace"], "istio-system")
        self.assertEqual(app["spec"]["syncPolicy"]["automated"], self.module.sync_policy()["automated"])
        self.assertIn("istio.json", files[self.module.ROOT_PATH + "/kustomization.yaml"]["resources"])
        self.assertFalse(any(value.get("kind") == "Secret" for value in files.values()))
        project = files[self.module.ROOT_PATH + "/istio-project.json"]["spec"]
        self.assertNotIn({"group": "", "kind": "Secret"}, project["namespaceResourceWhitelist"])
        self.assertFalse(any(entry.get("kind") == "*" for entry in project["clusterResourceWhitelist"]))

    def test_owned_namespace_is_not_enrolled_in_mesh(self):
        files = self.module.render(fixture(), istio_fixture())
        ns = files[self.module.ISTIO_MANIFEST_PATH + "/namespace.json"]
        self.assertEqual(ns["metadata"]["name"], "istio-system")
        self.assertNotIn("istio-injection", ns["metadata"].get("labels", {}))
        self.assertEqual(ns["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-20")

    def test_values_gate_control_plane_before_injected_gateway(self):
        base = ROOT / "gitops/platform/istio"
        pilot = json.loads((base / "istiod.values.json").read_text())
        gateway = json.loads((base / "gateway.values.json").read_text())
        self.assertEqual(pilot["deploymentAnnotations"]["argocd.argoproj.io/sync-wave"], "10")
        self.assertEqual(gateway["annotations"]["argocd.argoproj.io/sync-wave"], "20")
        self.assertEqual(pilot["base"]["validationFailurePolicy"], "Fail")
        self.assertIn("@sha256:", pilot["image"])
        self.assertIn("@sha256:", pilot["global"]["proxy"]["image"])
        self.assertEqual(pilot["global"]["proxy"]["image"], pilot["global"]["proxy_init"]["image"])
        self.assertFalse(pilot["sidecarInjectorWebhook"]["enableNamespacesByDefault"])
        self.assertFalse(pilot["cni"]["enabled"])
        self.assertEqual(gateway["service"]["type"], "ClusterIP")

    def test_cli_connects_istio_and_blocks_silent_disablement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / self.module.SETTINGS_PATH
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(fixture()))
            istio = root / self.module.ISTIO_SETTINGS_PATH
            istio.write_text(json.dumps(istio_fixture()))
            args = [sys.executable, str(ROOT / "scripts/argocd_gitops.py"), "--repo-root", str(root)]
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
            self.assertFalse((root / self.module.ROOT_PATH).exists())
            self.assertEqual(subprocess.run(args + ["--write"], capture_output=True).returncode, 0)
            self.assertTrue(self.module.check_files(root, self.module.render(fixture(), istio_fixture())))
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
            snapshot = {p: p.read_bytes() for p in (root / self.module.ROOT_PATH).iterdir()}
            disabled = istio_fixture()
            disabled["enabled"] = False
            istio.write_text(json.dumps(disabled))
            result = subprocess.run(args + ["--write"], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(all(p.read_bytes() == raw for p, raw in snapshot.items()))


if __name__ == "__main__":
    unittest.main()
