"""Local regression checks plus exact PostgreSQL HBA-query fixtures.

Emit read-only synthetic SQL for root's disposable PostgreSQL 18.4:
  python scripts/tests/test_gaegaeting_chat_db_guards.py --sql-output /tmp/chat-hba-guards.sql
No live connection, credential or data is used by this test module.
"""
import argparse
import ast
import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import gaegaeting_chat_database as db

BASE = '80c4ddcd0d61cea728bec401d91fbab09d321ded'


def rule(number, **changes):
    value = dict(rule_number=number, type='hostssl', database=['sameuser'],
                 user_name=['all'], address='all', netmask=None,
                 auth_method='scram-sha-256', options=None, error=None)
    value.update(changes)
    return value


def cases():
    same = rule(9)
    stop = rule(10, type='host', database=['all'], auth_method='reject')
    tail = rule(11, type='host', database=['all'])
    initial = [rule(1, type='local', database=['all'], user_name=['postgres'],
                    address=None, auth_method='peer'),
               rule(2, database=['replication'], user_name=['all'], auth_method='cert'),
               rule(8, database=['fixture_other'], user_name=['fixture_other']), same, stop]
    def changed(index, **changes):
        rows = copy.deepcopy(initial)
        rows[index].update(changes)
        return rows
    return [
        ('scoped_sameuser_reject', initial, True),
        ('unreachable_cnpg_tail', initial + [tail], True),
        ('physical_row_order_irrelevant', list(reversed(initial + [tail])), True),
        ('broad_before_reject', initial + [rule(7, database=['all'])], False),
        ('trust_before_reject', initial + [rule(7, type='host', database=['all'], auth_method='trust')], False),
        ('candidate_collision', initial + [rule(7, database=['fixture_other'], user_name=['fixture_candidate'])], False),
        ('group_before_reject', initial + [rule(7, database=['all'], user_name=['+fixture_group'])], False),
        ('regex_before_reject', initial + [rule(7, database=['all'], user_name=['/fixture_.*'])], False),
        ('unexpanded_file_before_reject', initial + [rule(7, database=['all'], user_name=['@fixture_file'])], False),
        ('unknown_user_syntax', initial + [rule(7, database=['all'], user_name=['?unknown'])], False),
        ('unreachable_group_tail', initial + [rule(11, database=['all'], user_name=['+fixture_group'])], True),
        ('parse_error_even_after_reject', initial + [rule(None, error='synthetic parse error')], False),
        ('missing_reject', initial[:-1], False),
        ('missing_sameuser', initial[:3] + [stop, tail], False),
        ('sameuser_after_reject', initial[:3] + [stop, rule(12)], False),
        ('reject_ipv4_only', changed(-1, address='0.0.0.0', netmask='0.0.0.0') + [tail], False),
        ('reject_ssl_only', changed(-1, type='hostssl') + [tail], False),
        ('reject_options', changed(-1, options=['unknown=true']) + [tail], False),
        ('reject_not_all_users', changed(-1, user_name=['fixture_other']) + [tail], False),
        ('sameuser_narrow_address', changed(-2, address='samehost'), False),
        ('sameuser_trust', changed(-2, auth_method='trust'), False),
        ('sameuser_options', changed(-2, options=['unknown=true']), False),
        ('gss_broad_before_reject', initial + [rule(7, type='hostgssenc', database=['all'])], False),
        ('unknown_type_before_reject', initial + [rule(7, type='futurehost')], False),
        ('null_username_before_reject', initial + [rule(7, user_name=[None])], False),
        ('empty_username_before_reject', initial + [rule(7, user_name=[])], False),
        ('duplicate_rule_numbers', initial + [rule(9)], False),
        ('missing_rule_number', initial + [rule(None)], False),
    ]


