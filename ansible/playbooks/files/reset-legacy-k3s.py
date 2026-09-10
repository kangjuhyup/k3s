#!/usr/bin/env python3
"""One-time reset of the inspected legacy host, never the replacement cluster.

Process, mount and netfilter cleanup follows the K3s v1.28.5+k3s1 installer
killall procedure, narrowed to this single installation and checked paths.
Source: https://github.com/k3s-io/k3s/blob/v1.28.5%2Bk3s1/install.sh
"""
import argparse
import json
import ipaddress
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

MARKER = Path('/var/lib/k3s-legacy-reset-20260910.complete')
ROOTS = ['/etc/rancher/k3s', '/var/lib/rancher/k3s', '/var/lib/kubelet',
         '/run/k3s', '/run/flannel', '/var/lib/cni', '/etc/cni/net.d',
         '/var/log/pods', '/var/log/containers', '/var/log/k3s', '/var/backups/k3s']
FILES = ['/etc/systemd/system/k3s.service', '/usr/local/bin/k3s']


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def scoped(path, roots=ROOTS):
    return any(path == root or path.startswith(root + '/') for root in roots)


def process_start(pid):
    try:
        return Path('/proc/%d/stat' % pid).read_text().rsplit(') ', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def process_active(pid, start):
    try:
        fields = Path('/proc/%d/stat' % pid).read_text().rsplit(') ', 1)[1].split()
        return fields[19] == start and fields[0] not in ('Z', 'X')
    except FileNotFoundError:
        return False


def cleanup_links(links):
    cni_indexes = {link['ifindex'] for link in links if link['ifname'] == 'cni0'}
    children = [link['ifname'] for link in links
                if link.get('master') == 'cni0' or link.get('master') in cni_indexes]
    return children + [link['ifname'] for link in links if link['ifname'] in ('cni0', 'flannel.1')]


def clean_rules(current):
    return '\n'.join(line for line in current.splitlines()
                     if not re.search(r'KUBE-|CNI-|FLANNEL', line, re.I)) + '\n'


def require_stopped_and_unmounted():
    require(run('systemctl', 'show', 'k3s', '--property=ActiveState', '--value').strip() == 'inactive',
            'Resume requires an inactive legacy service')
    require(run('systemctl', 'show', 'k3s', '--property=MainPID', '--value').strip() == '0',
            'Resume requires no service process')
    processes = run('ps', '-e', '-o', 'comm=', '-o', 'args=').splitlines()
    require(not any(re.match(r'(k3s(?:-server|-agent)?|containerd(?:-shim)?)\s', line.strip())
                    or '/var/lib/rancher/k3s/data/' in line for line in processes),
            'Resume refused: legacy runtime processes remain')
    require(not any(scoped(p) or p.startswith('/run/netns/cni-')
                    for p in run('findmnt', '-rn', '-o', 'TARGET').splitlines()),
            'Resume refused: legacy mounts remain')


def delete_cluster_link(name):
    try:
        run('ip', 'link', 'delete', name)
    except subprocess.CalledProcessError:
        links = json.loads(run('ip', '-j', 'link', 'show'))
        if any(link['ifname'] == name for link in links):
            raise


def inspect(resume=False):
    require(os.geteuid() == 0, 'Root required')
    if MARKER.exists():
        print('Legacy reset already completed; replacement cluster will not be touched')
        return False
    require(not Path('/etc/rancher/k3s/ansible-install-complete').exists(),
            'Refusing to reset an Ansible-managed replacement cluster')
    expected = os.environ.get('K3S_RESET_EXPECTED_CIDR', '')
    try:
        expected = str(ipaddress.IPv4Interface(expected))
    except ValueError:
        raise SystemExit('Explicit reviewed reset network required') from None
    require(expected in run('ip', '-4', 'addr', 'show', 'enp0s6'), 'Unexpected host network')
    for path in ROOTS + FILES:
        require(not Path(path).is_symlink(), 'Refusing redirected reset path: ' + path)
    for binary in ('systemctl', 'ip', 'ps', 'findmnt', 'umount', 'iptables-save',
                   'iptables-restore', 'ip6tables-save', 'ip6tables-restore'):
        require(shutil.which(binary) is not None, 'Missing reset tool: ' + binary)
    for family in ('iptables', 'ip6tables'):
        run(family + '-restore', '--test', input=clean_rules(run(family + '-save')))
    require('k3s version v1.28.5+k3s1 ' in run('/usr/local/bin/k3s', '--version'),
            'Only the inspected legacy K3s version can be reset')
    import yaml
    config = yaml.safe_load(Path('/etc/rancher/k3s/config.yaml').read_text())
    require(config.get('data-dir') == '/var/lib/rancher/k3s' and config.get('cluster-init') is True,
            'Unexpected datastore or data directory')
    if resume:
        require_stopped_and_unmounted()
        print('Validated stopped legacy cluster and unmounted cleanup scope; no API access required')
        print('Remove paths: ' + ', '.join(ROOTS + FILES))
        return True
    pvs = json.loads(run('/usr/local/bin/k3s', 'kubectl', '--context', 'default',
                        '--kubeconfig', '/etc/rancher/k3s/k3s.yaml',
                        '--request-timeout=15s', 'get', 'pv', '-o', 'json'))['items']
    for pv in pvs:
        path = pv['spec'].get('hostPath', {}).get('path', '')
        require(path.startswith('/var/lib/rancher/k3s/storage/'), 'Unexpected PV backend; stop for review')
    print('Validated legacy version, embedded etcd and %d local PVs' % len(pvs))
    print('Remove paths: ' + ', '.join(ROOTS + FILES))
    return True


def execute():
    # Snapshot descendants before stopping the service: container shims survive it.
    processes = {}
    for line in run('ps', '-e', '-o', 'pid=', '-o', 'ppid=', '-o', 'args=').splitlines():
        pid, ppid, args = line.strip().split(None, 2)
        processes[int(pid)] = (int(ppid), args)
    targets = {pid for pid, (_, args) in processes.items()
               if re.match(r'/var/lib/rancher/k3s/data/[^/]+/bin/containerd-shim', args)}
    service_pid = int(run('systemctl', 'show', 'k3s', '--property=MainPID', '--value').strip())
    require(service_pid > 1, 'Legacy service is not running; inspect partial reset manually')
    targets.add(service_pid)
    while True:
        children = {pid for pid, (ppid, _) in processes.items() if ppid in targets}
        if children <= targets:
            break
        targets |= children
    starts = {pid: process_start(pid) for pid in targets}
    run('systemctl', 'stop', 'k3s')
    for pid in sorted(targets, reverse=True):
        if starts[pid] is None or process_start(pid) != starts[pid]:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while any(process_active(pid, starts[pid]) for pid in targets):
        require(time.monotonic() < deadline, 'Legacy processes remain; no mounts or data removed')
        time.sleep(0.2)
    run('systemctl', 'disable', 'k3s')
    # Normal unmount only; a busy mount aborts deletion instead of forcing it.
    mounts = run('findmnt', '-rn', '-o', 'TARGET').splitlines()
    for path in sorted(mounts, key=len, reverse=True):
        if scoped(path) or path.startswith('/run/netns/cni-'):
            run('umount', path)
    require(not any(scoped(p) for p in run('findmnt', '-rn', '-o', 'TARGET').splitlines()),
            'Mounts remain under reset paths')
    finish_cleanup()


def finish_cleanup():
    require_stopped_and_unmounted()
    for line in run('ip', 'netns', 'list').splitlines():
        name = line.split()[0]
        if name.startswith('cni-'):
            run('ip', 'netns', 'delete', name)
    links = json.loads(run('ip', '-j', 'link', 'show'))
    for name in cleanup_links(links):
        delete_cluster_link(name)
    # Preserve UFW, SSH policy and all non-Kubernetes rules.
    for family in ('iptables', 'ip6tables'):
        current = run(family + '-save')
        clean = clean_rules(current)
        run(family + '-restore', '--test', input=clean)
        run(family + '-restore', input=clean)
    for path in ROOTS:
        if Path(path).exists():
            shutil.rmtree(path)
    for path in FILES:
        Path(path).unlink(missing_ok=True)
    run('systemctl', 'daemon-reload')
    MARKER.write_text('Legacy v1.28.5+k3s1 cluster and local PVs removed\n')
    MARKER.chmod(0o600)
    print('Legacy K3s reset completed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--inspect-resume', action='store_true')
    parser.add_argument('--resume-cleanup', action='store_true')
    args = parser.parse_args()
    require(sum([args.inspect, args.execute, args.inspect_resume, args.resume_cleanup]) == 1,
            'Select exactly one mode')
    if inspect(resume=args.inspect_resume or args.resume_cleanup):
        if args.execute:
            execute()
        elif args.resume_cleanup:
            finish_cleanup()
