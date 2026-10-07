#!/usr/bin/env python3
"""Guarded one-off Chat DB bootstrap; Doppler is the sole identity/credential source.

Default is read-only. --write creates only the approved Chat role/database/schema ACL.
Reuse vote_database.py's explicit-context CNPG socket/stdin path, never kubectl apply.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from doppler_runtime import Cluster, validate_run, load, require

KEYS = ('CHAT_DATABASE_NAME', 'CHAT_DATABASE_USERNAME', 'CHAT_DATABASE_PASSWORD')
MARKER = 'gaegaeting-dev-chat-gitops'


def validate_identity(values):
    require(set(values) == set(KEYS))
    for key in KEYS[:2]:
        v = values[key]
        require(isinstance(v, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,62}', v))
        require(not v.startswith('pg_') and v not in {'postgres', 'template0', 'template1', 'public'})
    require(values[KEYS[0]] == values[KEYS[1]])  # Existing sameuser TLS HBA, no shared restart.
    require(isinstance(values[KEYS[2]], str) and len(values[KEYS[2]]) >= 32)
    require(not any(c in values[KEYS[2]] for c in '\x00\r\n'))


def validate_hba(rules):
    # Existing CNPG custom rules, in order: scoped identities then sameuser then
    # reject. No broad password/trust fallback or hostname/IP constants added.
    require(isinstance(rules, list) and len(rules) >= 2)
    require(rules[-2:] == ['hostssl sameuser all all scram-sha-256', 'host all all all reject'])
    allowed = {
        'hostssl @/projected/identity/database @/projected/identity/username all scram-sha-256',
        'hostssl @/projected/gaegaeting-dev/account/database @/projected/gaegaeting-dev/account/username all scram-sha-256',
        'hostssl @/projected/gaegaeting-dev/match/database @/projected/gaegaeting-dev/match/username all scram-sha-256',
    }
    require(len(rules[:-2]) == len(set(rules[:-2])) and set(rules[:-2]) <= allowed)


HBA_GUARD = r'''
-- Stop at the first unconditional network reject, in server rule order.
-- Address=all (not a single-family CIDR) and no options are required.
WITH rules AS (SELECT * FROM pg_hba_file_rules), boundary AS (
 SELECT min(rule_number) AS stop FROM rules
 WHERE type='host' AND database=ARRAY['all'] AND user_name=ARRAY['all']
 AND address='all' AND netmask IS NULL AND auth_method='reject'
 AND COALESCE(cardinality(options),0)=0
), reachable AS (
 SELECT r.* FROM rules r, boundary b WHERE r.rule_number < b.stop
)
SELECT NOT EXISTS (SELECT 1 FROM rules WHERE error IS NOT NULL OR rule_number IS NULL OR rule_number<1)
 AND (SELECT count(*)=count(DISTINCT rule_number) FROM rules)
 AND (SELECT stop IS NOT NULL FROM boundary)
 AND EXISTS (
 SELECT 1 FROM reachable WHERE type='hostssl' AND database=ARRAY['sameuser']
 AND user_name=ARRAY['all'] AND address='all' AND netmask IS NULL
 AND auth_method='scram-sha-256' AND COALESCE(cardinality(options),0)=0
 )
 AND NOT EXISTS (
 SELECT 1 FROM reachable WHERE type IS NULL
 OR type NOT IN ('local','host','hostssl','hostnossl','hostgssenc','hostnogssenc')
 OR (type<>'local' AND (
 auth_method IS NULL OR database IS NULL OR cardinality(database)=0
 OR user_name IS NULL OR cardinality(user_name)=0 OR address IS NULL
 OR EXISTS (SELECT 1 FROM unnest(database) n WHERE n IS NULL)
 OR EXISTS (SELECT 1 FROM unnest(user_name) n WHERE n IS NULL)
 ))
 )
 AND NOT EXISTS (
 SELECT 1 FROM reachable WHERE type<>'local' AND auth_method<>'reject'
 -- Physical replication cannot select an ordinary database, and the role is
 -- separately required to be NOREPLICATION/NOSUPERUSER with no memberships.
 AND database IS DISTINCT FROM ARRAY['replication']
 AND NOT (type='hostssl' AND database=ARRAY['sameuser'] AND user_name=ARRAY['all']
          AND address='all' AND netmask IS NULL AND auth_method='scram-sha-256'
          AND COALESCE(cardinality(options),0)=0)
 AND (user_name && ARRAY['all',:'username'] OR EXISTS (
 SELECT 1 FROM unnest(user_name) n WHERE n !~ '^[A-Za-z0-9_][A-Za-z0-9_.-]*$'
 ))
 ) AS hba_safe
'''


GUARDS = r'''
\set ON_ERROR_STOP on
\getenv dbname TARGET_DATABASE
\getenv username TARGET_USERNAME
\getenv password TARGET_PASSWORD
SET log_statement = 'none';
SET log_duration = off;
SET log_min_duration_statement = -1;
SET log_min_duration_sample = -1;
SET log_transaction_sample_rate = 0;
SET log_min_error_statement = 'panic';
SET lock_timeout = '5s';
SET statement_timeout = '30s';
BEGIN READ ONLY;
SELECT COALESCE(current_setting('pgaudit.log',true),'none') IN ('none','') AS audit_safe \gset
\if :audit_safe
\else
SELECT 1/0;
\endif
SELECT pg_advisory_lock(hashtextextended('gaegaeting-dev-chat-bootstrap',0));
SELECT NOT EXISTS (
 SELECT 1 FROM pg_roles WHERE rolname=:'username' AND
 (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
 OR shobj_description(oid,'pg_authid') IS DISTINCT FROM 'gaegaeting-dev-chat-gitops')
) AND NOT EXISTS (
 SELECT 1 FROM pg_database d WHERE datname=:'dbname' AND
 (pg_get_userbyid(datdba)<>:'username' OR shobj_description(oid,'pg_database') IS DISTINCT FROM 'gaegaeting-dev-chat-gitops')
) AND NOT EXISTS (
 SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member OR r.oid=m.roleid WHERE r.rolname=:'username'
) AND NOT EXISTS (
 SELECT 1 FROM pg_database d WHERE datname<>:'dbname' AND pg_get_userbyid(datdba)=:'username'
) AS safe \gset
\if :safe
\else
SELECT 1/0;
\endif
''' + HBA_GUARD + r''' \gset
\if :hba_safe
\else
SELECT 1/0;
\endif
-- PUBLIC ACL alone does not bypass fail-closed sameuser HBA. Never revoke
-- another DB's ACL. Reject direct grants to the candidate role instead.
SELECT NOT EXISTS (
 SELECT 1 FROM pg_database d JOIN pg_roles r ON r.rolname=:'username',
 LATERAL aclexplode(COALESCE(d.datacl,acldefault('d',d.datdba))) a
 WHERE d.datname<>:'dbname' AND a.grantee=r.oid
) AS isolated \gset
\if :isolated
\else
SELECT 1/0;
\endif
COMMIT;
'''
WRITE = r'''
BEGIN;
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', :'username', :'password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'username') \gexec
SELECT format('COMMENT ON ROLE %I IS %L', :'username','gaegaeting-dev-chat-gitops') \gexec
COMMIT;
-- CREATE DATABASE cannot run in a transaction. On failure retain marked role;
-- repair prerequisites then rerun the same identity, never rotate or drop it.
SELECT format('CREATE DATABASE %I OWNER %I', :'dbname', :'username') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname=:'dbname') \gexec
SELECT format('COMMENT ON DATABASE %I IS %L', :'dbname','gaegaeting-dev-chat-gitops') \gexec
BEGIN;
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'dbname') \gexec
SELECT format('GRANT CONNECT,TEMPORARY ON DATABASE %I TO %I', :'dbname', :'username') \gexec
COMMIT;
\connect :dbname
SET log_statement = 'none';
SET log_duration = off;
SET log_min_duration_statement = -1;
SET log_min_duration_sample = -1;
SET log_transaction_sample_rate = 0;
SET log_min_error_statement = 'panic';
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE,CREATE ON SCHEMA public TO %I', :'username') \gexec
COMMIT;
'''


def shell_input(values, write=False):
    validate_identity(values)
    lines = ['set -eu', 'unset PGPASSWORD PGHOST PGHOSTADDR PGPORT PGUSER PGDATABASE PGSERVICE PGSERVICEFILE PGOPTIONS',
             'test -S /controller/run/.s.PGSQL.5432']
    for target, source in zip(('TARGET_DATABASE', 'TARGET_USERNAME', 'TARGET_PASSWORD'), KEYS):
        lines.append('export ' + target + '=' + shlex.quote(values[source]))
    sql = GUARDS + (WRITE if write else '')
    lines.append("psql -X -q -h /controller/run -p 5432 -U postgres -d postgres <<'CHAT_SQL' >/dev/null 2>&1\n" + sql + '\nCHAT_SQL')
    return '\n'.join(lines) + '\n'


def verify_access(cluster, primary, values):
    # Read database names only into operator memory; never output them.
    sql = "SET log_statement='none'; SET log_duration=off; SET log_min_duration_statement=-1; SET log_min_error_statement='panic'; SELECT json_agg(datname) FROM pg_database WHERE datallowconn;"
    r = subprocess.run(cluster.prefix+['-n','databases','exec','-i',primary,'-c','postgres','--','env','-u','PGPASSWORD','-u','PGHOST','-u','PGHOSTADDR','-u','PGPORT','-u','PGUSER','-u','PGDATABASE','-u','PGSERVICE','-u','PGSERVICEFILE','-u','PGOPTIONS','psql','-X','-qAt','-h','/controller/run','-p','5432','-U','postgres','-d','postgres'],input=sql,capture_output=True,text=True,timeout=40)
    require(r.returncode == 0)
    databases = json.loads(r.stdout.strip())
    others = [d for d in databases if d != values['CHAT_DATABASE_NAME']]
    require(others and len(others) < 100)
    pods = cluster.execute(['-n','gaegaeting-dev','get','pods','-l','app.kubernetes.io/name=account','-o','json'])['items']
    pods = [p for p in pods if not p['metadata'].get('deletionTimestamp') and any(c.get('ready') and c['name']=='account' for c in p.get('status',{}).get('containerStatuses',[]))]
    require(len(pods) == 1)
    payload = {'database':values[KEYS[0]], 'username':values[KEYS[1]], 'password':values[KEYS[2]], 'otherDatabases':others}
    code = 'const input = '+json.dumps(payload)+';\n'+r"""
