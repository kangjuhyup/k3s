"""Monitoring must wait for secrets, remain private, and retain persistent data."""
import os
import subprocess
import unittest
import yaml
from test_argocd_gitops import manifest_files, layout, ROOT


class MonitoringTests(unittest.TestCase):
    def test_public_grafana_waits_for_tls_and_routes_only_its_host(self):
        m = layout("monitoring")
        host = "grafana.rvkang.app"
        files = manifest_files()
        cert = files[m.PATH + "/grafana-certificate.yaml"]
        gateway = files[m.PATH + "/grafana-gateway.yaml"]
        self.assertEqual(cert["metadata"]["namespace"], "istio-system")
        self.assertEqual(cert["spec"]["dnsNames"], [host])
        self.assertEqual(gateway["spec"]["servers"][1]["tls"]["credentialName"], cert["spec"]["secretName"])
        self.assertLess(int(cert["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                        int(gateway["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
        route = files[m.PATH + "/grafana-route.yaml"]["spec"]
        self.assertEqual(route["hosts"], [host])
        self.assertEqual(route["http"][1]["route"][0]["destination"], {
            "host": "monitoring-grafana.monitoring.svc.cluster.local", "port": {"number": 80}})
        ini = files[m.PUBLIC_VALUES]["grafana"]["grafana.ini"]
        self.assertEqual(ini["server"]["root_url"], "https://" + host)
        self.assertTrue(ini["security"]["cookie_secure"])
        self.assertEqual(files[m.PATH + "/namespace.yaml"]["metadata"]["labels"]["istio-injection"], "disabled")
        self.assertFalse(any(o.get("kind") == "Secret" for o in files.values()))


    def test_public_grafana_is_covered_by_shared_dns_issuer(self):
        files = manifest_files()
        cert = files["gitops/clusters/oci-a1/monitoring/grafana-certificate.yaml"]
        issuer = files["gitops/clusters/oci-a1/argocd-ingress/issuer.yaml"]
        self.assertEqual(cert["spec"]["issuerRef"]["name"], issuer["metadata"]["name"])
        self.assertIn(cert["spec"]["dnsNames"][0], issuer["spec"]["acme"]["solvers"][0]["selector"]["dnsNames"])


    def test_private_stack_uses_doppler_references_and_bounded_persistent_storage(self):
        m = layout("monitoring")
        v = yaml.safe_load((ROOT / m.VALUES).read_text())
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
        m = layout("monitoring")
        files = manifest_files()
        for role in ["master", "replica"]:
            pod = files[m.PATH + "/redis-metrics-" + role + ".yaml"]["spec"]["template"]["spec"]
            container = pod["containers"][0]
            env = {e["name"]: e for e in container["env"]}
            self.assertTrue(env["REDIS_ADDR"]["value"].startswith("rediss://"))
            self.assertIn("REDIS_EXPORTER_TLS_CLIENT_KEY_FILE", env)
            self.assertNotIn("REDIS_EXPORTER_SKIP_TLS_VERIFICATION", env)
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(container["resources"]["limits"]["memory"], "64Mi")
        mappings = yaml.safe_load((ROOT / "gitops/clusters/oci-a1/doppler.json").read_text())["mappings"]
        keys = next(x["keys"] for x in mappings if x["name"] == "monitoring-redis")
        self.assertIn("REDIS_PROBE_PASSWORD", keys)
        self.assertNotIn("REDIS_ADMIN_PASSWORD", keys)
        self.assertNotIn("REDIS_TLS_CA_KEY", keys)

    @unittest.skipUnless(os.environ.get("MONITORING_TEST_CHART") and os.environ.get("HELM_TEST_BINARY"), "Pinned monitoring chart required")
    def test_chart_resources_fit_project_and_services_are_internal(self):
        m = layout("monitoring")
        p = subprocess.run([os.environ["HELM_TEST_BINARY"], "template", "monitoring", os.environ["MONITORING_TEST_CHART"],
                            "--namespace", "monitoring", "--kube-version", "1.36.4", "--include-crds", "--skip-tests",
                            "-f", str(ROOT / m.VALUES), "-f", str(ROOT / m.PUBLIC_VALUES)], capture_output=True, text=True, check=True)
        class Loader(yaml.SafeLoader):
            pass
        Loader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))
        docs = [d for d in yaml.load_all(p.stdout, Loader=Loader) if d]
        grafana_config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "monitoring-grafana")
        public_host = "grafana.rvkang.app"
        self.assertIn("root_url = https://" + public_host, grafana_config["data"]["grafana.ini"])
        self.assertIn("cookie_secure = true", grafana_config["data"]["grafana.ini"])
        self.assertIn("[auth.anonymous]\nenabled = false", grafana_config["data"]["grafana.ini"])
        project = manifest_files()[m.ROOT + "/monitoring-project.yaml"]["spec"]
        allowed = {(r["group"], r["kind"]) for key in ("clusterResourceWhitelist", "namespaceResourceWhitelist") for r in project[key]}
        for d in docs:
            group = d["apiVersion"].split("/")[0] if "/" in d["apiVersion"] else ""
            self.assertIn((group, d["kind"]), allowed)
            if d["kind"] == "Service":
                self.assertEqual(d["spec"].get("type", "ClusterIP"), "ClusterIP")
        self.assertFalse(any(d["kind"] == "Secret" and d["metadata"]["name"] in {"grafana-admin", "alertmanager-slack"} for d in docs))
        self.assertFalse(any(d["kind"] in {"ClusterRole", "ClusterRoleBinding"} and d["metadata"]["name"].startswith("monitoring-grafana") for d in docs))
