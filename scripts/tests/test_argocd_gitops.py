"""Non-secret stage-two contracts, no cluster or Git service access."""
import importlib.util
from pathlib import Path
import yaml
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def manifest_files(component=None):
    """Read the checked-in source of truth, optionally scoped to one application."""
    files = {str(p.relative_to(ROOT)): yaml.safe_load(p.read_text())
             for p in (ROOT / "gitops").rglob("*")
             if p.is_file() and p.suffix in {".json", ".yaml"}}
    if component is None:
        return files
    base = "gitops/clusters/oci-a1/"
    return {p: obj for p, obj in files.items() if p.startswith(base + component + "/")
            or p in {base + "root/" + component + ".yaml", base + "root/" + component + "-project.yaml"}}


def layout(component):
    """Paths only; no generated defaults or resource construction."""
    result = SimpleNamespace(PATH="gitops/clusters/oci-a1/" + component,
                             ROOT="gitops/clusters/oci-a1/root",
                             ENV="gitops/clusters/oci-a1/argocd.values.yaml",
                             VALUES="gitops/platform/" + component + "/base.values.yaml",
                             PUBLIC_VALUES="gitops/clusters/oci-a1/grafana-public.values.yaml",
                             NAMESPACE="cnpg-system" if component == "cnpg" else component)
    if component == "redis":
        data = manifest_files("redis")[result.PATH + "/config.yaml"]["data"]
        result.START, result.CONFIG, result.HEALTH = data["start.sh"], data["redis.conf"], data["health.sh"]
    return result


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return {"reviewed": True, "repo_url": "https://git.example.invalid/team/infra.git",
            "revision": "main", "kube_version": "1.35.1",
            "auth": {"mode": "https-token", "username_env": "TEST_GIT_USERNAME", "password_env": "TEST_GIT_TOKEN"},
            "doppler": {"project": "test-infra", "config": "test"},
            "secret_env": {"admin_password_hash": "TEST_ADMIN_HASH", "server_secretkey": "TEST_SERVER_KEY", "redis_auth": "TEST_REDIS_AUTH"}}


class GitOpsTests(unittest.TestCase):
    def setUp(self):
        self.module = load("gitops_validate")

    def test_self_management_uses_pinned_chart_and_git_values(self):
        files = manifest_files()
        app = files["gitops/clusters/oci-a1/root/argocd.yaml"]
        self.assertEqual(app["spec"]["sources"][0]["targetRevision"], "10.8.2")
        self.assertIn("$values/gitops/platform/argocd/accounts.values.yaml", app["spec"]["sources"][0]["helm"]["valueFiles"])
        self.assertEqual(app["spec"]["sources"][1]["ref"], "values")
        for path, value in files.items():
            if value.get("kind") == "Application":
                auto = value["spec"]["syncPolicy"]["automated"]
                self.assertEqual(auto, {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False})
                self.assertIn("ServerSideApply=true", value["spec"]["syncPolicy"]["syncOptions"])
                self.assertNotIn("finalizers", value["metadata"])

    def test_root_is_restricted_and_secrets_are_not_git_objects(self):
        files = manifest_files()
        project = files["gitops/clusters/oci-a1/root/root-project.yaml"]["spec"]
        self.assertEqual(project["sourceRepos"], [files[self.module.SETTINGS_PATH]["repo_url"]])
        self.assertEqual(project["clusterResourceWhitelist"], [])
        self.assertEqual({p["kind"] for p in project["namespaceResourceWhitelist"]}, {"Application", "AppProject"})
        self.assertFalse(any(value.get("kind") == "Secret" for value in files.values()))

    def test_rejects_unreviewed_auth_in_urls_and_unknown_fields(self):
        for change in [{"reviewed": False}, {"repo_url": "https://user:secret@git.example.com/r.git"},
                       {"repo_url": "http://git.example.com/r.git"}, {"revision": "HEAD"},
                       {"revision": "main^{commit}"}, {"kube_version": "latest"},
                       {"secret": "DO_NOT_ECHO"}]:
            config = fixture()
            config.update(change)
            with self.subTest(change=list(change)), self.assertRaises(ValueError) as failure:
                self.module.validate(config)
            self.assertNotIn("DO_NOT_ECHO", str(failure.exception))

    def test_active_configuration_is_reviewed_and_public_git_is_explicit(self):
        config = yaml.safe_load((ROOT / "gitops/clusters/oci-a1/bootstrap.json").read_text())
        self.assertTrue(config['reviewed'])
        self.assertEqual(config['auth']['mode'], 'public')
        files = manifest_files()
        self.assertEqual(files['gitops/clusters/oci-a1/root/root.yaml']['spec']['source']['repoURL'], config['repo_url'])

    def test_baseline_separates_secrets_and_keeps_private_single_node_settings(self):
        values = yaml.safe_load((ROOT / "gitops/platform/argocd/base.values.yaml").read_text())
        self.assertFalse(values["configs"]["secret"]["createSecret"])
        self.assertFalse(values["redisSecretInit"]["enabled"])
        self.assertEqual(values["server"]["service"]["type"], "ClusterIP")
        self.assertFalse(values["configs"]["params"]["server.insecure"])
        self.assertFalse(values["dex"]["enabled"])
        self.assertIn("@sha256:", values["global"]["image"]["tag"])

    def test_remote_check_uses_scoped_environment_auth_and_exact_branch_sha(self):
        module = load("argocd_remote_check")
        calls = []
        def fake(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\trefs/heads/main\n")
        environment = {"TEST_GIT_USERNAME": "test-user", "TEST_GIT_TOKEN": "SYNTHETIC_PRIVATE_TOKEN"}
        module.verify(fixture(), "a" * 40, environment, execute=fake)
        self.assertNotIn("SYNTHETIC_PRIVATE_TOKEN", " ".join(calls[0][0]))
        self.assertEqual(calls[0][1]["env"]["GIT_CONFIG_KEY_0"], "http." + fixture()["repo_url"] + ".extraHeader")
        self.assertIn("http.followRedirects=false", calls[0][0])
        with self.assertRaises(ValueError):
            module.verify(fixture(), "b" * 40, environment, execute=fake)


if __name__ == "__main__":
    unittest.main()
