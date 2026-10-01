#!/usr/bin/env python3
"""Prepare only the Vote-owned logical database on an existing PostgreSQL Pod."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
from doppler_runtime import Cluster, validate_run, load, require

SQL = r'''
\set ON_ERROR_STOP on
\getenv dbname TARGET_DATABASE
\getenv username TARGET_USERNAME
\getenv password TARGET_PASSWORD
SELECT pg_advisory_lock(hashtextextended('vote-database-provision',0));
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'username' AND
 (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR
 shobj_description(oid,'pg_authid') IS DISTINCT FROM 'vote-gitops')) AS safe \gset
\if :safe
\else
SELECT 1/0;
\endif
SELECT NOT EXISTS (SELECT 1 FROM pg_database WHERE datname=:'dbname' AND pg_get_userbyid(datdba)<>:'username') AS owned \gset
\if :owned
\else
SELECT 1/0;
\endif
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', :'username', :'password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'username') \gexec
SELECT format('COMMENT ON ROLE %I IS %L', :'username','vote-gitops') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'dbname', :'username') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname=:'dbname') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'dbname') \gexec
SELECT format('GRANT CONNECT,TEMPORARY ON DATABASE %I TO %I', :'dbname', :'username') \gexec
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-config', type=Path, required=True)
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        gitops = load('gitops_validate')
        run = validate_run(gitops.read_json(args.run_config))
        source = subprocess.run(['git','show',run['expected_revision']+':scripts/vote_database.py'],cwd=root,capture_output=True,text=True,check=True).stdout
        require(source == Path(__file__).read_text())
        cluster = Cluster(run)
        pg = cluster.get('cluster.postgresql.cnpg.io','shared-postgres','databases')
        require(pg['status']['readyInstances'] == pg['spec']['instances'] == 1)
        require('hostssl sameuser all all scram-sha-256' in pg['spec']['postgresql']['pg_hba'])
        pod = pg['status']['currentPrimary']
        require(pod and cluster.get('pod',pod,'databases')['metadata']['labels']['cnpg.io/cluster']=='shared-postgres')
        result = subprocess.run(['doppler','secrets','download','--project','vote','--config','prd','--no-file','--format','json'],capture_output=True,text=True,timeout=40,check=True)
        values = json.loads(result.stdout)
        require(values['DATABASE_NAME'] == values['DATABASE_USER'])
        require(all(values[k] for k in ['DATABASE_NAME','DATABASE_USER','DATABASE_PASSWORD']))
        shell = '\n'.join('export '+key+'='+shlex.quote(values[source]) for key,source in [('TARGET_DATABASE','DATABASE_NAME'),('TARGET_USERNAME','DATABASE_USER'),('TARGET_PASSWORD','DATABASE_PASSWORD')])
        shell += "\npsql -X -q -d postgres <<'VOTE_SQL' >/dev/null 2>&1\n"+SQL+"\nVOTE_SQL\n"
        result = subprocess.run(cluster.prefix+['-n','databases','exec','-i',pod,'-c','postgres','--','sh','-s'],input=shell,capture_output=True,text=True,timeout=60)
        require(result.returncode==0)
        print('Vote-owned logical database and restricted role prepared; existing databases unchanged; values suppressed.')
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        print('Vote logical database preparation failed; credentials and SQL output suppressed.')
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
