"""Offline tests: real renderer and CLI, no cloud clients or mocks."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "argocd_accounts.py"


def bootstrap():
    return {
        "phase": "bootstrap",
        "accounts": [],
        "cutover": {"verified_admin": None, "recovery_verified": False},
    }


def account(name="alice", role="developer", enabled=True, projects=None):
    return {
        "name": name, "role": role, "enabled": enabled,
        "projects": ["sample-app"] if projects is None else projects,
    }


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.exists():
            return
        spec = importlib.util.spec_from_file_location("argocd_accounts", SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "Account renderer has not been implemented")

    def render(self, config):
        return self.module.render_values(config)

    def test_bootstrap_keeps_admin_and_grants_no_default_access(self):
        self.assertEqual(self.render(bootstrap()), {"configs": {
            "cm": {"admin.enabled": "true", "users.anonymous.enabled": "false"},
            "rbac": {"policy.default": "role:authenticated", "policy.csv": "",
                     "policy.matchMode": "glob", "scopes": "[]"},
        }})

    def test_developer_gets_only_own_project_read_access(self):
        config = bootstrap()
        config["accounts"] = [account()]
        values = self.render(config)["configs"]
        self.assertEqual(values["cm"]["accounts.alice"], "login")
        self.assertEqual(values["cm"]["accounts.alice.enabled"], "true")
        self.assertEqual(values["rbac"]["policy.csv"],
                         "p, alice, applications, get, sample-app/*, allow\n"
                         "p, alice, projects, get, sample-app, allow\n")

    def test_disabled_account_has_no_policy_grants(self):
        config = bootstrap()
        config["accounts"] = [account(enabled=False)]
        values = self.render(config)["configs"]
        self.assertEqual(values["cm"]["accounts.alice.enabled"], "false")
        self.assertEqual(values["rbac"]["policy.csv"], "")

    def test_managed_requires_live_admin_and_recovery_attestations(self):
        config = bootstrap()
        config["phase"] = "managed"
        config["accounts"] = [account("owner", "platform-admin", projects=[])]
        cases = [
            {"verified_admin": None, "recovery_verified": False},
            {"verified_admin": "owner", "recovery_verified": False},
            {"verified_admin": "missing", "recovery_verified": True},
        ]
        for cutover in cases:
            with self.subTest(cutover=cutover), self.assertRaises(ValueError):
                config["cutover"] = cutover
                self.render(config)
        config["cutover"] = {"verified_admin": "owner", "recovery_verified": True}
        values = self.render(config)["configs"]
        self.assertEqual(values["cm"]["admin.enabled"], "false")
        self.assertEqual(values["rbac"]["policy.csv"], "g, owner, role:admin\n")
        config["accounts"][0]["enabled"] = False
        with self.assertRaises(ValueError):
            self.render(config)
        config["accounts"] = [account("owner")]
        with self.assertRaises(ValueError):
            self.render(config)

    def test_rejects_duplicate_accounts_and_policy_injection(self):
        cases = [
            [account(), account()], [account("admin")], [account("role:admin")],
            [account("alice\np, alice, *, *, *, allow")],
            [account(projects=["*"])], [account(projects=["foo/*"])],
            [account(projects=["foo, allow"])], [account(projects=["foo\nbar"])],
            [account(projects=[])], [account(projects=["sample-app", "sample-app"])],
            [account("owner", "platform-admin", projects=["sample-app"])],
        ]
        for accounts in cases:
            with self.subTest(accounts=accounts), self.assertRaises(ValueError):
                config = bootstrap()
                config["accounts"] = accounts
                self.render(config)

    def test_rejects_types_and_secret_fields_without_echoing_values(self):
        mutations = [
            {"enabled": "false"}, {"enabled": 1}, {"role": "admin"},
            {"projects": "sample-app"}, {"name": None},
            {"password": "DO_NOT_ECHO_THIS"}, {"apiKey": True},
        ]
        for mutation in mutations:
            config = bootstrap()
            config["accounts"] = [dict(account(), **mutation)]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError) as error:
                self.render(config)
            self.assertNotIn("DO_NOT_ECHO_THIS", str(error.exception))
        for config in [None, [], {}, dict(bootstrap(), phase="other"),
                       dict(bootstrap(), password="DO_NOT_ECHO_THIS"),
                       dict(bootstrap(), accounts=None)]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.render(config)

    def test_output_is_stable_under_input_reordering(self):
        config = bootstrap()
        config["accounts"] = [account("bob", projects=["project-b", "project-a"]), account()]
        reordered = copy.deepcopy(config)
        reordered["accounts"].reverse()
        reordered["accounts"][1]["projects"].reverse()
        self.assertEqual(self.render(config), self.render(reordered))

    def invoke(self, source, output, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output), *extra],
            text=True, capture_output=True, check=False,
        )

    def test_cli_checks_without_writing_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "accounts.json"
            output = Path(directory) / "accounts.values.json"
            source.write_text(json.dumps(bootstrap()), encoding="utf-8")
            self.assertNotEqual(self.invoke(source, output).returncode, 0)
            self.assertFalse(output.exists())
            result = self.invoke(source, output, "--write")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text()), self.render(bootstrap()))
            self.assertEqual(self.invoke(source, output).returncode, 0)
            output.write_text("stale", encoding="utf-8")
            self.assertNotEqual(self.invoke(source, output).returncode, 0)
            self.assertEqual(output.read_text(), "stale")

    def test_invalid_input_never_overwrites_output_or_echoes_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "accounts.json"
            output = Path(directory) / "accounts.values.json"
            output.write_text("keep-me", encoding="utf-8")
            for body in ['{"phase":"bootstrap","phase":"managed"}',
                         '{"password":"DO_NOT_ECHO_THIS"}', 'DO_NOT_ECHO_THIS']:
                source.write_text(body, encoding="utf-8")
                result = self.invoke(source, output, "--write")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("DO_NOT_ECHO_THIS", result.stdout + result.stderr)
                self.assertEqual(output.read_text(), "keep-me")

    def test_cli_refuses_overwriting_source_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "accounts.json"
            source.write_text(json.dumps(bootstrap()), encoding="utf-8")
            before = source.read_text()
            self.assertNotEqual(self.invoke(source, source, "--write").returncode, 0)
            self.assertEqual(source.read_text(), before)
            link = Path(directory) / "link.values.json"
            link.symlink_to(source)
            self.assertNotEqual(self.invoke(source, link, "--write").returncode, 0)
            self.assertEqual(source.read_text(), before)


if __name__ == "__main__":
    unittest.main()
