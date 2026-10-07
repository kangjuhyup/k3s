#!/usr/bin/env python3
"""Chat render/security contract checks; no API calls or mutations."""
import argparse,json,re,subprocess
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def verify(resources, release):
    def one(kind,name):
        rows=[r for r in resources if r['kind']==kind and r['metadata']['name']==name]
        assert len(rows)==1,(kind,name)
        return rows[0]
    chat=release['devChat'];image=chat['migrationImage']
    dep=one('Deployment','chat');job=one('Job',chat['migrationJob'])
    assert dep['spec']['replicas']==1 and job['spec']['suspend'] is False
    assert job['spec']['backoffLimit']==0
    for w in [dep,job]:
        p=w['spec']['template']['spec'];c=p['containers'][0]
        assert c['name']=='chat' and c['image']==image and re.search(r'@sha256:[a-f0-9]{64}$',image)
        assert p['automountServiceAccountToken'] is False and p['securityContext']['runAsUser']==1000
        assert c['securityContext']['capabilities']['drop']==['ALL'] and c['securityContext']['allowPrivilegeEscalation'] is False
        assert any(e['name']=='NODE_EXTRA_CA_CERTS' and e['value']=='/etc/database/ca.crt' for e in c['env'])
    c=dep['spec']['template']['spec']['containers'][0]
    assert c['readinessProbe']['httpGet']['path']=='/chat/health/ready'
    assert c['livenessProbe']['httpGet']['path']=='/chat/health'
    assert job['spec']['template']['spec']['containers'][0]['command']==['node','dist/src/migrations/migrate.js']
    assert one('Service','chat')['spec']['ports'][0]['port']==2804
    secret=one('DopplerSecret','gaegaeting-dev-chat-runtime')['spec']
    assert (secret['project'],secret['config'])==('gaegaeting','stg')
    for k in ['NAME','USERNAME','PASSWORD']:assert secret['processors']['CHAT_DATABASE_'+k]['asName']=='DATABASE_'+k
    assert set(secret['secrets'])==set(secret['processors'])
    for k in ['MATCH_SERVICE_HOST','CHAT_KAFKA_ENABLED','CHAT_KAFKA_GROUP_ID','KAFKA_TOPIC_PREFIX','DATABASE_SSL_MODE']:assert k in secret['secrets']
    gateway=one('DopplerSecret','gaegaeting-dev-gateway-runtime')['spec']
    for k in ['CHAT_SERVICE_URL','CHAT_WS_ALLOWED_ORIGINS','OIDC_ISSUER','OIDC_INTROSPECTION_CLIENT_ID','OIDC_INTROSPECTION_CLIENT_SECRET']:assert k in gateway['secrets']
    policy=one('NetworkPolicy','chat-ingress')['spec']['ingress'];assert len(policy)==1
    assert policy[0]['ports']==[{'protocol':'TCP','port':2804}]
    assert len(policy[0]['from'])==1 and policy[0]['from'][0]['podSelector']['matchLabels']['app.kubernetes.io/name']=='gateway'
    assert policy[0]['from'][0]['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name']=='gaegaeting-dev'
    match=one('NetworkPolicy','match-ingress')['spec']['ingress'][0]['from']
    assert {p['podSelector']['matchLabels']['app.kubernetes.io/name'] for p in match}=={'gateway','chat'}
    shell=one('ConfigMap','edge-proxy-start')['data']['start.sh']
    envoy=yaml.safe_load(shell.split('<<EOF\n',1)[1].rsplit('EOF\n',1)[0]);h=envoy['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config'];routes=h['route_config']['virtual_hosts'][0]['routes']
    ws,http=routes[:2]
    assert ws['match']=={'path':'/gateway/graphql','headers':[{'name':':method','string_match':{'exact':'GET'}},{'name':'upgrade','string_match':{'exact':'websocket','ignore_case':True}}]}
    assert ws['route']['upgrade_configs']==[{'upgrade_type':'websocket','enabled':True}]
    assert ws['route']['cluster']=='gateway' and ws['route']['timeout']=='0s'
    assert ws['typed_per_filter_config']['envoy.filters.http.ext_authz']['disabled'] is True
    assert h['upgrade_configs']==[{'upgrade_type':'websocket','enabled':False}]
    assert http['match']=={'path':'/gateway/graphql'} and 'typed_per_filter_config' not in http
    assert not any(r['match'].get('path','').startswith('/chat') for r in routes)
    assert h['http_filters'][1]['typed_config']['failure_mode_allow'] is False
    assert routes[-1]['direct_response']['status']==404
    for name in ['gateway','edge-proxy']:assert one('Deployment',name)['spec']['template']['metadata']['annotations']['gaegaeting.app/chat-contract']==chat['revision']
    return envoy

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kubectl',required=True);p.add_argument('--baseline-ref',required=True);p.add_argument('--envoy-output',type=Path);a=p.parse_args()
    base=ROOT/'gitops/clusters/oci-a1/gaegaeting-dev'
    rendered=subprocess.run([a.kubectl,'kustomize',str(base)],capture_output=True,text=True,check=True).stdout
    resources=list(yaml.safe_load_all(rendered));release=json.loads((base/'release-images.json').read_text());envoy=verify(resources,release)
    def old(path):return subprocess.run(['git','show',a.baseline_ref+':'+path],cwd=ROOT,capture_output=True,text=True,check=True).stdout
    old_release=json.loads(old('gitops/clusters/oci-a1/gaegaeting-dev/release-images.json'))
    assert {k:v for k,v in release.items() if k!='devChat'}==old_release,'Existing service/migration metadata changed'
    paths=subprocess.run(['git','ls-tree','-r','--name-only',a.baseline_ref,'gitops/apps/base/gaegaeting'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
    for path in paths:
        if path.endswith('kustomization.yaml'):continue
        assert (ROOT/path).read_text()==old(path),'Existing base workload changed: '+path
    old_proxy=yaml.safe_load(old('gitops/clusters/oci-a1/gaegaeting-dev/edge-proxy-config.yaml'))['data']['start.sh']
    old_envoy=yaml.safe_load(old_proxy.split('<<EOF\n',1)[1].rsplit('EOF\n',1)[0])
    import copy
    preserved=copy.deepcopy(envoy)
    h=preserved['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
    h.pop('upgrade_configs');h['route_config']['virtual_hosts'][0]['routes'].pop(0)
    assert preserved==old_envoy,'Existing Envoy routing/filter/cluster semantics changed'
    kafka_path='gitops/clusters/oci-a1/kafka/network-policy.yaml'
    assert (ROOT/kafka_path).read_text()==old(kafka_path),'Existing Kafka policy changed'
    kafka=yaml.safe_load((ROOT/'gitops/clusters/oci-a1/kafka/gaegaeting-chat-client.yaml').read_text())
    assert kafka['spec']['podSelector']['matchLabels']=={'app.kubernetes.io/name':'kafka'}
    rule=kafka['spec']['ingress'][0]
    assert rule['ports']==[{'port':9092,'protocol':'TCP'}] and len(rule['from'])==1
    assert rule['from'][0]['namespaceSelector']['matchLabels']=={'kubernetes.io/metadata.name':'gaegaeting-dev'}
    assert rule['from'][0]['podSelector']['matchLabels']=={'app.kubernetes.io/name':'chat','app.kubernetes.io/part-of':'gaegaeting'}
    if a.envoy_output:
        data=yaml.safe_dump(envoy,sort_keys=False)
        # Synthetic names only for isolated binary validation; never runtime addresses.
        data=re.sub(r'\$\{[A-Z_]+\}', 'validation.invalid',data)
        a.envoy_output.write_text(data)
    print(json.dumps({'valid':True,'resources':len(resources),'existingBaseWorkloadsAndReleaseMetadataPreserved':True,'httpEdgeAuthPreserved':True,'wsRequiresGatewayConnectionInitAuth':True}))
if __name__=='__main__':main()