import assert from 'node:assert/strict';
import {Client} from 'pg';
import {readDatabaseConnectionOptions} from '@core/database';
assert.equal(process.env.NODE_ENV,'development');
assert.equal(process.env.AUTH_TENANT_CODE,'gaegaeting-dev');
assert.equal(process.env.AUTH_ISSUER,'https://auth.rvkang.app/t/gaegaeting-dev/oidc');
assert.equal(process.env.DATABASE_SSL_MODE,'verify-full');
assert.equal(process.env.NODE_EXTRA_CA_CERTS,'/etc/database/ca.crt');
const map={DATABASE_NAME:input.database,DATABASE_USERNAME:input.username,DATABASE_PASSWORD:input.password};
const config=readDatabaseConnectionOptions({get:(k,f)=>map[k]??process.env[k]??f});
assert(config.ssl && config.ssl.rejectUnauthorized !== false);
const c=new Client(config);
try {
 await c.connect();
 const r=await c.query('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()');assert.equal(r.rows[0].ssl,true);
 await c.query('BEGIN READ ONLY');await c.query('SELECT 1');await c.query('ROLLBACK');
}finally{await c.end();}
let denied=0;
for(const database of input.otherDatabases){
 const target=new Client({...config,database,connectionTimeoutMillis:5000});
 try{await target.connect();throw Error('UNEXPECTED_CROSS_DATABASE_ACCESS');}
 catch(e){if(['28000','42501'].includes(e.code))denied++;else throw Error('ISOLATION_CHECK_FAILED');}
 finally{await target.end().catch(()=>{});}
}
assert.equal(denied,input.otherDatabases.length);
console.log(JSON.stringify({ownDatabaseTlsVerified:true,otherDatabasesTested:denied,allOtherDatabaseLoginsDenied:true}));
"""
    r = subprocess.run(cluster.prefix+['-n','gaegaeting-dev','exec','-i',pods[0]['metadata']['name'],'-c','account','--','node','--input-type=module'],input=code,capture_output=True,text=True,timeout=120)
    require(r.returncode == 0)
    result=json.loads(r.stdout)
    require(result['ownDatabaseTlsVerified'] and result['allOtherDatabaseLoginsDenied'])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-config', type=Path, required=True)
    action = p.add_mutually_exclusive_group()
    action.add_argument('--write', action='store_true')
    action.add_argument('--verify-access', action='store_true')
    args = p.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        run = validate_run(load('gitops_validate').read_json(args.run_config))
        source = subprocess.run(['git','show',run['expected_revision']+':scripts/gaegaeting_chat_database.py'],cwd=root,capture_output=True,text=True,check=True).stdout
        require(source == Path(__file__).read_text())
        cluster = Cluster(run)
        pg = cluster.get('cluster.postgresql.cnpg.io','shared-postgres','databases')
        require(pg['status']['readyInstances'] == pg['spec']['instances'] == 1)
        validate_hba(pg['spec']['postgresql']['pg_hba'])
        pod = pg['status']['currentPrimary']
        actual = cluster.get('pod',pod,'databases')
        require(actual['metadata']['labels']['cnpg.io/cluster']=='shared-postgres')
        require(any(c.get('ready') for c in actual.get('status',{}).get('containerStatuses',[]) if c['name']=='postgres'))
        values = {}
        for key in KEYS:
            r = subprocess.run(['doppler','secrets','get',key,'--project','gaegaeting','--config','stg','--plain'],capture_output=True,text=True,timeout=40,check=True)
            values[key] = r.stdout.rstrip('\n')
        validate_identity(values)
        if args.verify_access:
            print(json.dumps(verify_access(cluster,pod,values)))
            return 0
        r = subprocess.run(cluster.prefix+['-n','databases','exec','-i',pod,'-c','postgres','--','sh','-s'],input=shell_input(values,args.write),capture_output=True,text=True,timeout=120)
        require(r.returncode==0)
        print(json.dumps({'validated':True,'writeRequested':args.write,'credentialsRotated':False,'valuesDisplayed':False}))
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        print(json.dumps({'validated':False,'writeRequested':args.write,'partialBootstrapPossible':args.write,'detailsSuppressed':True}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
