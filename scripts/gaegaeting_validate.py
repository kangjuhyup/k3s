#!/usr/bin/env python3
"""Render Gaegaeting dev declarations and verify inactive preparation or release gates."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'gitops/clusters/oci-a1/gaegaeting-dev'


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', default=str(ROOT / '.local/bin/kubectl-1.36.4'))
    parser.add_argument('--release', action='store_true')
    args = parser.parse_args()
    resources = []
    for suffix in ['', 'kafka', 'secrets', 'database', 'ingress']:
        result = subprocess.run([args.kubectl, 'kustomize', str(BASE / suffix)], capture_output=True, text=True, check=True)
        resources.extend(yaml.safe_load_all(result.stdout))
    identities = [(r['apiVersion'], r['kind'], r['metadata'].get('namespace'), r['metadata']['name']) for r in resources]
    check(len(identities) == len(set(identities)), 'Duplicate Kubernetes resource ownership')
    check(not any(r['kind'] == 'Secret' for r in resources), 'Secret values must be Doppler-owned')
    workloads = [r for r in resources if r['kind'] in ['Deployment', 'StatefulSet', 'Job']]
    release = json.loads((BASE / 'release-images.json').read_text())
    check(re.fullmatch(r'[0-9a-f]{40}', release['revision']), 'Invalid source revision')
    expected = {i['service']: i['image'] + ':sha-' + release['revision'] + '@' + i['digest']
                for i in release['images']}
    check(set(expected) == {'account', 'match', 'gateway', 'edge-authz', 'integration-ui'},
          'Incomplete release image manifest')
    app_image_count = 0
    for r in workloads:
        spec = r['spec']
        pod = spec['template']['spec']
        check(pod.get('automountServiceAccountToken') is False, 'Unexpected Kubernetes API token access')
        check(pod['securityContext']['runAsNonRoot'] is True, 'Root workload')
        if not args.release:
            check(spec.get('suspend') is True if r['kind'] == 'Job' else spec.get('replicas') == 0, 'Preparation may not start workloads')
        for c in pod['containers']:
            if c['name'] in expected:
                check(c['image'] == expected[c['name']], 'Application/migration image differs from release')
                app_image_count += 1
                if r['kind'] == 'Job':
                    check(r['metadata']['name'] == c['name'] + '-migration-' + release['revision'][:12],
                          'Migration Job identity differs from release')
            check(c['securityContext']['allowPrivilegeEscalation'] is False, 'Privilege escalation allowed')
            if args.release:
                check(re.search(r'@sha256:[0-9a-f]{64}$', c['image']), 'Unpinned release image')
    check(app_image_count == 7, 'Expected five deployments and two migration image references')
    apps = list(yaml.safe_load_all((BASE / 'applications.yaml').read_text()))
    if not args.release:
        check(all(a['spec']['syncPolicy']['automated']['enabled'] is False for a in apps), 'Argo automation enabled before release')
        active = (BASE.parent / 'root/kustomization.yaml').read_text()
        check('gaegaeting' not in active, 'Preparation referenced by active root')
    for r in resources:
        if r['kind'] == 'DopplerSecret':
            check((r['spec']['project'], r['spec']['config']) == (('infrastructure', 'prd') if r['metadata']['name'] == 'gaegaeting-dev-cloudflare' else ('gaegaeting', 'dev')), 'Cross-environment secret source')
    policies = {r['metadata']['name']: r for r in resources if r['kind'] == 'NetworkPolicy'}
    gateway = policies['gateway-ingress']['spec']['ingress'][0]['from']
    check(len(gateway) == 1 and gateway[0]['podSelector']['matchLabels']['app.kubernetes.io/name'] == 'edge-proxy', 'Gateway permits edge bypass')
    proxy = next(r for r in resources if r['kind'] == 'ConfigMap' and r['metadata']['name'] == 'edge-proxy-start')['data']['start.sh']
    check('failure_mode_allow: false' in proxy, 'Edge authentication must fail closed')
    config = yaml.safe_load(proxy.split('<<EOF\n', 1)[1].rsplit('EOF\n', 1)[0])
    filters = config['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']['http_filters']
    lua = filters[0]['typed_config']['default_source_code']['inline_string']
    for header in ['x-gaegaeting-principal', 'x-gaegaeting-edge-assertion']:
        check('remove("' + header + '")' in lua, 'Client assertion header not removed')
    print(json.dumps({'resources':len(resources),'workloads':len(workloads),'mode':'release' if args.release else 'inactive-preparation','valid':True}))


if __name__ == '__main__':
    main()
