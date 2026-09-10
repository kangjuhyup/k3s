"""Non-secret stage-two contracts, no cluster or Git service access."""
import importlib.util
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


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
        self.module = load("argocd_gitops")

    def test_self_management_uses_pinned_chart_and_git_values(self):
        files = self.module.render(fixture())
        app = files["gitops/clusters/oci-a1/root/argocd.json"]
        self.assertEqual(app["spec"]["sources"][0]["targetRevision"], "10.8.2")
        self.assertIn("$values/gitops/platform/argocd/accounts.values.json", app["spec"]["sources"][0]["helm"]["valueFiles"])
        self.assertEqual(app["spec"]["sources"][1]["ref"], "values")
        for path, value in files.items():
            if value.get("kind") == "Application":
                auto = value["spec"]["syncPolicy"]["automated"]
                self.assertEqual(auto, {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False})
                self.assertIn("ServerSideApply=true", value["spec"]["syncPolicy"]["syncOptions"])
                self.assertNotIn("finalizers", value["metadata"])

    def test_root_is_restricted_and_secrets_are_not_git_objects(self):
        files = self.module.render(fixture())
        project = files["gitops/clusters/oci-a1/root/root-project.json"]["spec"]
        self.assertEqual(project["sourceRepos"], [fixture()["repo_url"]])
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
                self.module.render(config)
            self.assertNotIn("DO_NOT_ECHO", str(failure.exception))

    def test_active_configuration_is_reviewed_and_public_git_is_explicit(self):
        config = json.loads((ROOT / "gitops/clusters/oci-a1/bootstrap.json").read_text())
        self.assertTrue(config['reviewed'])
        self.assertEqual(config['auth']['mode'], 'public')
        files = self.module.render(config)
        self.assertEqual(files['gitops/clusters/oci-a1/root/root.json']['spec']['source']['repoURL'], config['repo_url'])

    def test_baseline_separates_secrets_and_keeps_private_single_node_settings(self):
        values = json.loads((ROOT / "gitops/platform/argocd/base.values.json").read_text())
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

    def test_generator_cli_checks_before_writing_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / self.module.SETTINGS_PATH
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(fixture()), encoding="utf-8")
            args = [sys.executable, str(ROOT / "scripts/argocd_gitops.py"), "--repo-root", str(root)]
            result = subprocess.run(args, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / self.module.ROOT_PATH).exists())
            result = subprocess.run(args + ["--write"], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(self.module.check_files(root, self.module.render(fixture())))
            self.assertEqual(subprocess.run(args, capture_output=True, check=False).returncode, 0)
            target = root / self.module.ENV_PATH
            target.unlink()
            target.symlink_to(settings)
            original = settings.read_bytes()
            self.assertEqual(subprocess.run(args + ["--write"], capture_output=True, check=False).returncode, 1)
            self.assertEqual(settings.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
