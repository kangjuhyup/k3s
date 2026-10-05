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
    for suffix in ['']:
        result = subprocess.run([args.kubectl, 'kustomize', str(BASE / suffix)], capture_output=True, text=True, check=True)
        resources.extend(yaml.safe_load_all(result.stdout))
    identities = [(r['apiVersion'], r['kind'], r['metadata'].get('namespace'), r['metadata']['name']) for r in resources]
    check(len(identities) == len(set(identities)), 'Duplicate Kubernetes resource ownership')
    check(not any(r['kind'] == 'Secret' for r in resources), 'Secret values must be Doppler-owned')
    workloads = [r for r in resources if r['kind'] in ['Deployment', 'StatefulSet', 'Job']]
    release = json.loads((BASE / 'release-images.json').read_text())
    check(re.fullmatch(r'[0-9a-f]{40}', release['revision']), 'Invalid source revision')
    revisions = {i['service']: i['revision'] for i in release['images']}
    check(all(re.fullmatch(r'[0-9a-f]{40}', r) for r in revisions.values()), 'Invalid service revision')
    expected = {i['service']: i['image'] + ':sha-' + i['revision'] + '@' + i['digest']
                for i in release['images']}
    check(set(expected) == {'account', 'match', 'payment', 'gateway', 'edge-authz', 'integration-ui', 'admin-ui'},
          'Incomplete release image manifest')
    # Code-only releases preserve completed schema Jobs and their immutable artifacts.
    migrations = release.get('migrationImages', [i for i in release['images'] if i['service'] in {'account', 'match', 'payment'}])
    check({i['service'] for i in migrations} == {'account', 'match', 'payment'} and len(migrations) == 3,
          'Incomplete migration image manifest')
    migration_revisions = {i['service']: i['revision'] for i in migrations}
    check(all(re.fullmatch(r'[0-9a-f]{40}', r) for r in migration_revisions.values()),
          'Invalid migration revision')
    migration_images = {i['service']: i['image'] + ':sha-' + i['revision'] + '@' + i['digest']
                        for i in migrations}
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
                check(c['image'] == (migration_images if r['kind'] == 'Job' else expected)[c['name']],
                      'Application/migration image differs from release')
                app_image_count += 1
                if r['kind'] == 'Job':
                    check(r['metadata']['name'] == c['name'] + '-migration-' + migration_revisions[c['name']][:12],
                          'Migration Job identity differs from release')
            check(c['securityContext']['allowPrivilegeEscalation'] is False, 'Privilege escalation allowed')
            if args.release:
                check(re.search(r'@sha256:[0-9a-f]{64}$', c['image']), 'Unpinned release image')
    check(app_image_count == 10, 'Expected seven application deployments and three migration image references')
    admin = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'admin-ui')
    container = admin['spec']['template']['spec']['containers'][0]
    check(all(container[p]['httpGet']['path'] == '/admin/health'
              for p in ['startupProbe', 'readinessProbe', 'livenessProbe']), 'Admin probe lost its base path')
    ui = next(r for r in resources if r['kind'] == 'VirtualService' and r['metadata']['name'] == 'gaegaeting-dev-ui')
    routes = ui['spec']['http']
    check(routes[0]['match'] == [{'port': 443, 'uri': {'exact': '/admin'}},
                                 {'port': 443, 'uri': {'prefix': '/admin/'}}], 'Admin path boundary changed')
    check(routes[0]['route'][0]['destination'] == {'host': 'admin-ui', 'port': {'number': 8080}},
          'Admin path points to wrong service')
    check(len(routes) == 2 and routes[1]['route'][0]['destination']['host'] == 'integration-ui',
          'User UI fallback changed')
    check(all('rewrite' not in r for r in routes), 'UI base paths must not be rewritten')
    root_path = BASE.parent / 'root'
    apps = [yaml.safe_load(p.read_text()) for p in root_path.glob('gaegaeting-dev*.yaml')
            if p.name != 'gaegaeting-dev-project.yaml']
    check(len(apps) == 1 and apps[0]['metadata']['name'] == 'gaegaeting-dev',
          'All Gaegaeting resources must belong to one Application')
    if not args.release:
        check(all(a['spec']['syncPolicy']['automated']['enabled'] is False for a in apps), 'Argo automation enabled before release')
        registered = yaml.safe_load((root_path / 'kustomization.yaml').read_text())['resources']
        check(all(a['metadata']['name'] + '.yaml' in registered for a in apps), 'Application missing from root')
    for r in resources:
        if r['kind'] == 'DopplerSecret':
            check((r['spec']['project'], r['spec']['config']) == (('infrastructure', 'prd') if r['metadata']['name'] == 'gaegaeting-dev-cloudflare' else ('gaegaeting', 'stg')), 'Cross-environment secret source')
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
    connection = config['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
    routes = connection['route_config']['virtual_hosts'][0]['routes']
    callbacks = {r['match'].get('path'): r for r in routes if r.get('route', {}).get('cluster') == 'payment'}
    check(set(callbacks) == {'/payment/notifications/apple', '/payment/notifications/google'},
          'Only exact provider callback routes may reach Payment directly')
    check(all(r['typed_per_filter_config']['envoy.filters.http.ext_authz']['disabled'] is True
              for r in callbacks.values()), 'Provider callbacks require provider authentication')
    check(routes[-1].get('direct_response', {}).get('status') == 404, 'Unknown public paths must fail closed')
    payment_ingress = policies['payment-ingress']['spec']['ingress']
    check(len(payment_ingress) == 1 and payment_ingress[0]['ports'] == [{'protocol': 'TCP', 'port': 2802}],
          'Payment ingress port changed')
    sources = payment_ingress[0]['from']
    check(len(sources) == 2 and {s['podSelector']['matchLabels']['app.kubernetes.io/name'] for s in sources}
          == {'gateway', 'edge-proxy'} and all(s['namespaceSelector']['matchLabels']
          == {'kubernetes.io/metadata.name': 'gaegaeting-dev'} for s in sources),
          'Payment ingress must be restricted to the Gateway and provider callback proxy')
    print(json.dumps({'resources':len(resources),'workloads':len(workloads),'mode':'release' if args.release else 'inactive-preparation','valid':True}))


if __name__ == '__main__':
    main()
