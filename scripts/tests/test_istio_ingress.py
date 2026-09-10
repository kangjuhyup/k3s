"""External TLS routing and scoped mesh security, without remote access."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_argocd_gitops import ROOT, fixture, load
from test_istio_gitops import istio_fixture
from test_k3s_config import fixture as k3s_fixture


def ingress_fixture():
    return {"enabled": True, "reviewed": True, "exposure": "k3s-servicelb",
            "network_reviewed": True, "tls_ready_reviewed": True,
            "mesh_namespaces": ["test-apps"],
            "routes": [{"name": "test-web", "host": "web.example.invalid", "tls_secret": "test-web-tls",
                        "backend_namespace": "test-apps", "backend_service": "web",
                        "backend_port": 8080, "path_prefix": "/"}]}


class IstioIngressTests(unittest.TestCase):
    def setUp(self):
        self.module = load("argocd_gitops")

    def render(self, ingress=None):
        return self.module.render(fixture(), istio_fixture(), ingress or ingress_fixture())

    def test_disabled_input_leaves_baseline_private(self):
        disabled = self.module.read_json(ROOT / self.module.INGRESS_SETTINGS_PATH)
        self.assertEqual(self.module.render(fixture(), istio_fixture(), disabled),
                         self.module.render(fixture(), istio_fixture()))

    def test_missing_reviews_and_bad_input_are_rejected(self):
        for change in [{"reviewed": False}, {"network_reviewed": False}, {"tls_ready_reviewed": False},
                       {"exposure": "oci-lb"}, {"mesh_namespaces": ["argocd"]},
                       {"mesh_namespaces": ["kube-system"]}, {"routes": []}, {"secret_value": "DO_NOT_ECHO"}]:
            value = ingress_fixture()
            value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.render(value)
        for key, bad in [("host", "*.example.invalid"), ("host", "https://example.invalid"),
                         ("tls_secret", "../secret"), ("backend_namespace", "default"),
                         ("backend_port", True), ("backend_port", 0), ("path_prefix", "/x?token=y")]:
            value = ingress_fixture()
            value["routes"][0][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.render(value)
        value = ingress_fixture()
        value["routes"].append(copy.deepcopy(value["routes"][0]))
        with self.assertRaises(ValueError):
            self.render(value)
        with self.assertRaises(ValueError):
            self.module.render(fixture(), None, ingress_fixture())

    def test_https_redirect_exact_host_and_secret_reference(self):
        files = self.render()
        gateway = next(o for o in files.values() if o.get("kind") == "Gateway")
        servers = gateway["spec"]["servers"]
        self.assertEqual(servers[0]["tls"], {"httpsRedirect": True})
        self.assertEqual(servers[1]["tls"], {"mode": "SIMPLE", "credentialName": "test-web-tls", "minProtocolVersion": "TLSV1_2"})
        self.assertEqual(servers[1]["hosts"], ["./web.example.invalid"])
        route = next(o for o in files.values() if o.get("kind") == "VirtualService")
        self.assertEqual(route["spec"]["hosts"], ["web.example.invalid"])
        self.assertEqual(route["spec"]["http"][0], {"match": [{"port": 80}], "redirect": {"scheme": "https", "port": 443}})
        self.assertEqual(route["spec"]["http"][1]["route"][0]["destination"],
                         {"host": "web.test-apps.svc.cluster.local", "port": {"number": 8080}})
        self.assertEqual(route["spec"]["gateways"], ["external-test-web"])
        self.assertFalse(any(o.get("kind") == "Secret" for o in files.values()))

    def test_strict_mtls_and_namespace_enrollment_are_scoped(self):
        files = self.render()
        policy = next(o for o in files.values() if o.get("kind") == "PeerAuthentication")
        self.assertEqual(policy["metadata"]["namespace"], "test-apps")
        self.assertEqual(policy["spec"], {"mtls": {"mode": "STRICT"}})
        namespace = next(o for o in files.values() if o.get("kind") == "Namespace" and o["metadata"]["name"] == "test-apps")
        self.assertEqual(namespace["metadata"]["labels"]["istio-injection"], "enabled")
        outbound = next(o for o in files.values() if o.get("kind") == "DestinationRule")
        self.assertEqual(outbound["spec"]["trafficPolicy"]["tls"]["mode"], "ISTIO_MUTUAL")
        self.assertEqual(outbound["spec"]["workloadSelector"], {"matchLabels": {"app": "istio-ingress"}})
        project = files[self.module.ROOT_PATH + "/istio-project.json"]["spec"]
        self.assertEqual({d["namespace"] for d in project["destinations"]}, {"istio-system", "test-apps"})
        self.assertNotIn({"group": "", "kind": "Secret"}, project["namespaceResourceWhitelist"])

    def test_only_80_and_443_are_exposed_without_nodeports(self):
        files = self.render()
        values = files[self.module.INGRESS_VALUES_PATH]
        self.assertEqual(values["service"]["type"], "LoadBalancer")
        self.assertFalse(values["service"]["allocateLoadBalancerNodePorts"])
        self.assertEqual([p["port"] for p in values["service"]["ports"]], [80, 443])
        self.assertEqual(values["service"]["externalTrafficPolicy"], "Cluster")
        app = files[self.module.ROOT_PATH + "/istio.json"]["spec"]
        self.assertIn("$values/" + self.module.INGRESS_VALUES_PATH, app["sources"][2]["helm"]["valueFiles"])

    def test_repository_checks_servicelb_version_and_removed_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(path, obj):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(obj))
            config = k3s_fixture()
            config["servicelb"] = True
            write(self.module.SETTINGS_PATH, fixture())
            write(self.module.ISTIO_SETTINGS_PATH, istio_fixture())
            write(self.module.INGRESS_SETTINGS_PATH, ingress_fixture())
            write(self.module.K3S_SETTINGS_PATH, config)
            self.assertTrue(self.module.render_repository(root))
            for change in [{"servicelb": False}, {"network_reviewed": False}, {"version": "v1.35.2+k3s1"}]:
                other = copy.deepcopy(config)
                other.update(change)
                write(self.module.K3S_SETTINGS_PATH, other)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.module.render_repository(root)
            write(self.module.K3S_SETTINGS_PATH, config)
            args = [sys.executable, str(ROOT / "scripts/argocd_gitops.py"), "--repo-root", str(root), "--write"]
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
            disabled = ingress_fixture()
            disabled["enabled"] = False
            write(self.module.INGRESS_SETTINGS_PATH, disabled)
            with self.assertRaises(ValueError):
                self.module.render_repository(root)
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
