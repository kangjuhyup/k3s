"""Stage-three contracts: no cluster access or actual deployment."""
import yaml
import unittest

from test_argocd_gitops import manifest_files, ROOT, load


class IstioGitOpsTests(unittest.TestCase):
    def setUp(self):
        self.module = load("gitops_validate")


    def test_single_application_owns_all_components(self):
        files = manifest_files()
        app = files[self.module.ROOT_PATH + "/istio.yaml"]
        sources = app["spec"]["sources"]
        self.assertEqual([s["chart"] for s in sources if "chart" in s], ["base", "istiod", "gateway"])
        self.assertTrue(all(s["targetRevision"] == "1.30.4" for s in sources if "chart" in s))
        self.assertEqual(app["spec"]["destination"]["namespace"], "istio-system")
        self.assertEqual(app["spec"]["syncPolicy"]["automated"], {"enabled": True, "prune": False, "selfHeal": True, "allowEmpty": False})
        self.assertIn("istio.yaml", files[self.module.ROOT_PATH + "/kustomization.yaml"]["resources"])
        self.assertFalse(any(value.get("kind") == "Secret" for value in files.values()))
        project = files[self.module.ROOT_PATH + "/istio-project.yaml"]["spec"]
        self.assertNotIn({"group": "", "kind": "Secret"}, project["namespaceResourceWhitelist"])
        self.assertFalse(any(entry.get("kind") == "*" for entry in project["clusterResourceWhitelist"]))

    def test_owned_namespace_is_not_enrolled_in_mesh(self):
        files = manifest_files()
        ns = files["gitops/clusters/oci-a1/istio" + "/namespace.yaml"]
        self.assertEqual(ns["metadata"]["name"], "istio-system")
        self.assertNotIn("istio-injection", ns["metadata"].get("labels", {}))
        self.assertEqual(ns["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-20")

    def test_values_gate_control_plane_before_injected_gateway(self):
        base = ROOT / "gitops/platform/istio"
        pilot = yaml.safe_load((base / "istiod.values.yaml").read_text())
        gateway = yaml.safe_load((base / "gateway.values.yaml").read_text())
        self.assertEqual(pilot["deploymentAnnotations"]["argocd.argoproj.io/sync-wave"], "10")
        self.assertEqual(gateway["annotations"]["argocd.argoproj.io/sync-wave"], "20")
        self.assertEqual(pilot["base"]["validationFailurePolicy"], "Fail")
        self.assertIn("@sha256:", pilot["image"])
        self.assertIn("@sha256:", pilot["global"]["proxy"]["image"])
        self.assertEqual(pilot["global"]["proxy"]["image"], pilot["global"]["proxy_init"]["image"])
        self.assertFalse(pilot["sidecarInjectorWebhook"]["enableNamespacesByDefault"])
        self.assertFalse(pilot["cni"]["enabled"])
        self.assertEqual(gateway["service"]["type"], "ClusterIP")


if __name__ == "__main__":
    unittest.main()
