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
        for path in (root / 'gitops/clusters/oci-a1/vote/secrets').glob('*.yaml'):
            obj = gitops.read_json(path)
            if obj.get('kind') != 'DopplerSecret' or obj['spec']['project'] != 'vote':
                continue
            spec = obj['spec']
            require(spec['config'] == 'prd' and spec['tokenSecret']['name'] == 'doppler-auth-vote-prd')
            mappings.append({'name': obj['metadata']['name'], 'project': 'vote', 'config': 'prd',
                             'token_secret': spec['tokenSecret']['name'], 'token_env': 'DOPPLER_VOTE_PRD_TOKEN',
                             'target_namespace': spec['managedSecret']['namespace'],
                             'target_secret': spec['managedSecret']['name'], 'type': spec['managedSecret']['type'],
                             'resync_seconds': spec['resyncSeconds'],
                             'keys': {k: v['asName'] for k, v in spec['processors'].items()}})
        config = {'enabled': True, 'reviewed': True, 'sync_enabled': False,
                  'auth_ready_reviewed': False, 'targets_ready_reviewed': True, 'mappings': mappings}
        cluster = Cluster(run)
        app = cluster.get('application', 'vote', 'argocd')
        require(app['spec']['source']['path'] == 'gitops/clusters/oci-a1/vote')
        require(app['spec']['syncPolicy']['automated']['enabled'] is False)
        bootstrap = gitops.validate(gitops.read_json(root / gitops.SETTINGS_PATH))
        created = bootstrap_tokens(cluster, bootstrap, config, os.environ, 'DOPPLER_VOTE_PRD_TOKEN')
        print(json.dumps({'created': created, 'unchanged': created == 0, 'values_displayed': False}))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print('Vote credential bootstrap failed; values suppressed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
