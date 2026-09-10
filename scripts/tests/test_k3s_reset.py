"""Safety boundaries for the authorized legacy reset; never contacts a host."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / 'ansible/playbooks/files/reset-legacy-k3s.py'
spec = importlib.util.spec_from_file_location('legacy_reset', SOURCE)
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


class LegacyResetSafetyTests(unittest.TestCase):
    def test_disappeared_link_is_tolerated_only_after_confirmed_absent(self):
        failure = subprocess.CalledProcessError(1, ['ip', 'link', 'delete', 'veth-old'])
        with patch.object(reset, 'run', side_effect=[failure, '[{"ifname":"enp0s6"}]']):
            reset.delete_cluster_link('veth-old')
        with patch.object(reset, 'run', side_effect=[failure, '[{"ifname":"veth-old"}]']):
            with self.assertRaises(subprocess.CalledProcessError):
                reset.delete_cluster_link('veth-old')

    def test_resume_requires_inactive_service_no_processes_and_no_mounts(self):
        for values, accepted in [(['inactive\n', '0\n', 'sshd sshd\n', '/\n'], True),
                                 (['active\n'], False),
                                 (['inactive\n', '123\n'], False),
                                 (['inactive\n', '0\n', 'containerd containerd\n'], False),
                                 (['inactive\n', '0\n', 'sshd sshd\n', '/var/lib/kubelet/pods/a\n'], False)]:
            with self.subTest(values=values), patch.object(reset, 'run', side_effect=values):
                if accepted:
                    reset.require_stopped_and_unmounted()
                else:
                    with self.assertRaises(SystemExit):
                        reset.require_stopped_and_unmounted()

    def test_only_exact_directories_and_descendants_are_in_deletion_scope(self):
        for path in ['/var/lib/rancher/k3s', '/var/lib/rancher/k3s/storage/pvc-123']:
            self.assertTrue(reset.scoped(path))
        for path in ['/', '/var/lib', '/var/lib/rancher/k3s-other', '/home/ubuntu', '/var/cache/k3s-bootstrap']:
            self.assertFalse(reset.scoped(path))

    def test_only_cni_bridge_children_and_known_cluster_links_are_removed(self):
        links = [{'ifindex': 2, 'ifname': 'enp0s6'}, {'ifindex': 3, 'ifname': 'cni0'},
                 {'ifindex': 4, 'ifname': 'veth-a', 'master': 3},
                 {'ifindex': 5, 'ifname': 'veth-b', 'master': 'cni0'},
                 {'ifindex': 6, 'ifname': 'docker0'}, {'ifindex': 7, 'ifname': 'flannel.1'}]
        self.assertEqual(reset.cleanup_links(links), ['veth-a', 'veth-b', 'cni0', 'flannel.1'])

    def test_firewall_cleanup_preserves_ssh_and_ufw_rules(self):
        rules = '*filter\n:ufw-user-input - [0:0]\n-A INPUT -j ufw-user-input\n-A ufw-user-input -p tcp --dport 22 -j ACCEPT\n:KUBE-SERVICES - [0:0]\n-A FORWARD -j KUBE-SERVICES\nCOMMIT\n'
        clean = reset.clean_rules(rules)
        self.assertIn('--dport 22 -j ACCEPT', clean)
        self.assertIn('-A INPUT -j ufw-user-input', clean)
        self.assertNotIn('KUBE-', clean)

    def test_failed_stop_never_deletes_data_or_restarts_service(self):
        calls = []
        def invoke(*args, **kwargs):
            calls.append(args)
            if args[0] == 'ps':
                return '100 1 k3s server\n101 100 containerd\n'
            if args[:2] == ('systemctl', 'show'):
                return '100\n'
            raise subprocess.CalledProcessError(1, args)
        with patch.object(reset, 'run', side_effect=invoke), patch.object(reset, 'process_start', return_value='10'), patch.object(reset.os, 'kill') as kill, patch.object(reset.shutil, 'rmtree') as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                reset.execute()
            kill.assert_not_called()
            remove.assert_not_called()
        self.assertFalse(any('start' in call or 'restart' in call for call in calls))

    def test_busy_mount_aborts_before_any_data_is_removed(self):
        def invoke(*args, **kwargs):
            if args[0] == 'ps':
                return '100 1 k3s server\n'
            if args[:2] == ('systemctl', 'show'):
                return '100\n'
            if args[0] == 'findmnt':
                return '/var/lib/kubelet/pods/example\n'
            if args[0] == 'umount':
                raise subprocess.CalledProcessError(1, args)
            return ''
        with patch.object(reset, 'run', side_effect=invoke), patch.object(reset, 'process_start', return_value='10'), patch.object(reset.os, 'kill'), patch.object(reset.shutil, 'rmtree') as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                reset.execute()
            remove.assert_not_called()

    def test_surviving_process_prevents_unmounts_and_data_deletion(self):
        def invoke(*args, **kwargs):
            if args[0] == 'ps':
                return '100 1 k3s server\n'
            if args[:2] == ('systemctl', 'show'):
                return '100\n'
            return ''
        with patch.object(reset, 'run', side_effect=invoke) as commands, patch.object(reset, 'process_start', return_value='10'), patch.object(reset, 'process_active', return_value=True), patch.object(reset.time, 'monotonic', side_effect=[0, 11]), patch.object(reset.os, 'kill'), patch.object(reset.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(SystemExit, 'Legacy processes remain'):
                reset.execute()
            remove.assert_not_called()
            self.assertFalse(any(call.args[0] in ('findmnt', 'umount') for call in commands.call_args_list))


if __name__ == '__main__':
    unittest.main()
