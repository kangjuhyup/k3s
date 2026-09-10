"""Offline contract tests; fixtures are not deployment configuration."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[2] / "ansible/filter_plugins/k3s_config.py"


def fixture():
    return {
        "reviewed": True, "network_reviewed": True,
        "version": "v1.35.1+k3s1", "sha256": "a" * 64,
        "datastore": "sqlite", "pod_cidr": "10.42.0.0/16",
        "service_cidr": "10.43.0.0/16", "cluster_dns": "10.43.0.10",
        "endpoint": "https://192.0.2.10:6443", "tls_sans": ["192.0.2.10"],
        "servicelb": False, "token_env": {"server": "K3S_TEST_SERVER_TOKEN", "agent": "K3S_TEST_AGENT_TOKEN"},
        "nodes": {
            "server-one": {"role": "server", "ssh_host": "192.0.2.10", "ssh_user": "ubuntu",
                           "node_ip": "192.0.2.10", "flannel_iface": "enp0s1",
                           "os_distribution": "Ubuntu", "os_version": "24.04"},
            "agent-one": {"role": "agent", "ssh_host": "192.0.2.11", "ssh_user": "ubuntu",
                          "node_ip": "192.0.2.11", "flannel_iface": "enp0s1",
                          "os_distribution": "Ubuntu", "os_version": "24.04"},
        },
    }


def etcd_fixture():
    config = fixture()
    config.update(datastore="etcd", bootstrap_server="server-one")
    config["token_env"]["server_join"] = "K3S_TEST_SERVER_JOIN_TOKEN"
    return config


class K3sConfigTests(unittest.TestCase):
    def test_environment_references_preserve_rendered_installation_contract(self):
        original = fixture()
        refs = copy.deepcopy(original)
        refs['nodes']['server-one']['ssh_host'] = {'$env': 'TEST_PUBLIC_IP'}
        refs['tls_sans'] = {'$env_json': 'TEST_SANS_JSON'}
        with patch.dict(os.environ, {'TEST_PUBLIC_IP': original['nodes']['server-one']['ssh_host'],
                                     'TEST_SANS_JSON': json.dumps(original['tls_sans'])}):
            self.assertEqual(self.module.inventory(refs), self.module.inventory(original))
            self.assertEqual(self.module.render_node(refs, 'server-one'), self.module.render_node(original, 'server-one'))

    def test_environment_references_reject_missing_empty_and_invalid_json(self):
        with patch.dict(os.environ, {}, clear=True):
            for ref in [{'$env': 'MISSING'}, {'$env_json': 'MISSING'}, {'$env': 'bad-name'},
                        {'$env': 'MISSING', 'fallback': 'unsafe'}]:
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    self.module.resolve_environment(ref)
        for value in ['', ' ', 'not-json']:
            with patch.dict(os.environ, {'TEST_BAD_JSON': value}), self.assertRaises(ValueError):
                self.module.resolve_environment({'$env_json': 'TEST_BAD_JSON'})

    def test_disabled_backup_disables_local_and_remote_without_credentials(self):
        config = etcd_fixture()
        config['backup'] = {'enabled': False}
        values = self.module.render_node(config, 'server-one')['config']
        self.assertTrue(values['etcd-disable-snapshots'])
        self.assertFalse(values['etcd-s3'])
        self.assertNotIn('etcd-s3-bucket', values)
        self.assertNotIn('etcd-disable-snapshots', self.module.render_node(config, 'agent-one')['config'])

    def test_enabling_backup_requires_explicit_complete_policy(self):
        config = etcd_fixture()
        config['backup'] = {'enabled': True}
        with self.assertRaises(ValueError):
            self.module.validate(config)
        config['backup'].update(endpoint='s3.ap-northeast-1.wasabisys.com', region='ap-northeast-1',
                                bucket='test-backups', folder='k3s/test/etcd', schedule='0 0,6,12,18 * * *',
                                local_retention=28, remote_retention=360)
        values = self.module.render_node(config, 'server-one')['config']
        self.assertFalse(values['etcd-disable-snapshots'])
        self.assertTrue(values['etcd-s3'])
        self.assertNotIn('etcd-s3-secret-key', values)
        for key, invalid in [('endpoint', 'http://untrusted.example'), ('schedule', 'bad'),
                             ('local_retention', 0), ('remote_retention', True), ('folder', '../other')]:
            modified = copy.deepcopy(config)
            modified['backup'][key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.module.validate(modified)

    def setUp(self):
        spec = importlib.util.spec_from_file_location("k3s_config", MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_server_is_workload_capable_without_traefik_or_etcd(self):
        result = self.module.render_node(fixture(), "server-one")
        config = result["config"]
        self.assertEqual(config["disable"], ["traefik", "servicelb"])
        self.assertEqual(config["write-kubeconfig-mode"], "0600")
        self.assertTrue(config["secrets-encryption"])
        for key in ["cluster-init", "node-taint", "token", "server"]:
            self.assertNotIn(key, config)
        self.assertEqual(config["token-file"], "/etc/rancher/k3s/bootstrap-token")

    def test_agent_has_only_join_settings(self):
        result = self.module.render_node(fixture(), "agent-one")
        self.assertEqual(result["config"]["server"], fixture()["endpoint"])
        self.assertNotIn("disable", result["config"])
        self.assertNotIn("cluster-cidr", result["config"])
        self.assertEqual(result["service"], "k3s-agent")

    def test_only_explicit_bootstrap_initializes_etcd(self):
        config = etcd_fixture()
        config["nodes"]["server-two"] = dict(config["nodes"]["agent-one"], role="server")
        del config["nodes"]["agent-one"]
        first = self.module.render_node(config, "server-one")
        second = self.module.render_node(config, "server-two")
        self.assertTrue(first["config"]["cluster-init"])
        self.assertNotIn("server", first["config"])
        self.assertNotIn("cluster-init", second["config"])
        self.assertEqual(second["config"]["server"], config["endpoint"])
        self.assertEqual(second["token_env"], "K3S_TEST_SERVER_JOIN_TOKEN")
        self.assertEqual(second["service"], "k3s")
        for key in ["cluster-cidr", "service-cidr", "cluster-dns", "disable", "secrets-encryption"]:
            self.assertEqual(first["config"][key], second["config"][key])

    def test_adding_control_planes_does_not_reinitialize_existing_members(self):
        config = etcd_fixture()
        before = self.module.render_node(config, "server-one")
        for index in [2, 3]:
            config["nodes"][f"server-{index}"] = dict(config["nodes"]["server-one"],
                ssh_host=f"192.0.2.{10+index}", node_ip=f"192.0.2.{10+index}")
        self.assertEqual(before, self.module.render_node(config, "server-one"))
        groups = self.module.inventory(config)["all"]["children"]
        self.assertEqual(set(groups["k3s_bootstrap"]["hosts"]), {"server-one"})
        self.assertEqual(set(groups["k3s_joining_servers"]["hosts"]), {"server-2", "server-3"})

    def test_etcd_requires_explicit_server_bootstrap_and_distinct_join_token_reference(self):
        for bootstrap in [None, "missing", "agent-one"]:
            config = etcd_fixture()
            config["bootstrap_server"] = bootstrap
            with self.subTest(bootstrap=bootstrap), self.assertRaises(ValueError):
                self.module.validate(config)
        config = etcd_fixture()
        config["token_env"]["server_join"] = config["token_env"]["agent"]
        with self.assertRaises(ValueError):
            self.module.validate(config)

    def test_expansion_does_not_change_server_contract(self):
        original = fixture()
        expanded = copy.deepcopy(original)
        extra = copy.deepcopy(expanded["nodes"]["agent-one"])
        extra.update(ssh_host="192.0.2.12", node_ip="192.0.2.12")
        expanded["nodes"]["agent-two"] = extra
        self.assertEqual(self.module.render_node(original, "server-one"),
                         self.module.render_node(expanded, "server-one"))

    def test_rejects_missing_inputs_unknown_fields_and_unreviewed_values(self):
        mutations = [{"reviewed": False}, {"network_reviewed": "true"},
                     {"version": "latest"}, {"sha256": ""}, {"datastore": "etcd"},
                     {"token": "DO-NOT-PRINT"}, {"servicelb": "false"},
                     {"token_env": "TOKEN\nINJECT"}]
        for change in mutations:
            with self.subTest(keys=list(change)):
                config = fixture()
                config.update(change)
                with self.assertRaises(ValueError) as error:
                    self.module.render_node(config, "server-one")
                self.assertNotIn("DO-NOT-PRINT", str(error.exception))
        config = fixture()
        del config["sha256"]
        with self.assertRaises(ValueError):
            self.module.render_node(config, "server-one")

    def test_rejects_invalid_topology_and_node_fields(self):
        for field, value in [("role", "server"), ("node_ip", "192.0.2.10"),
                             ("ssh_host", "192.0.2.10"), ("ssh_host", "localhost"),
                             ("ssh_user", "root;touch /tmp/x"), ("os_distribution", "OracleLinux"),
                             ("flannel_iface", "eth0\nExecStart=x")]:
            config = fixture()
            config["nodes"]["agent-one"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.module.render_node(config, "server-one")
        with self.assertRaises(ValueError):
            self.module.render_node(fixture(), "unknown")

    def test_network_ranges_dns_and_endpoint_are_validated(self):
        for change in [
            {"pod_cidr": "10.43.0.0/16"}, {"cluster_dns": "10.42.0.10"},
            {"endpoint": "http://192.0.2.10:6443"},
            {"endpoint": "https://user:pass@192.0.2.10:6443"},
            {"endpoint": "https://192.0.2.10:6443/path"},
            {"tls_sans": ["other.example.invalid"]}, {"pod_cidr": "192.0.2.0/24"},
        ]:
            config = fixture()
            config.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.render_node(config, "server-one")

    def test_fingerprint_is_stable_and_detects_configuration_changes(self):
        config = fixture()
        before = self.module.render_node(config, "server-one")["fingerprint"]
        config["servicelb"] = True
        self.assertNotEqual(before, self.module.render_node(config, "server-one")["fingerprint"])
        self.assertEqual(len(before), 64)

    def test_inventory_generator_is_explicit_and_read_only_by_default(self):
        script = MODULE.parents[2] / "scripts/k3s_inventory.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "settings.json", root / "hosts.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            args = [sys.executable, str(script), "--input", str(source), "--output", str(output)]
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(output.exists())
            result = subprocess.run(args + ["--write"], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            generated = json.loads(output.read_text())
            self.assertEqual(set(generated["all"]["children"]["k3s_servers"]["hosts"]), {"server-one"})
            self.assertEqual(set(generated["all"]["children"]["k3s_agents"]["hosts"]), {"agent-one"})
            self.assertEqual(subprocess.run(args, capture_output=True, check=False).returncode, 0)
            before = output.read_bytes()
            source.write_text('{"token":"NEVER-PRINT","token":"DUPLICATE"}', encoding="utf-8")
            result = subprocess.run(args + ["--write"], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("NEVER-PRINT", result.stdout + result.stderr)
            self.assertEqual(before, output.read_bytes())
            output.unlink()
            output.symlink_to(source)
            result = subprocess.run(args + ["--write"], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
