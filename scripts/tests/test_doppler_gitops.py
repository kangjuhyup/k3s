"""Offline Doppler declarations, ownership and upstream artifact checks."""
import copy
import os
from pathlib import Path
import tempfile
import yaml
import unittest

from test_argocd_gitops import ROOT, fixture as bootstrap, load


def fixture(sync=True):
    return {"enabled": True, "reviewed": True, "sync_enabled": sync,
            "auth_ready_reviewed": sync, "targets_ready_reviewed": sync,
            "mappings": [{"name": "web-tls", "project": "test-web", "config": "prd",
                          "token_secret": "doppler-auth-web", "token_env": "TEST_DOPPLER_WEB_TOKEN",
                          "target_namespace": "istio-system", "target_secret": "web-external-tls",
                          "type": "kubernetes.io/tls", "resync_seconds": 120,
                          "keys": {"WEB_TLS_CERT": "tls.crt", "WEB_TLS_KEY": "tls.key"}}]}


class DopplerTests(unittest.TestCase):
    def setUp(self):
        self.module = load("doppler_gitops")

    def test_disabled_configuration_renders_nothing(self):
        config = fixture(False)
        config.update(enabled=False, reviewed=False, mappings=[])
        self.module.validate(config)
        self.assertFalse(config["enabled"])
        self.assertEqual(self.module.render(bootstrap(), config), {})

    def test_operator_then_auth_then_sync_are_separate_gates(self):
        initial = self.module.render(bootstrap(), fixture(False))
        active = self.module.render(bootstrap(), fixture())
        self.assertTrue(any(v.get("kind") == "Application" for v in initial.values()))
        self.assertFalse(any(v.get("kind") == "DopplerSecret" for v in initial.values()))
        cr = next(v for v in active.values() if v.get("kind") == "DopplerSecret")
        self.assertEqual(cr["spec"]["secrets"], ["WEB_TLS_CERT", "WEB_TLS_KEY"])
        self.assertEqual(cr["spec"]["processors"]["WEB_TLS_CERT"], {"type": "plain", "asName": "tls.crt"})
        self.assertTrue(cr["spec"]["verifyTLS"])
        self.assertEqual(cr["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "20")
        self.assertFalse(any(v.get("kind") == "Secret" for v in active.values()))
        project = next(v for v in active.values() if v.get("kind") == "AppProject")
        self.assertNotIn("Secret", [x["kind"] for x in project["spec"]["namespaceResourceWhitelist"]])

    def test_write_rbac_has_no_delete_and_update_is_name_scoped(self):
        files = self.module.render(bootstrap(), fixture())
        role = next(v for v in files.values() if v.get("kind") == "Role")
        for rule in role["rules"]:
            self.assertEqual(rule["resources"], ["secrets"])
            self.assertNotIn("delete", rule["verbs"])
            if "update" in rule["verbs"]:
                self.assertEqual(rule["resourceNames"], ["web-external-tls"])

    def test_rejects_unreviewed_broad_reserved_and_ambiguous_mappings(self):
        cases = []
        for key in ["reviewed", "auth_ready_reviewed", "targets_ready_reviewed"]:
            config = fixture()
            config[key] = False
            cases.append(config)
        for changes in [{"target_namespace": "argocd"}, {"target_secret": "cacerts"},
                        {"target_namespace": "kube-system"}, {"keys": {}},
                        {"keys": {"WEB_TLS_CERT": "tls.crt"}}, {"type": "Opaque"},
                        {"resync_seconds": True}, {"serviceToken": "DO_NOT_PRINT"}]:
            config = fixture()
            config["mappings"][0].update(changes)
            cases.append(config)
        duplicated = fixture()
        duplicated["mappings"].append(copy.deepcopy(duplicated["mappings"][0]))
        cases.append(duplicated)
        for config in cases:
            with self.assertRaises(ValueError) as failure:
                self.module.validate(config)
            self.assertNotIn("DO_NOT_PRINT", str(failure.exception))


    def test_pinned_upstream_chart_and_hardened_render(self):
        archive = os.environ.get("DOPPLER_TEST_CHART")
        if not archive:
            self.skipTest("DOPPLER_TEST_CHART not supplied")
        vendor = load("doppler_vendor")
        files = vendor.render(Path(archive))
        self.assertEqual(len([v for v in files.values() if v.get("kind") != "Kustomization"]), 9)
        for path, value in files.items():
            self.assertEqual(yaml.safe_load((ROOT / path).read_text()), value)
        deployment = next(v for v in files.values() if v.get("kind") == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"]["kubernetes.io/arch"], "arm64")
        self.assertIn("@sha256:", pod["containers"][0]["image"])
        role = next(v for v in files.values() if v.get("kind") == "ClusterRole")
        for rule in role["rules"]:
            self.assertNotIn("serviceaccounts/token", rule["resources"])
            if "secrets" in rule["resources"] or "deployments" in rule["resources"]:
                self.assertEqual(set(rule["verbs"]), {"get", "list", "watch"})
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.tgz"
            bad.write_bytes(b"not the approved artifact")
            with self.assertRaises(ValueError):
                vendor.render(bad)
