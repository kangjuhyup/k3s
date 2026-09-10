"""Fake Kubernetes only: never reads a real kubeconfig or real environment secrets."""
import base64
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_argocd_gitops import fixture as bootstrap, load
from test_doppler_gitops import fixture


class FakeCluster:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def get(self, kind, name, namespace=None, optional=False):
        obj = self.objects.get((kind, namespace, name))
        if not optional and obj is None:
            raise ValueError("not found")
        return obj

    def create(self, obj):
        self.writes.append(copy.deepcopy(obj))
        self.objects[(obj["kind"].lower(), obj["metadata"]["namespace"], obj["metadata"]["name"])] = obj


class DopplerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.module = load("doppler_runtime")
        self.config = fixture(False)
        self.mapping = self.config["mappings"][0]
        self.cluster = FakeCluster()
        self.cluster.objects[("namespace", None, "istio-system")] = {"kind": "Namespace"}
        self.environment = {self.mapping["token_env"]: "dp.st.synthetic-not-real-" + "x" * 32}

    def test_create_only_and_identical_rerun_are_idempotent(self):
        self.assertEqual(self.module.bootstrap_tokens(self.cluster, bootstrap(), self.config, self.environment), 1)
        self.assertEqual(self.module.bootstrap_tokens(self.cluster, bootstrap(), self.config, self.environment), 0)
        self.assertEqual(len(self.cluster.writes), 1)
        obj = self.cluster.writes[0]
        self.assertEqual(set(obj["data"]), {"serviceToken"})
        self.assertEqual(obj["metadata"]["namespace"], "doppler-operator-system")

    def test_client_context_api_guard_and_secret_stdin_not_environment(self):
        run = {"kubectl": "/synthetic/kubectl", "kubeconfig": "/synthetic/config",
               "context": "test-context", "api_server": "https://api.example.invalid:6443"}
        view = {"current-context": "test-context", "clusters": [{"cluster": {"server": run["api_server"]}}]}
        with patch.object(self.module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(view))) as execute:
            client = self.module.Cluster(run)
            client.create({"kind": "Secret", "data": {"serviceToken": "SYNTHETIC_DO_NOT_ECHO"}})
            args, kwargs = execute.call_args
            self.assertIn("--context", args[0])
            self.assertIn("--namespace", args[0])
            self.assertNotIn("SYNTHETIC_DO_NOT_ECHO", " ".join(args[0]))
            self.assertNotIn("SYNTHETIC_DO_NOT_ECHO", str(kwargs["env"]))
            self.assertIn("SYNTHETIC_DO_NOT_ECHO", kwargs["input"])
            self.assertEqual(set(kwargs["env"]) - {"HOME"}, {"PATH"})
            view["clusters"][0]["cluster"]["insecure-skip-tls-verify"] = True
            execute.return_value.stdout = json.dumps(view)
            with self.assertRaises(ValueError):
                self.module.Cluster(run)

    def test_missing_credentials_conflicting_token_and_foreign_target_never_write(self):
        for mode in ["missing", "foreign-auth", "changed-token", "foreign-target", "namespace-absent"]:
            with self.subTest(mode=mode):
                self.setUp()
                if mode in {"foreign-auth", "changed-token"}:
                    self.module.bootstrap_tokens(self.cluster, bootstrap(), self.config, self.environment)
                    self.cluster.writes.clear()
                    if mode == "foreign-auth":
                        next(obj for obj in self.cluster.objects.values() if obj.get("kind") == "Secret")["metadata"]["annotations"] = {}
                    else:
                        self.environment[self.mapping["token_env"]] += "changed"
                elif mode == "missing":
                    self.environment.clear()
                elif mode == "namespace-absent":
                    self.cluster.objects.clear()
                else:
                    self.cluster.objects[("secret", "istio-system", "web-external-tls")] = {"metadata": {}}
                with self.assertRaises(ValueError):
                    self.module.bootstrap_tokens(self.cluster, bootstrap(), self.config, self.environment)
                self.assertEqual(self.cluster.writes, [])

    def test_all_tokens_checked_before_first_write_and_sync_must_be_off(self):
        second = copy.deepcopy(self.mapping)
        second.update(name="other-tls", target_secret="other-tls", token_secret="doppler-auth-other", token_env="OTHER_TOKEN")
        self.config["mappings"].append(second)
        with self.assertRaises(ValueError):
            self.module.bootstrap_tokens(self.cluster, bootstrap(), self.config, self.environment)
        self.assertEqual(self.cluster.writes, [])
        with self.assertRaises(ValueError):
            self.module.bootstrap_tokens(self.cluster, bootstrap(), fixture(), self.environment)

    def test_verification_checks_keys_owner_condition_and_no_argo_tracking(self):
        config = fixture()
        cr = next(v for v in self.module.doppler.render(bootstrap(), config).values() if v.get("kind") == "DopplerSecret")
        cr["status"] = {"conditions": [{"type": "secrets.doppler.com/SecretSyncReady", "status": "True"}]}
        secret = {"type": "kubernetes.io/tls", "metadata": {"annotations": {
            "secrets.doppler.com/managed-by": "doppler-operator-system/web-tls"}},
            "data": {k: base64.b64encode(b"synthetic").decode() for k in ["tls.crt", "tls.key"]}}
        self.cluster.objects[("dopplersecret", "doppler-operator-system", "web-tls")] = cr
        self.cluster.objects[("secret", "istio-system", "web-external-tls")] = secret
        self.assertEqual(self.module.verify_delivery(self.cluster, bootstrap(), config), 1)
        for mode in ["key", "owner", "condition", "tracking"]:
            old = copy.deepcopy(self.cluster.objects)
            if mode == "key":
                secret["data"]["tls.key"] = ""
            elif mode == "owner":
                secret["metadata"]["annotations"]["secrets.doppler.com/managed-by"] = "another/owner"
            elif mode == "condition":
                cr["status"]["conditions"][0]["status"] = "False"
            else:
                secret["metadata"]["annotations"]["argocd.argoproj.io/tracking-id"] = "owned"
            with self.assertRaises(ValueError):
                self.module.verify_delivery(self.cluster, bootstrap(), config)
            self.cluster.objects = old
            cr = self.cluster.objects[("dopplersecret", "doppler-operator-system", "web-tls")]
            secret = self.cluster.objects[("secret", "istio-system", "web-external-tls")]

    def test_explicit_config_bootstrap_does_not_require_unrelated_tokens(self):
        config = fixture()
        other = copy.deepcopy(config["mappings"][0])
        other.update(name="other-tls", target_secret="other-tls", token_secret="doppler-auth-other", token_env="OTHER_TOKEN")
        config["mappings"].append(other)
        self.assertEqual(self.module.bootstrap_tokens(self.cluster, bootstrap(), config, self.environment,
                         self.mapping["token_env"]), 1)
        self.assertEqual(len(self.cluster.writes), 1)
        with self.assertRaises(ValueError):
            self.module.bootstrap_tokens(self.cluster, bootstrap(), config, self.environment, "UNKNOWN_TOKEN")
