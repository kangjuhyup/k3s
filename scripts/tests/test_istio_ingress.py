"""External TLS routing and scoped mesh security, without remote access."""
import unittest

from test_argocd_gitops import manifest_files, load


class IstioIngressTests(unittest.TestCase):
    def setUp(self):
        self.module = load("gitops_validate")

    def manifests(self):
        return manifest_files()


    def test_only_80_and_443_are_exposed_without_nodeports(self):
        files = self.manifests()
        values = files[self.module.INGRESS_VALUES_PATH]
        self.assertEqual(values["service"]["type"], "LoadBalancer")
        self.assertFalse(values["service"]["allocateLoadBalancerNodePorts"])
        self.assertEqual([p["port"] for p in values["service"]["ports"]], [80, 443])
        self.assertEqual(values["service"]["externalTrafficPolicy"], "Cluster")
        app = files[self.module.ROOT_PATH + "/istio.yaml"]["spec"]
        self.assertIn("$values/" + self.module.INGRESS_VALUES_PATH, app["sources"][2]["helm"]["valueFiles"])


if __name__ == "__main__":
    unittest.main()
