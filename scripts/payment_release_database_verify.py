"""Run Payment tests in isolated PostgreSQL/Node containers sharing one clock."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid


def verify(source):
    assert (source / '.nvmrc').read_text().strip() == '24.13.1'
    image = re.search(r'node:24\.13\.1-bookworm-slim@sha256:[a-f0-9]{64}',
                      (source / 'deploy/docker/Dockerfile').read_text()).group()
    password = uuid.uuid4().hex
    environment = {**os.environ, 'POSTGRES_PASSWORD': password,
                   'POSTGRES_USER': 'payment_fixture', 'POSTGRES_DB': 'payment_fixture'}
    container = None
    try:
        created = subprocess.run(['docker', 'run', '--detach', '--rm', '--pull=never',
                                  '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_USER', '-e', 'POSTGRES_DB',
                                  'postgres:16.15'], env=environment, capture_output=True, text=True)
        assert created.returncode == 0
        container = created.stdout.strip()
        assert re.fullmatch(r'[a-f0-9]{64}', container)
        for _ in range(30):
            if subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'payment_fixture'],
                              capture_output=True).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Temporary PostgreSQL did not become ready')
        environment['PAYMENT_TEST_DATABASE_URL'] = 'postgresql://payment_fixture:' + password + '@127.0.0.1:5432/payment_fixture'
        result = subprocess.run(['docker', 'run', '--rm', '--pull=never', '--network', 'container:' + container,
                                 '--mount', 'type=bind,src=' + str(source) + ',dst=/workspace,readonly',
                                 '-w', '/workspace/packages/payment', '-e', 'PAYMENT_TEST_DATABASE_URL', image,
                                 'node', '--experimental-vm-modules', 'node_modules/jest/bin/jest.js',
                                 '--runInBand', '--cacheDirectory', '/tmp/payment-jest'],
                                env=environment, capture_output=True, text=True, timeout=120)
        # Only aggregate test results are emitted, never the environment or raw failures.
        summary = [line for line in (result.stdout + '\n' + result.stderr).splitlines()
                   if re.match(r'^(Test Suites:|Tests:|Time:|Ran all test suites)', line)]
        return {'valid': result.returncode == 0, 'postgres': '16.15', 'node': '24.13.1',
                'sameDockerClock': True, 'isolatedTemporaryDatabase': True, 'summary': summary}
    finally:
        if container:
            subprocess.run(['docker', 'rm', '--force', container], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Existing Gaegaeting source checkout with installed dependencies')
    args = parser.parse_args()
    try:
        result = verify(args.source.resolve())
    except Exception:
        result = {'valid': False, 'error': 'Payment isolated test failed; sensitive details suppressed'}
    print(json.dumps(result))
    raise SystemExit(0 if result['valid'] else 1)


if __name__ == '__main__':
    main()
