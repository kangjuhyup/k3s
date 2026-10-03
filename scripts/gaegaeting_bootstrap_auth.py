#!/usr/bin/env python3
"""Ansible-only bootstrap of one config-scoped Doppler credential; never prints values."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from doppler_runtime import Cluster, bootstrap_tokens, validate_run, load, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-config', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        gitops = load('gitops_validate')
        run = validate_run(gitops.read_json(args.run_config))
        load('argocd_bundle').verify_checkout(root, run['expected_revision'])
        gitops.validate_repository(root)
        mappings = []
        configs = set()
        for path in (root / 'gitops/clusters/oci-a1/gaegaeting-dev/secrets').glob('*.yaml'):
            obj = gitops.read_json(path)
            if obj.get('kind') != 'DopplerSecret' or obj['spec']['project'] != 'gaegaeting':
                continue
            spec = obj['spec']
            config_name = spec['config']
            require(config_name in {'dev', 'stg'})
            require(spec['tokenSecret']['name'] == 'doppler-auth-gaegaeting-' + config_name)
            configs.add(config_name)
            mappings.append({'name': obj['metadata']['name'], 'project': 'gaegaeting', 'config': config_name,
                             'token_secret': spec['tokenSecret']['name'], 'token_env': 'DOPPLER_GAEGAETING_' + config_name.upper() + '_TOKEN',
                             'target_namespace': spec['managedSecret']['namespace'],
                             'target_secret': spec['managedSecret']['name'], 'type': spec['managedSecret']['type'],
                             'resync_seconds': spec['resyncSeconds'],
                             'keys': {k: v['asName'] for k, v in spec['processors'].items()}})
        require(len(configs) == 1)
        config_name = configs.pop()
        token_env = 'DOPPLER_GAEGAETING_' + config_name.upper() + '_TOKEN'
        config = {'enabled': True, 'reviewed': True, 'sync_enabled': False,
                  'auth_ready_reviewed': False, 'targets_ready_reviewed': True, 'mappings': mappings}
        cluster = Cluster(run)
        app = cluster.get('application', 'gaegaeting-dev', 'argocd')
        require(app['spec']['source']['path'] == 'gitops/clusters/oci-a1/gaegaeting-dev')
        if app['spec']['syncPolicy']['automated']['enabled'] is not False:
            # Add only a new stg credential during the authorized config transition.
            # Existing delivery and dev authentication remain under their current owners.
            require(config_name == 'stg')
            cluster.get('secret', 'doppler-auth-gaegaeting-dev', 'doppler-operator-system')
            for mapping in mappings:
                live = cluster.get('dopplersecret', mapping['name'], 'doppler-operator-system')
                require(live['spec']['project'] == 'gaegaeting')
                require(live['spec']['config'] in {'dev', 'stg'})
                require(live['spec']['managedSecret']['name'] == mapping['target_secret'])
                require(live['spec']['managedSecret']['namespace'] == mapping['target_namespace'])
        bootstrap = gitops.validate(gitops.read_json(root / gitops.SETTINGS_PATH))
        created = bootstrap_tokens(cluster, bootstrap, config, os.environ, token_env)
        print(json.dumps({'created': created, 'unchanged': created == 0, 'values_displayed': False}))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print('Gaegaeting credential bootstrap failed; values suppressed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
