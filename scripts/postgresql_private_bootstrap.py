#!/usr/bin/env python3
"""Explicitly prepare private bootstrap SQL in Doppler; never writes values to Git."""
import argparse
import json
import re
import subprocess


def statements(database, user, password):
    for value in (database, user):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value) or value.startswith("pg_") or value in {"postgres", "template0", "template1"}:
            raise ValueError("Invalid identifier")
    if not password or "\x00" in password:
        raise ValueError("Invalid password")
    quoted_password = "E'" + password.replace('\\', '\\\\').replace("'", "''") + "'"
    return {
        "DB_INIT_ROLE_SQL": f'CREATE ROLE "{user}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {quoted_password}',
        "DB_INIT_DATABASE_SQL": f'CREATE DATABASE "{database}" OWNER "{user}"',
        "DB_INIT_ACL_SQL": f'REVOKE ALL ON DATABASE "{database}" FROM PUBLIC; GRANT CONNECT, TEMPORARY ON DATABASE "{database}" TO "{user}"; REVOKE CONNECT ON DATABASE postgres FROM PUBLIC; REVOKE CONNECT ON DATABASE template1 FROM PUBLIC',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    flags = ['--project', args.project, '--config', args.config, '--no-check-version']
    try:
        values = [subprocess.run(['doppler', 'secrets', 'get', k, '--plain'] + flags,
                  capture_output=True, text=True, check=True).stdout.rstrip('\n') for k in ['DB_NAME', 'DB_USER', 'DB_PASSWORD']]
        sql = statements(*values)
        if args.write:
            for key, statement in sql.items():
                subprocess.run(['doppler', 'secrets', 'set', key, '--no-interactive'] + flags,
                               input=statement, capture_output=True, text=True, check=True)
        print(json.dumps({'validated': True, 'written': args.write, 'values_displayed': False}))
    except (ValueError, subprocess.SubprocessError):
        print('Private bootstrap preparation failed; values are not displayed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
