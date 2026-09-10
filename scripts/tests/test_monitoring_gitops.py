"""Monitoring must wait for secrets, remain private, and retain persistent data."""
import json
import os
import subprocess
import unittest
import yaml
from test_argocd_gitops import ROOT, fixture, load


class MonitoringTests(unittest.TestCase):
    def test_public_grafana_waits_for_tls_and_routes_only_its_host(self):
        m = load("monitoring_gitops")
        host = "grafana.example.invalid"
        files = m.render(fixture(), {"enabled": True, "credentials_ready_reviewed": True, "public_host": host})
        cert = files[m.PATH + "/grafana-certificate.json"]
        gateway = files[m.PATH + "/grafana-gateway.json"]
        self.assertEqual(cert["metadata"]["namespace"], "istio-system")
        self.assertEqual(cert["spec"]["dnsNames"], [host])
        self.assertEqual(gateway["spec"]["servers"][1]["tls"]["credentialName"], cert["spec"]["secretName"])
        self.assertLess(int(cert["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                        int(gateway["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
        route = files[m.PATH + "/grafana-route.json"]["spec"]
        self.assertEqual(route["hosts"], [host])
        self.assertEqual(route["http"][1]["route"][0]["destination"], {
            "host": "monitoring-grafana.monitoring.svc.cluster.local", "port": {"number": 80}})
        ini = files[m.PUBLIC_VALUES]["grafana"]["grafana.ini"]
        self.assertEqual(ini["server"]["root_url"], "https://" + host)
        self.assertTrue(ini["security"]["cookie_secure"])
        self.assertEqual(files[m.PATH + "/namespace.json"]["metadata"]["labels"]["istio-injection"], "disabled")
        self.assertFalse(any(o.get("kind") == "Secret" for o in files.values()))

    def test_public_grafana_rejects_invalid_domains_and_disabled_stack(self):
        m = load("monitoring_gitops")
        for host in ("*.example.invalid", "https://grafana.example.invalid", "", 123):
            with self.subTest(host=host), self.assertRaises(ValueError):
                m.render(fixture(), {"enabled": True, "credentials_ready_reviewed": True, "public_host": host})
        with self.assertRaises(ValueError):
            m.render(fixture(), {"enabled": False, "credentials_ready_reviewed": False, "public_host": "grafana.example.invalid"})

    def test_public_grafana_is_covered_by_shared_dns_issuer(self):
        files = load("argocd_gitops").render_repository(ROOT)
        cert = files["gitops/clusters/oci-a1/monitoring/grafana-certificate.json"]
        issuer = files["gitops/clusters/oci-a1/argocd-ingress/issuer.json"]
        self.assertEqual(cert["spec"]["issuerRef"]["name"], issuer["metadata"]["name"])
        self.assertIn(cert["spec"]["dnsNames"][0], issuer["spec"]["acme"]["solvers"][0]["selector"]["dnsNames"])

    def test_namespace_can_precede_secret_delivery_without_starting_consumers(self):
        m = load("monitoring_gitops")
        files = m.render(fixture(), {"enabled": False, "credentials_ready_reviewed": False})
        app = files[m.ROOT + "/monitoring.json"]
        self.assertEqual(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "25")
        self.assertNotIn("sources", app["spec"])
        self.assertEqual(files[m.PATH + "/kustomization.yaml"]["resources"], ["namespace.json"])

    def test_stack_cannot_start_before_reviewed_secret_delivery(self):
        m = load("monitoring_gitops")
        for config in [{"enabled": True, "credentials_ready_reviewed": False},
                       {"enabled": "true", "credentials_ready_reviewed": True}]:
            with self.assertRaises(ValueError):
                m.render(fixture(), config)

    def test_private_stack_uses_doppler_references_and_bounded_persistent_storage(self):
        m = load("monitoring_gitops")
        v = json.loads((ROOT / m.VALUES).read_text())
        self.assertEqual(v["grafana"]["admin"]["existingSecret"], "grafana-admin")
        self.assertNotIn("adminPassword", v["grafana"])
        self.assertTrue(v["grafana"]["rbac"]["namespaced"])
        slack = v["alertmanager"]["config"]["receivers"][1]["slack_configs"][0]
        self.assertIn("api_url_file", slack)
        self.assertNotIn("api_url", slack)
        p = v["prometheus"]["prometheusSpec"]
        self.assertEqual(p["retention"], "7d")
        self.assertEqual(p["retentionSize"], "8GB")
        self.assertEqual(p["storageSpec"]["volumeClaimTemplate"]["spec"]["resources"]["requests"]["storage"], "10Gi")
        self.assertEqual(p["persistentVolumeClaimRetentionPolicy"]["whenDeleted"], "Retain")
        self.assertFalse(v["kubelet"]["serviceMonitor"]["tlsConfig"]["insecureSkipVerify"])

    def test_redis_scrapes_use_mtls_and_only_probe_credentials(self):
        m = load("monitoring_gitops")
        files = m.render(fixture(), {"enabled": True, "credentials_ready_reviewed": True})
        for role in ["master", "replica"]:
            pod = files[m.PATH + "/redis-metrics-" + role + ".json"]["spec"]["template"]["spec"]
            container = pod["containers"][0]
            env = {e["name"]: e for e in container["env"]}
            self.assertTrue(env["REDIS_ADDR"]["value"].startswith("rediss://"))
            self.assertIn("REDIS_EXPORTER_TLS_CLIENT_KEY_FILE", env)
            self.assertNotIn("REDIS_EXPORTER_SKIP_TLS_VERIFICATION", env)
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(container["resources"]["limits"]["memory"], "64Mi")
        mappings = json.loads((ROOT / "gitops/clusters/oci-a1/doppler.json").read_text())["mappings"]
        keys = next(x["keys"] for x in mappings if x["name"] == "monitoring-redis")
        self.assertIn("REDIS_PROBE_PASSWORD", keys)
        self.assertNotIn("REDIS_ADMIN_PASSWORD", keys)
        self.assertNotIn("REDIS_TLS_CA_KEY", keys)

    @unittest.skipUnless(os.environ.get("MONITORING_TEST_CHART") and os.environ.get("HELM_TEST_BINARY"), "Pinned monitoring chart required")
    def test_chart_resources_fit_project_and_services_are_internal(self):
        m = load("monitoring_gitops")
        p = subprocess.run([os.environ["HELM_TEST_BINARY"], "template", "monitoring", os.environ["MONITORING_TEST_CHART"],
                            "--namespace", "monitoring", "--kube-version", "1.36.4", "--include-crds", "--skip-tests",
                            "-f", str(ROOT / m.VALUES), "-f", str(ROOT / m.PUBLIC_VALUES)], capture_output=True, text=True, check=True)
        class Loader(yaml.SafeLoader):
            pass
        Loader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))
        docs = [d for d in yaml.load_all(p.stdout, Loader=Loader) if d]
        grafana_config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "monitoring-grafana")
        public_host = json.loads((ROOT / m.SETTINGS).read_text())["public_host"]
        self.assertIn("root_url = https://" + public_host, grafana_config["data"]["grafana.ini"])
        self.assertIn("cookie_secure = true", grafana_config["data"]["grafana.ini"])
        self.assertIn("[auth.anonymous]\nenabled = false", grafana_config["data"]["grafana.ini"])
        project = m.render(fixture(), {"enabled": True, "credentials_ready_reviewed": True})[m.ROOT + "/monitoring-project.json"]["spec"]
        allowed = {(r["group"], r["kind"]) for key in ("clusterResourceWhitelist", "namespaceResourceWhitelist") for r in project[key]}
        for d in docs:
            group = d["apiVersion"].split("/")[0] if "/" in d["apiVersion"] else ""
            self.assertIn((group, d["kind"]), allowed)
            if d["kind"] == "Service":
                self.assertEqual(d["spec"].get("type", "ClusterIP"), "ClusterIP")
        self.assertFalse(any(d["kind"] == "Secret" and d["metadata"]["name"] in {"grafana-admin", "alertmanager-slack"} for d in docs))
        self.assertFalse(any(d["kind"] in {"ClusterRole", "ClusterRoleBinding"} and d["metadata"]["name"].startswith("monitoring-grafana") for d in docs))
