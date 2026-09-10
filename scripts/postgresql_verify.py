#!/usr/bin/env python3
"""Verify app SQL access, verified TLS and isolation without displaying credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import re

from doppler_runtime import Cluster, validate_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        cluster = Cluster(validate_run(json.loads(args.run_config.read_text())))
        db = cluster.get("clusters.postgresql.cnpg.io", "shared-postgres", "databases")
        assert db["status"]["readyInstances"] == 1
        pod = db["status"]["currentPrimary"]
        secret = cluster.get("secret", "auth-db-credentials", "databases")
        identity = cluster.get("secret", "auth-db-private", "databases")
        database_name = base64.b64decode(identity["data"]["database"]).decode()
        user = base64.b64decode(secret["data"]["username"]).decode()
        password = base64.b64decode(secret["data"]["password"]).decode()
        assert user == base64.b64decode(identity["data"]["username"]).decode() and password and "\n" not in password
        assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", v) for v in [database_name, user])

        def query(database, sslmode, sql):
            # Password is stdin only, not argv or shared environment. No shell expansion of values.
            command = ['sh', '-c', 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql "$@"', 'sh',
                       '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-At',
                       f'host={db["status"]["writeService"]}.databases.svc.cluster.local port=5432 dbname={database} user={user} sslmode={sslmode} sslrootcert=/controller/certificates/server-ca.crt',
                       '-c', sql]
            return subprocess.run(cluster.prefix + ['-n', 'databases', 'exec', '-i', pod, '-c', 'postgres', '--'] + command,
                                  input=password + '\n', text=True, capture_output=True, timeout=30,
                                  env=cluster.environment)

        result = query(database_name, 'verify-full',
            "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid(); "
            "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls) FROM pg_roles WHERE rolname=current_user; "
            "BEGIN; CREATE TEMP TABLE cnpg_access_check (id integer); INSERT INTO cnpg_access_check VALUES (1); "
            "SELECT count(*)=1 FROM cnpg_access_check; ROLLBACK;")
        assert result.returncode == 0 and result.stdout.splitlines().count('t') == 3
        for database, mode in [('postgres', 'verify-full'), (database_name, 'disable')]:
            denied = query(database, mode, 'SELECT 1')
            assert denied.returncode != 0 and 'pg_hba.conf rejects connection' in denied.stderr
        print(json.dumps({"verified_tls": True, "sql_transaction": True, "unprivileged_role": True,
                          "other_database_denied": True, "plaintext_denied": True, "values_displayed": False}))
        return 0
    except (AssertionError, ValueError, KeyError, OSError, subprocess.SubprocessError):
        print('PostgreSQL verification failed; inspect status safely. Values are not displayed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
