"""Approved auth deployment preserves TLS and migration/scaling boundaries."""
import unittest
from test_argocd_gitops import ROOT, load, manifest_files, layout


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.m = layout("auth")
        self.config = {"public_host": "auth.rvkang.app"}
        self.files = manifest_files("auth")
        self.effective = load("gitops_validate").resources_at(ROOT, ROOT / self.m.PATH)

    def resource(self, name):
        path = self.m.PATH + "/" + name + ".yaml"
        original = self.files.get(path) or manifest_files()["gitops/apps/auth/" + name + ".yaml"]
        return next(o for o in self.effective if o["kind"] == original["kind"]
                    and o["metadata"]["name"] == original["metadata"]["name"])

    def test_app_base_is_reusable_and_environment_supplies_resources_and_domain(self):
        base = manifest_files()["gitops/apps/auth/auth-service.yaml"]
        container = base["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("resources", container)
        self.assertFalse(any(e["name"] in ("ADMIN_UI_URL", "OIDC_ISSUER") for e in container["env"]))
        effective = self.resource("auth-service")["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(effective["resources"]["requests"]["cpu"], "100m")
        self.assertEqual(next(e["value"] for e in effective["env"] if e["name"] == "OIDC_ISSUER"), "https://auth.rvkang.app")

    def test_approved_runtime_uses_the_full_environment_overlay(self):
        app = self.files[self.m.ROOT + "/auth.yaml"]["spec"]
        self.assertEqual(app["source"]["path"], self.m.PATH)
        self.assertEqual(self.files[self.m.PATH + "/bootstrap/kustomization.yaml"]["resources"], ["namespace.yaml"])


    def test_hpa_owns_replicas_with_bounded_cpu_scaling(self):
        hpa = self.resource("hpa")["spec"]
        self.assertEqual((hpa["minReplicas"], hpa["maxReplicas"]), (1, 3))
        self.assertEqual(hpa["metrics"][0]["resource"]["name"], "cpu")
        self.assertNotIn("replicas", self.resource("auth-service")["spec"])
        app = self.files[self.m.ROOT + "/auth.yaml"]["spec"]
        self.assertIn("/spec/replicas", app["ignoreDifferences"][0]["jsonPointers"])
        self.assertIn("RespectIgnoreDifferences=true", app["syncPolicy"]["syncOptions"])

    def test_only_single_migration_job_receives_bootstrap_credentials(self):
        job = self.resource("migration")
        self.assertEqual(job["spec"]["template"]["spec"]["containers"][0]["command"], ["node", "dist/cli/migrate.js"])
        self.assertLess(int(job["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]), 0)
        for name, command in (("auth-service", "dist/main.js"), ("auth-worker", "dist/worker.js")):
            pod = self.resource(name)["spec"]["template"]["spec"]
            c = pod["containers"][0]
            self.assertEqual(c["command"], ["node", command])
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertFalse(any(e["name"].startswith("ADMIN_") and "valueFrom" in e for e in c["env"]))
        worker_env = self.resource("auth-worker")["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertFalse(any(e["name"].startswith("REDIS_") for e in worker_env))

    def test_secret_values_are_operator_owned_and_tls_is_verified(self):
        self.assertFalse(any(o.get("kind") == "Secret" for o in self.files.values()))
        sync = self.resource("auth-runtime-sync")["spec"]
        self.assertTrue(sync["verifyTLS"])
        self.assertIn("REDIS_TLS_KEY", sync["secrets"])
        self.assertIn("REDIS_KEY_PREFIX", sync["secrets"])
        self.assertNotIn("REDIS_ADMIN_PASSWORD", sync["secrets"])
        self.assertEqual(sync["tokenSecret"]["name"], "doppler-auth-auth-prd")

    def test_database_clients_require_tls_with_a_private_ca_mount(self):
        for name in ("auth-service", "auth-worker", "migration"):
            pod = self.resource(name)["spec"]["template"]["spec"]
            c = pod["containers"][0]
            env = {e["name"]: e for e in c["env"]}
            self.assertEqual(env["PGSSLMODE"]["valueFrom"]["secretKeyRef"]["key"], "DB_SSLMODE")
            self.assertEqual(env["NODE_EXTRA_CA_CERTS"]["value"], "/var/run/auth-db-ca/ca.crt")
            ca = next(v for v in pod["volumes"] if v["name"] == "db-ca")
            self.assertEqual(ca["secret"]["items"], [{"key": "DB_TLS_CA_CERT", "path": "ca.crt"}])
            self.assertTrue(next(v for v in c["volumeMounts"] if v["name"] == "db-ca")["readOnly"])

    def test_login_and_password_reset_have_required_runtime_ttls(self):
        c = self.resource("auth-service")["spec"]["template"]["spec"]["containers"][0]
        values = {e["name"]: e.get("value") for e in c["env"]}
        for name, value in {"OIDC_CACHE_TTL_MARGIN_SEC": "5", "OIDC_CACHE_NEGATIVE_TTL_SEC": "3",
                            "OIDC_CACHE_BACKFILL_TTL_SEC": "60", "OTP_PASSWORD_RESET_TTL_SEC": "900"}.items():
            self.assertEqual(values[name], value)

    def test_ui_runs_unprivileged_and_public_paths_preserve_oidc(self):
        pod = self.resource("auth-ui")["spec"]["template"]["spec"]
        self.assertEqual(pod["securityContext"]["runAsUser"], 101)
        c = pod["containers"][0]
        self.assertEqual(c["ports"][0]["containerPort"], 8080)
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        routes = self.resource("route")["spec"]["http"]
        self.assertEqual(routes[0]["redirect"]["scheme"], "https")
        self.assertIn("/t/", [m["uri"]["prefix"] for m in routes[1]["match"]])
        self.assertNotIn("rewrite", routes[1])
        self.assertEqual(routes[1]["headers"]["response"]["set"]["cache-control"], "no-store")
        self.assertEqual(routes[-1]["route"][0]["destination"]["host"], "auth-ui.auth.svc.cluster.local")

    def test_every_declared_resource_fits_project_permissions(self):
        p = self.files[self.m.ROOT + "/auth-project.yaml"]["spec"]
        allowed = {(a["group"], a["kind"]) for field in ("clusterResourceWhitelist", "namespaceResourceWhitelist") for a in p[field]}
        for path, obj in self.files.items():
            if path.startswith(self.m.ROOT) or obj["kind"] == "Kustomization":
                continue
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            self.assertIn((group, obj["kind"]), allowed)

    def test_public_auth_certificate_is_covered_by_the_shared_issuer(self):
        files = manifest_files()
        names = files["gitops/clusters/oci-a1/argocd-ingress/issuer.yaml"]["spec"]["acme"]["solvers"][0]["selector"]["dnsNames"]
        self.assertIn(self.config["public_host"], names)
