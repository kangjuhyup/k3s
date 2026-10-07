import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import gaegaeting_chat_database as db
import gaegaeting_chat_validate as contract

class IdentityGuards(unittest.TestCase):
    def setUp(self):self.values=dict(zip(db.KEYS,['synthetic_chat_guard','synthetic_chat_guard',"synthetic-only-passphrase-0123456789'\\end"]))
    def test_hba_catch_all_or_wrong_order_denied(self):
        valid=['hostssl sameuser all all scram-sha-256','host all all all reject']
        db.validate_hba(valid)
        for rules in [valid[::-1], ['hostssl all all all scram-sha-256']+valid, valid+['host all all all trust']]:
            with self.subTest(),self.assertRaises(ValueError):db.validate_hba(rules)
    def test_public_metadata_is_not_a_global_revoke(self):
        self.assertNotIn('a.grantee=0',db.GUARDS)
        self.assertIn('a.grantee=r.oid',db.GUARDS)
        self.assertIn('pg_hba_file_rules',db.GUARDS)
        self.assertNotIn('REVOKE CONNECT ON DATABASE postgres',db.WRITE)
    def test_sameuser_required(self):
        self.values[db.KEYS[1]]='different_synthetic_role'
        with self.assertRaises(ValueError):db.validate_identity(self.values)
    def test_reserved_and_injection_denied(self):
        for value in ['postgres','pg_test','bad;select','bad\nvalue','bad-name','UPPER']:
            values={**self.values,db.KEYS[0]:value,db.KEYS[1]:value}
            with self.subTest(value=value),self.assertRaises(ValueError):db.validate_identity(values)
    def test_short_or_multiline_password_denied(self):
        for value in ['short','x'*32+'\n','x'*32+'\x00']:
            with self.subTest(),self.assertRaises(ValueError):db.validate_identity({**self.values,db.KEYS[2]:value})
    def test_shell_preserves_special_password_without_execution(self):
        # Local shell parsing only, never contacts Doppler or a DB.
        import shlex
        s=db.shell_input(self.values)
        assignment=next(line for line in s.splitlines() if line.startswith('export TARGET_PASSWORD='))
        parsed=shlex.split(assignment)[1].split('=',1)[1]
        self.assertEqual(parsed,self.values[db.KEYS[2]])
    def test_tls_probe_javascript_syntax(self):
        import os,json
        from unittest.mock import patch,Mock
        cluster=Mock();cluster.prefix=['kubectl']
        cluster.execute.return_value={'items':[{'metadata':{'name':'synthetic-ready-account'},'status':{'containerStatuses':[{'name':'account','ready':True}]}}]}
        outputs=[subprocess.CompletedProcess([],0,json.dumps(['synthetic_chat_guard','synthetic_other']),''),subprocess.CompletedProcess([],0,json.dumps({'ownDatabaseTlsVerified':True,'allOtherDatabaseLoginsDenied':True,'otherDatabasesTested':1}),'')]
        with patch.object(db.subprocess,'run',side_effect=outputs) as run:
            db.verify_access(cluster,'synthetic-primary',self.values)
            code=run.call_args_list[1].kwargs['input']
        result=subprocess.run([os.environ['CHAT_TEST_NODE'],'--check','--input-type=module'],input=code,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,'Generated TLS verifier must parse; output suppressed')
    def test_default_has_no_ddl_and_sql_logs_suppressed_before_password(self):
        s=db.shell_input(self.values)
        self.assertNotIn('CREATE ROLE',s);self.assertNotIn('CREATE DATABASE',s)
        self.assertIn('BEGIN READ ONLY;',s)
        w=db.shell_input(self.values,True)
        for setting in ["SET log_statement = 'none'",'SET log_duration = off','SET log_min_duration_statement = -1',"SET log_min_error_statement = 'panic'"]:
            self.assertLess(w.index(setting),w.index('CREATE ROLE'))
        self.assertNotIn('ALTER ROLE',w)
        self.assertIn('NOBYPASSRLS',w)
        self.assertIn(db.MARKER,w)

class RouteNegativeCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json,os
        kubectl=os.environ['CHAT_TEST_KUBECTL']
        rendered=subprocess.run([kubectl,'kustomize',str(ROOT/'gitops/clusters/oci-a1/gaegaeting-dev')],capture_output=True,text=True,check=True).stdout
        cls.resources=list(yaml.safe_load_all(rendered));cls.release=json.loads((ROOT/'gitops/clusters/oci-a1/gaegaeting-dev/release-images.json').read_text())
    def test_rendered_contract(self):contract.verify(self.resources,self.release)
    def test_broad_ws_route_rejected(self):
        r=copy.deepcopy(self.resources);cm=next(x for x in r if x['kind']=='ConfigMap' and x['metadata']['name']=='edge-proxy-start')
        cm['data']['start.sh']=cm['data']['start.sh'].replace('path: /gateway/graphql','prefix: /',1)
        with self.assertRaises(AssertionError):contract.verify(r,self.release)
    def test_wrong_migration_digest_rejected(self):
        r=copy.deepcopy(self.resources);j=next(x for x in r if x['kind']=='Job' and x['metadata']['name'].startswith('chat-migration-'));j['spec']['template']['spec']['containers'][0]['image']='invalid'
        with self.assertRaises(AssertionError):contract.verify(r,self.release)
    def test_missing_ws_introspection_secret_rejected(self):
        r=copy.deepcopy(self.resources);s=next(x for x in r if x['kind']=='DopplerSecret' and x['metadata']['name']=='gaegaeting-dev-gateway-runtime');s['spec']['secrets'].remove('OIDC_INTROSPECTION_CLIENT_SECRET')
        with self.assertRaises(AssertionError):contract.verify(r,self.release)
if __name__=='__main__':unittest.main()
