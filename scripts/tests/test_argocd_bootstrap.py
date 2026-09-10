"""State-machine tests use only a fake Kubernetes client."""
import copy
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from test_argocd_gitops import manifest_files, fixture, load


def secret_fixture():
    return {"admin_password_hash": "$2b$12$" + "a" * 53, "server_secretkey": "x" * 40,
            "redis_auth": "y" * 40, "git_username": "synthetic-user", "git_password": "synthetic-token"}


def healthy(expected, revisions):
    app = copy.deepcopy(expected)
    multi = "sources" in app["spec"]
    revision_data = {"revisions": revisions} if multi else {"revision": revisions[0]}
    app["status"] = {"health": {"status": "Healthy"}, "sync": {
        "status": "Synced", **revision_data,
        "comparedTo": {key: app["spec"][key] for key in ["destination", "sources" if multi else "source"]}},
        "operationState": {"phase": "Succeeded", "syncResult": revision_data}}
    return app


class FakeClient:
    def __init__(self, bundle, existing=False):
        self.bundle = bundle
        self.writes, self.events = [], []
        self.objects = {}
        if existing:
            self.objects[("namespace", "argocd")] = {"metadata": {"annotations": {
                "infrastructure.local/bootstrap-id": bundle["identity"]}}}
            self.reconcile()

    def reconcile(self):
        revision = self.bundle["expected_revision"]
        self.objects[("applications.argoproj.io", "oci-a1-root")] = healthy(self.bundle["root"], [revision])
        self.objects[("applications.argoproj.io", "argocd")] = healthy(self.bundle["self"], ["10.8.2", revision])

    def check_api(self, version):
        self.events.append("api")

    def get(self, kind, name):
        return self.objects.get((kind, name))

    def create(self, obj):
        self.writes.append(copy.deepcopy(obj))
        self.events.append(obj["kind"] + "/" + obj["metadata"]["name"])
        if obj["kind"] == "Application":
            self.reconcile()

    def wait_crds(self):
        self.events.append("crds-established")

    def rollouts(self):
        self.events.append("rollouts")


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.runtime = load("argocd_bootstrap_runtime")
        gitops = load("gitops_validate")
        config = fixture()
        files = manifest_files()
        # Keep transport credentials synthetic while exercising the Git-owned apps.
        config["repo_url"] = files[gitops.SETTINGS_PATH]["repo_url"]
        self.bundle = {"schema": 1, "config": config, "identity": gitops.identity(config),
                       "expected_revision": "a" * 40, "initial_accounts": True,
                       "root": files[gitops.ROOT_PATH + "/root.yaml"],
                       "self": files[gitops.ROOT_PATH + "/argocd.yaml"],
                       "projects": [files[gitops.ROOT_PATH + "/" + name] for name in ["root-project.yaml", "platform-project.yaml"]],
                       "resources": [
                           {"kind": "CustomResourceDefinition", "metadata": {"name": "applications.argoproj.io"}},
                           {"kind": "Deployment", "metadata": {"name": "argocd-server", "namespace": "argocd"}},
                           {"kind": "StatefulSet", "metadata": {"name": "argocd-application-controller", "namespace": "argocd"}}]}

    def test_fresh_bootstrap_orders_prerequisites_and_only_seeds_root(self):
        client = FakeClient(self.bundle)
        result = self.runtime.bootstrap(self.bundle, secret_fixture(), client, attempts=1, pause=lambda _: None)
        self.assertTrue(result["changed"])
        self.assertLess(client.events.index("Secret/argocd-redis"), client.events.index("Deployment/argocd-server"))
        self.assertLess(client.events.index("crds-established"), client.events.index("AppProject/bootstrap-root"))
        apps = [o["metadata"]["name"] for o in client.writes if o["kind"] == "Application"]
        self.assertEqual(apps, ["oci-a1-root"])

    def test_handed_off_cluster_has_zero_writes_and_needs_no_secrets(self):
        client = FakeClient(self.bundle, existing=True)
        result = self.runtime.bootstrap(self.bundle, {}, client, attempts=1, pause=lambda _: None)
        self.assertFalse(result["changed"])
        self.assertEqual(client.writes, [])

    def test_foreign_namespace_and_cluster_resource_conflicts_never_write(self):
        for conflict in ["namespace", "crd"]:
            client = FakeClient(self.bundle)
            if conflict == "namespace":
                client.objects[("namespace", "argocd")] = {"metadata": {}}
            else:
                client.objects[("CustomResourceDefinition", "applications.argoproj.io")] = {"metadata": {}}
            with self.subTest(conflict=conflict), self.assertRaises(ValueError):
                self.runtime.bootstrap(self.bundle, secret_fixture(), client, attempts=1, pause=lambda _: None)
            self.assertEqual(client.writes, [])

    def test_partial_bootstrap_is_not_overwritten_or_reported_complete(self):
        client = FakeClient(self.bundle, existing=True)
        client.objects.pop(("applications.argoproj.io", "argocd"))
        with self.assertRaises(ValueError):
            self.runtime.bootstrap(self.bundle, {}, client, attempts=1, pause=lambda _: None)
        self.assertEqual(client.writes, [])

    def test_invalid_secrets_and_managed_account_phase_block_first_write(self):
        for field in ["admin_password_hash", "server_secretkey", "git_password"]:
            values = secret_fixture()
            values[field] = ""
            client = FakeClient(self.bundle)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.runtime.bootstrap(self.bundle, values, client, attempts=1, pause=lambda _: None)
            self.assertEqual(client.writes, [])
        self.bundle["initial_accounts"] = False
        with self.assertRaises(ValueError):
            self.runtime.bootstrap(self.bundle, secret_fixture(), FakeClient(self.bundle), attempts=1, pause=lambda _: None)

    def test_revision_health_source_overrides_and_stale_status_fail_handoff(self):
        expected = self.bundle["self"]
        revisions = ["10.8.2", "a" * 40]
        for mutation in ["revision", "operation", "health", "source", "compared", "error", "pending", "autosync"]:
            app = healthy(expected, revisions)
            if mutation == "revision":
                app["status"]["sync"]["revisions"] = ["10.8.2", "b" * 40]
            elif mutation == "operation":
                app["status"]["operationState"]["phase"] = "Failed"
            elif mutation == "health":
                app["status"]["health"]["status"] = "Progressing"
            elif mutation == "source":
                app["spec"]["sources"][0]["helm"]["parameters"] = [{"name": "configs.cm.admin.enabled", "value": "true"}]
            elif mutation == "compared":
                app["status"]["sync"]["comparedTo"] = {}
            elif mutation == "error":
                app["status"]["conditions"] = [{"type": "ComparisonError"}]
            elif mutation == "autosync":
                app["spec"]["syncPolicy"]["automated"]["enabled"] = False
            else:
                app["operation"] = {"sync": {}}
            with self.subTest(mutation=mutation):
                self.assertFalse(self.runtime.handoff_ready(app, expected, revisions))

    def test_kubectl_transport_uses_explicit_context_and_secret_stdin_only(self):
        document = self.runtime.secrets(fixture(), secret_fixture())[0]
        with patch.object(self.runtime.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="created")) as execute:
            self.runtime.Kubectl().create(document)
        args, options = execute.call_args
        self.assertIn("--context=default", args[0])
        self.assertIn("--namespace=argocd", args[0])
        self.assertIn("--kubeconfig=/etc/rancher/k3s/k3s.yaml", args[0])
        self.assertIn("create", args[0])
        self.assertNotIn("apply", args[0])
        self.assertNotIn(secret_fixture()["admin_password_hash"], " ".join(args[0]))
        self.assertIn(secret_fixture()["admin_password_hash"], options["input"])


if __name__ == "__main__":
    unittest.main()
