"""Optional native controller-only checks; never run host installation plays."""

import json
import base64
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_k3s_config

fixture = test_k3s_config.fixture


ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = ROOT / "ansible"


class AnsibleNativeTests(unittest.TestCase):
    def setUp(self):
        binary = os.environ.get("ANSIBLE_TEST_BINARY")
        if not binary:
            self.skipTest("ANSIBLE_TEST_BINARY not supplied; optional native check")
        self.binary = str(Path(binary).resolve())
        self.assertTrue(Path(self.binary).is_file())
        loader = test_k3s_config.K3sConfigTests()
        loader.setUp()
        self.module = loader.module

    def invoke(self, args, tokens=True):
        # Preserve genuine HOME but exclude user ANSIBLE_*/SSH/Kubernetes/Doppler
        # environment. Only controller-side actions execute in validate-inputs.
        environment = {"PATH": str(Path(self.binary).parent) + os.pathsep + os.defpath,
                       "ANSIBLE_CONFIG": str(ANSIBLE / "ansible.cfg"),
                       "ANSIBLE_NOCOLOR": "1"}
        if "HOME" in os.environ:
            environment["HOME"] = os.environ["HOME"]
        if tokens:
            environment["K3S_TEST_SERVER_TOKEN"] = "synthetic_server_secret_" + "x" * 32
            environment["K3S_TEST_AGENT_TOKEN"] = "K10" + "a" * 64 + "::server:synthetic_agent_secret_" + "y" * 32
            environment["K3S_TEST_SERVER_JOIN_TOKEN"] = "K10" + "a" * 64 + "::server:synthetic_join_secret_" + "z" * 32
        return subprocess.run([self.binary, *args], cwd=ANSIBLE, env=environment,
                              text=True, capture_output=True, timeout=60, check=False)

    def write_inventory(self, root, config):
        path = root / "hosts.json"
        path.write_text(json.dumps(self.module.inventory(config)), encoding="utf-8")
        return path

    def test_real_ansible_evaluates_inputs_and_templates_without_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_inventory(Path(directory), fixture())
            result = self.invoke(["-i", str(inventory), "playbooks/validate-inputs.yml"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("synthetic_server_secret", result.stdout + result.stderr)
            self.assertNotIn("synthetic_agent_secret", result.stdout + result.stderr)
            self.assertNotIn("ESTABLISH SSH", result.stdout + result.stderr)
            self.assertIn("changed=0", result.stdout)

    def test_missing_token_and_unreviewed_input_fail_before_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = self.write_inventory(root, fixture())
            result = self.invoke(["-i", str(inventory), "playbooks/validate-inputs.yml"], tokens=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Require a nonempty token", result.stdout)
            data = json.loads(inventory.read_text())
            data["all"]["vars"]["k3s_config"]["reviewed"] = False
            inventory.write_text(json.dumps(data), encoding="utf-8")
            result = self.invoke(["-i", str(inventory), "playbooks/validate-inputs.yml"])
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Gather target", result.stdout)

    def test_all_entrypoints_parse_and_agent_limit_excludes_server(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_inventory(Path(directory), fixture())
            plays = ["playbooks/" + name + ".yml" for name in
                     ["validate-inputs", "preflight", "install-server", "join-agents", "verify-cluster", "bootstrap-argocd", "bootstrap-doppler-auth"]]
            result = self.invoke(["-i", str(inventory), "--syntax-check", *plays], tokens=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = self.invoke(["-i", str(inventory), "--list-hosts", "--limit", "agent-one",
                                  "playbooks/join-agents.yml"], tokens=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("agent-one", result.stdout)
            self.assertNotIn("server-one", result.stdout)

    def test_install_check_mode_is_rejected_before_any_host_action(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_inventory(Path(directory), fixture())
            result = self.invoke(["-i", str(inventory), "--check", "playbooks/install-server.yml"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Use preflight.yml", result.stdout)
            self.assertNotIn("Gather target", result.stdout)

    def test_etcd_bootstrap_and_join_targets_are_separate(self):
        config = test_k3s_config.etcd_fixture()
        for index in [2, 3]:
            config["nodes"][f"server-{index}"] = dict(config["nodes"]["server-one"],
                ssh_host=f"192.0.2.{10+index}", node_ip=f"192.0.2.{10+index}")
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_inventory(Path(directory), config)
            result = self.invoke(["-i", str(inventory), "playbooks/validate-inputs.yml"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("synthetic_join_secret", result.stdout + result.stderr)
            bootstrap = self.invoke(["-i", str(inventory), "--list-hosts", "playbooks/install-server.yml"], tokens=False)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            self.assertIn("server-one", bootstrap.stdout)
            self.assertNotIn("server-2", bootstrap.stdout)
            join = self.invoke(["-i", str(inventory), "--list-hosts", "playbooks/join-servers.yml"], tokens=False)
            self.assertEqual(join.returncode, 0, join.stderr)
            self.assertIn("server-2", join.stdout)
            self.assertIn("server-3", join.stdout)
            self.assertNotIn("server-one", join.stdout)

    def test_argocd_missing_inputs_fail_before_remote_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.write_inventory(Path(directory), fixture())
            result = self.invoke(["-i", str(inventory), "playbooks/bootstrap-argocd.yml"], tokens=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Bootstrap requires reviewed server inventory", result.stdout)
            self.assertNotIn("Inspect first-stage", result.stdout)

    def test_doppler_missing_inputs_and_check_mode_never_invoke_runtime(self):
        for args in [[], ["--check", "-e", "doppler_python=/not-real/python doppler_run_config=/not-real/run.json"]]:
            result = self.invoke(["-i", "localhost,", *args, "playbooks/bootstrap-doppler-auth.yml"], tokens=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("TASK [Create missing", result.stdout)

    def test_real_rerun_assertions_reject_drift_and_missing_state(self):
        import yaml

        tasks = yaml.safe_load((ANSIBLE / "roles/k3s_preflight/tasks/main.yml").read_text())
        checks = []
        for task in tasks:
            if task["name"].startswith(("Reject existing", "Reject loss")):
                checks.append(task)
            if task["name"].startswith("Verify completed"):
                for nested in task["block"]:
                    if "ansible.builtin.assert" in nested:
                        check = dict(nested)
                        check["when"] = task["when"]
                        checks.append(check)
        self.assertEqual(len(checks), 4)
        content, unit, token = "test config", "test unit", "synthetic_token_do_not_print"
        sums = ["a" * 64] + [hashlib.sha256(value.encode()).hexdigest() for value in (content, token, unit)]
        variables = {
            "k3s_preflight_marker": {"stat": {"exists": True, "isreg": True, "islnk": False, "uid": 0}},
            "k3s_preflight_artifacts": {"results": [
                {"stat": {"checksum": digest, "isreg": True, "islnk": False, "uid": 0}}
                for digest in sums]},
            "k3s_preflight_existing_paths": {"results": [{"stat": {"exists": True}}]},
            "k3s_preflight_processes": {"rc": 1},
            "k3s_preflight_persistent_state": {"stat": {"isreg": True, "islnk": False}},
            "k3s_preflight_installed_fingerprint": {"content": base64.b64encode(b"fingerprint\n").decode()},
            "k3s_plan": {"fingerprint": "fingerprint", "sha256": "a" * 64},
            "k3s_config_content": content, "k3s_unit_content": unit, "k3s_runtime_token": token,
        }
        scenarios = [("unchanged", variables, True)]
        for label in ["binary", "config", "token", "unit", "fingerprint", "database", "unmanaged", "process"]:
            altered = copy.deepcopy(variables)
            if label in ("binary", "config", "token", "unit"):
                index = ["binary", "config", "token", "unit"].index(label)
                altered["k3s_preflight_artifacts"]["results"][index]["stat"]["checksum"] = "changed"
            elif label == "fingerprint":
                altered["k3s_plan"]["fingerprint"] = "changed"
            elif label == "database":
                altered["k3s_preflight_persistent_state"]["stat"] = {"exists": False}
            else:
                altered["k3s_preflight_marker"]["stat"]["exists"] = False
                if label == "process":
                    altered["k3s_preflight_existing_paths"]["results"] = []
                    altered["k3s_preflight_processes"]["rc"] = 0
            scenarios.append((label, altered, False))
        clean = copy.deepcopy(variables)
        clean["k3s_preflight_marker"]["stat"]["exists"] = False
        clean["k3s_preflight_existing_paths"]["results"] = []
        scenarios.append(("clean", clean, True))
        with tempfile.TemporaryDirectory() as directory:
            play = Path(directory) / "assertions.yml"
            for label, inputs, success in scenarios:
                with self.subTest(scenario=label):
                    play.write_text(json.dumps([{"name": "Synthetic assertions only", "hosts": "localhost",
                                                "gather_facts": False, "vars": inputs, "tasks": checks}]), encoding="utf-8")
                    result = self.invoke(["-i", "localhost,", "-c", "local", str(play)], tokens=False)
                    self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                    self.assertNotIn(token, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
