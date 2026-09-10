"""Controller-only migration gates; no SSH, service or filesystem changes on a node."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / 'ansible/playbooks/migrate-sqlite-to-etcd.yml'


class DatastoreMigrationGates(unittest.TestCase):
    def setUp(self):
        binary = os.environ.get('ANSIBLE_TEST_BINARY')
        if not binary:
            self.skipTest('ANSIBLE_TEST_BINARY required for controller-only checks')
        self.binary = str(Path(binary).resolve())
        self.tasks = yaml.safe_load(PLAYBOOK.read_text())[0]['tasks']

    def assert_gate(self, name, variables, accepted):
        task = next(copy.deepcopy(task) for task in self.tasks if task['name'] == name)
        task.pop('when', None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gate.yml'
            path.write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False,
                                         'vars': variables, 'tasks': [task]}]))
            environment = dict(os.environ)
            environment['LC_ALL'] = 'en_US.UTF-8'
            environment['ANSIBLE_CONFIG'] = str(ROOT / 'ansible/ansible.cfg')
            result = subprocess.run([self.binary, '-i', 'localhost,', '-c', 'local', str(path)],
                                    text=True, capture_output=True, env=environment, timeout=30)
            self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)

    def test_unowned_or_redirected_installations_cannot_be_migrated(self):
        for stat, accepted in [({'isreg': True, 'islnk': False, 'uid': 0}, True),
                               ({'exists': False}, False),
                               ({'isreg': True, 'islnk': True, 'uid': 0}, False),
                               ({'isreg': True, 'islnk': False, 'uid': 1000}, False)]:
            with self.subTest(stat=stat):
                self.assert_gate('Require an existing owned installation',
                                 {'migration_marker': {'stat': stat}}, accepted)

    def test_only_exact_sqlite_source_or_completed_etcd_fingerprint_is_accepted(self):
        for fingerprint, accepted in [('source', True), ('desired', True), ('drift', False)]:
            variables = {'migration_marker_content': {'content': base64.b64encode(fingerprint.encode()).decode()},
                         'migration_sqlite_plan': {'fingerprint': 'source'},
                         'migration_desired_plan': {'fingerprint': 'desired'}}
            with self.subTest(fingerprint=fingerprint):
                self.assert_gate('Require either the exact previous or completed desired installation', variables, accepted)

    def test_partial_etcd_conversion_cannot_be_automatically_restarted(self):
        for exists in [False, True]:
            self.assert_gate('Reject a partial or externally initialized datastore migration',
                             {'migration_existing_etcd': {'stat': {'exists': exists}}}, not exists)

    def test_live_multi_node_cluster_cannot_be_converted_by_single_node_procedure(self):
        for names, accepted in [('localhost', True), ('localhost another-server', False), ('', False)]:
            self.assert_gate('Require only the selected bootstrap node in the live cluster',
                             {'migration_actual_nodes': {'stdout': names}}, accepted)

    def test_migration_is_not_completed_if_the_node_identity_changes(self):
        for before, after, accepted in [('original-uid', 'original-uid', True),
                                         ('original-uid', 'replacement-uid', False), ('', '', False)]:
            self.assert_gate('Require the same node identity after conversion',
                             {'migration_node_identity_before': {'stdout': before},
                              'migration_node_identity_after': {'stdout': after}}, accepted)

    def test_verification_only_recovery_requires_original_identity(self):
        uid = '305e3cea-30bf-408f-ad8c-73db34c5b5bb'
        for original, accepted in [(uid, True), ('different', False), ('', False)]:
            self.assert_gate('Require the same node identity after conversion',
                             {'migration_node_identity_before': {'stdout': uid},
                              'migration_node_identity_after': {'stdout': uid},
                              'migration_finalize_only': True,
                              'migration_original_node_uid': original}, accepted)


if __name__ == '__main__':
    unittest.main()
