"""Optional offline integration checks against explicit local official tools.

Set ARGOCD_TEST_BINARY, HELM_TEST_BINARY and ARGOCD_TEST_CHART to local files.
No downloads, real configuration files, cluster requests or installs occur here.
"""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "argocd_accounts.py"
spec = importlib.util.spec_from_file_location("argocd_accounts", SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def fixture():
    return {
        "phase": "managed",
        "accounts": [
            {"name": "owner", "role": "platform-admin", "enabled": True, "projects": []},
            {"name": "alice", "role": "developer", "enabled": True, "projects": ["sample-app"]},
            {"name": "disabled", "role": "developer", "enabled": False, "projects": ["sample-app"]},
        ],
        # Synthetic test attestations, not evidence of any live login.
        "cutover": {"verified_admin": "owner", "recovery_verified": True},
    }


class NativeAccountTests(unittest.TestCase):
    def local_file(self, key):
        value = os.environ.get(key)
        if not value:
            self.skipTest(key + " not supplied; optional native check")
        path = Path(value).resolve()
        self.assertTrue(path.is_file(), key + " must name an existing local file")
        return str(path)

    def invoke(self, command):
        # Explicit local inputs plus a minimal environment keep user credentials
        # and inherited ARGOCD_* options outside these fixture checks.
        environment = {"PATH": os.defpath}
        # Preserve the genuine system home required by the CLI; never redirect
        # it. Explicit --config/--kubeconfig use only temporary fixture paths.
        if "HOME" in os.environ:
            environment["HOME"] = os.environ["HOME"]
        return subprocess.run(command, text=True, capture_output=True, check=False,
                              timeout=30, env=environment)

    def test_native_rbac_allows_only_expected_actions(self):
        binary = self.local_file("ARGOCD_TEST_BINARY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "argocd-rbac-cm.yaml"
            policy.write_text(json.dumps({
                "apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {"name": "argocd-rbac-cm"},
                "data": renderer.render_values(fixture())["configs"]["rbac"],
            }), encoding="utf-8")
            # The CLI builds client configuration even for local policy files.
            # A fake token suppresses interactive auth prompting. No real
            # credentials or exec hooks; policy-file avoids API requests.
            kubeconfig = root / "offline-kubeconfig.json"
            kubeconfig.write_text(json.dumps({
                "apiVersion": "v1", "kind": "Config",
                "clusters": [{"name": "offline", "cluster": {"server": "https://127.0.0.1:1"}}],
                "users": [{"name": "offline", "user": {"token": "synthetic-offline-test-only"}}],
                "contexts": [{"name": "offline", "context": {"cluster": "offline", "user": "offline"}}],
                "current-context": "offline",
            }), encoding="utf-8")
            options = ["--policy-file", str(policy), "--config", str(root / "no-config"),
                       "--kubeconfig", str(kubeconfig), "--load-cluster-settings=false"]
            validation = self.invoke([binary, "admin", "settings", "rbac", "validate", *options])
            self.assertEqual(validation.returncode, 0, validation.stderr)
            cases = [
                ("alice", "get", "applications", "sample-app/web", "Yes"),
                ("alice", "get", "projects", "sample-app", "Yes"),
                ("alice", "get", "applications", "other/web", "No"),
                ("alice", "sync", "applications", "sample-app/web", "No"),
                ("alice", "update", "applications", "sample-app/web", "No"),
                ("alice", "delete", "applications", "sample-app/web", "No"),
                ("alice", "override", "applications", "sample-app/web", "No"),
                ("alice", "create", "exec", "sample-app/web", "No"),
                ("alice", "get", "logs", "sample-app/web", "No"),
                ("disabled", "get", "applications", "sample-app/web", "No"),
                ("unknown", "get", "applications", "sample-app/web", "No"),
                ("owner", "get", "applications", "other/web", "Yes"),
            ]
            for subject, action, resource, target, expected in cases:
                with self.subTest(subject=subject, action=action, resource=resource, target=target):
                    result = self.invoke([binary, "admin", "settings", "rbac", "can",
                                          subject, action, resource, target, *options])
                    self.assertEqual(result.stdout.strip(), expected, result.stderr)
                    self.assertEqual(result.returncode, 0 if expected == "Yes" else 1)

    def test_official_chart_renders_bootstrap_and_managed_values(self):
        helm = self.local_file("HELM_TEST_BINARY")
        chart = self.local_file("ARGOCD_TEST_CHART")
        with tempfile.TemporaryDirectory() as directory:
            values_file = Path(directory) / "accounts.values.yaml"
            for phase, expected in [("bootstrap", "true"), ("managed", "false")]:
                with self.subTest(phase=phase):
                    config = fixture()
                    config["phase"] = phase
                    values_file.write_text(yaml.safe_dump(renderer.render_values(config)), encoding="utf-8")
                    result = self.invoke([
                        helm, "template", "accounts-check", chart, "--namespace", "argocd",
                        "--values", str(values_file),
                        "--show-only", "templates/argocd-configs/argocd-cm.yaml",
                        "--show-only", "templates/argocd-configs/argocd-rbac-cm.yaml",
                    ])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for key, value in {
                        "admin.enabled": expected, "users.anonymous.enabled": "false",
                        "accounts.alice": "login", "accounts.alice.enabled": "true",
                        "accounts.disabled.enabled": "false", "policy.default": "role:authenticated",
                    }.items():
                        self.assertRegex(result.stdout, r"(?m)^  " + re.escape(key) + r': [\"\x27]?' + re.escape(value) + r'[\"\x27]?$')
                    self.assertIn("p, alice, applications, get, sample-app/*, allow", result.stdout)
                    self.assertIn("g, owner, role:admin", result.stdout)
                    self.assertNotIn("kind: Secret", result.stdout)


if __name__ == "__main__":
    unittest.main()