def fixture_sql():
    lines = ['\\set ON_ERROR_STOP on', 'BEGIN READ ONLY;']
    for name, rows, expected in cases():
        payload = json.dumps(rows).replace("'", "''")
        fixture = """WITH fixture_rules AS (
 SELECT * FROM jsonb_to_recordset('%s'::jsonb) AS f(
 rule_number integer, type text, database text[], user_name text[],
 address text, netmask text, auth_method text, options text[], error text)
), rules AS""" % payload
        query = db.HBA_GUARD.replace('WITH rules AS', fixture, 1)
        query = query.replace('pg_hba_file_rules', 'fixture_rules').replace(":'username'", "'fixture_candidate'")
        lines += ['-- ' + name, 'SELECT hba_safe IS ' + str(expected).upper() +
                  ' AS passed FROM (' + query + ') result \\gset',
                  '\\if :passed', '\\else', 'SELECT 1/0;', '\\endif']
    lines += ['ROLLBACK;', "SELECT 'hba_fixture_cases_passed=" + str(len(cases())) + "';"]
    return '\n'.join(lines) + '\n'


class GuardRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        baseline = subprocess.run(['git','show',BASE+':scripts/gaegaeting_chat_database.py'],
                                  cwd=ROOT, capture_output=True, text=True, check=True).stdout
        cls.old = {}
        for item in ast.parse(baseline).body:
            if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
                cls.old[item.targets[0].id] = ast.literal_eval(item.value)

    def test_collision_membership_and_acl_guards_unchanged(self):
        before = self.old['GUARDS'].split('-- Effective server rules')[0]
        self.assertTrue(db.GUARDS.startswith(before))
        self.assertEqual(db.GUARDS.split('-- PUBLIC ACL')[1], self.old['GUARDS'].split('-- PUBLIC ACL')[1])
        self.assertEqual(db.WRITE, self.old['WRITE'])

    def test_socket_and_no_ambient_connection(self):
        values = dict(zip(db.KEYS, ['fixture_candidate', 'fixture_candidate', "x'" * 20]))
        script = db.shell_input(values)
        self.assertIn('test -S /controller/run/.s.PGSQL.5432', script)
        self.assertIn('psql -X -q -h /controller/run -p 5432 -U postgres -d postgres', script)
        self.assertIn('unset PGPASSWORD PGHOST PGHOSTADDR PGPORT', script)
        self.assertNotIn('CREATE ROLE', script)
        self.assertLess(script.index("SET log_statement = 'none'"), script.index('BEGIN READ ONLY'))
        exports = [line for line in script.splitlines() if line.startswith('export TARGET_PASSWORD=')]
        self.assertEqual(shlex.split(exports[0])[1], 'TARGET_PASSWORD=' + values[db.KEYS[2]])

    def test_identity_collision_boundaries(self):
        for name, user, password in [('fixture_one','fixture_two','x'*32),
                                     ('postgres','postgres','x'*32),
                                     ('pg_test','pg_test','x'*32),
                                     ('fixture;sql','fixture;sql','x'*32),
                                     ('fixture','fixture','short')]:
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    db.validate_identity(dict(zip(db.KEYS,[name,user,password])))

    def test_spec_order_still_strict(self):
        good = ['hostssl sameuser all all scram-sha-256','host all all all reject']
        db.validate_hba(good)
        for bad in [good[::-1], ['host all all all trust']+good, good+['host all all all trust']]:
            with self.assertRaises(ValueError):
                db.validate_hba(bad)

    def test_readonly_database_listing_has_explicit_socket(self):
        import inspect
        source = inspect.getsource(db.verify_access)
        self.assertIn("'-h','/controller/run','-p','5432'", source)
        self.assertIn("'-u','PGHOSTADDR'", source)
        self.assertIn("'-u','PGSERVICE'", source)

    def test_fixture_export_is_readonly_and_uses_production_query(self):
        sql = fixture_sql()
        self.assertEqual(len(cases()), 28)
        self.assertEqual(len({name for name, _, _ in cases()}), 28)
        self.assertEqual(sql.count(' AS passed FROM ('), 28)
        self.assertEqual(sql.count('rule_number < b.stop'), 28)
        self.assertEqual(sql.count('SELECT 1/0;'), 28)
        self.assertNotIn('CREATE ', sql)
        self.assertNotIn('TARGET_PASSWORD', sql)
        self.assertTrue(sql.endswith("SELECT 'hba_fixture_cases_passed=28';\n"))


if __name__ == '__main__':
    if '--sql-output' in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--sql-output', type=Path, required=True)
        args = parser.parse_args()
        args.sql_output.write_text(fixture_sql())
        print(json.dumps({'syntheticSqlWritten': True, 'cases': len(cases()), 'sqlExecuted': False}))
    else:
        unittest.main()
