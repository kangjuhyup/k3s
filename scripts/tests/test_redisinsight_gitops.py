"""The shared Redis browser cannot bypass authentication or write application data."""
import unittest
import yaml
from test_argocd_gitops import ROOT, layout


class RedisInsightTests(unittest.TestCase):
    def test_browser_uses_only_read_credentials_and_cannot_manage_connections(self):
        doc = yaml.safe_load((ROOT / 'gitops/apps/redisinsight/deployment.yaml').read_text())
        pod = doc['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        ui = next(c for c in pod['containers'] if c['name'] == 'redisinsight')
        env = {e['name']: e for e in ui['env']}
        self.assertEqual(env['RI_APP_HOST']['value'], '127.0.0.1')
        self.assertEqual(env['RI_DATABASE_MANAGEMENT']['value'], 'false')
        self.assertEqual(env['RI_REDIS_TLS']['value'], 'true')
        self.assertEqual(env['RI_REDIS_PASSWORD']['valueFrom']['secretKeyRef']['name'], 'redisinsight-redis-credentials')
        self.assertNotIn('REDIS_ADMIN_PASSWORD', str(pod))
        self.assertNotIn('CA_KEY', str(pod))

    def test_every_proxy_request_requires_an_access_jwt_for_this_app(self):
        doc = yaml.safe_load((ROOT / 'gitops/apps/redisinsight/access-proxy.yaml').read_text())
        config = yaml.safe_load(doc['data']['envoy.yaml'])
        hcm = config['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
        jwt = hcm['http_filters'][0]['typed_config']
        self.assertEqual(jwt['rules'], [{'match': {'prefix': '/'}, 'requires': {'provider_name': 'cloudflare'}}])
        provider = jwt['providers']['cloudflare']
        self.assertEqual(provider['audiences'], ['@ACCESS_AUD@'])
        self.assertEqual(provider['from_headers'], [{'name': 'Cf-Access-Jwt-Assertion'}])
        self.assertNotIn('allow_missing', str(jwt))
        self.assertTrue(provider['remote_jwks']['http_uri']['uri'].startswith('https://'))

    def test_read_account_cannot_run_scripts_or_write_keys(self):
        start = layout('redis').START
        readonly = next(line for line in start.splitlines() if '%%R~*' in line)
        self.assertIn('-@all +@read -@dangerous -@scripting', readonly)
        self.assertNotIn('+@write', readonly)
        self.assertNotIn('+eval', readonly)
        self.assertIn('/readonly/username', start)
        service = yaml.safe_load((ROOT / 'gitops/apps/redisinsight/service.yaml').read_text())
        self.assertEqual(service['spec']['ports'][0]['targetPort'], 'access-http')
