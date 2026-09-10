"""Controller-only guards for local administrator access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class UserAccessGuards(unittest.TestCase):
    def test_unrelated_kubectl_is_preserved_and_k3s_link_is_accepted(self):
        binary = os.environ.get('ANSIBLE_TEST_BINARY')
        if not binary:
            self.skipTest('ANSIBLE_TEST_BINARY required')
        role = ROOT / 'ansible/roles/k3s_user_access'
        tasks = yaml.safe_load((role / 'tasks/main.yml').read_text())
        guard = next(t for t in tasks if t['name'] == 'Refuse to replace an unrelated kubectl installation')
        for stat, accepted in [
            ({'exists': False}, True),
            ({'exists': True, 'islnk': True, 'lnk_source': '/usr/local/bin/k3s'}, True),
            ({'exists': True, 'islnk': True, 'lnk_source': '/other/kubectl'}, False),
            ({'exists': True, 'isreg': True, 'checksum': 'unrelated'}, False),
        ]:
            with self.subTest(stat=stat), tempfile.TemporaryDirectory() as directory:
                play = Path(directory) / 'guard.yml'
                play.write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False,
                    'vars': {'k3s_user_kubectl': {'stat': stat}, 'role_path': str(role)},
                    'tasks': [guard]}]))
                result = subprocess.run([binary, '-i', 'localhost,', '-c', 'local', str(play)],
                    env={**os.environ, 'LC_ALL': 'en_US.UTF-8'}, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
