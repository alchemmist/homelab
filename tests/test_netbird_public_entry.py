import base64
import datetime
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
entry=load('nb_entry','netbird-public-entry.py')
owner=load('nb_owner','netbird-owner-handover.py')

class PublicEntryTests(unittest.TestCase):
    def test_scoped_identity_entry(self):
        docs=entry.manifests()
        self.assertTrue(all(d['metadata']['namespace'] in ['identity','netbird-pilot'] for d in docs))
        self.assertFalse(any(d['kind'] in ['Secret','ClusterRole','Role','IngressRoute','Namespace'] for d in docs))
        self.assertNotIn('netbird-runtime',yaml.safe_dump_all(docs))
        deploy=next(d for d in docs if d['kind']=='Deployment')
        self.assertEqual(deploy['metadata']['name'],'netbird-edge-forwarder')
        cm=next(d for d in docs if d['kind']=='ConfigMap')
        static=yaml.safe_load(cm['data']['static.yaml'])
        self.assertEqual(static['entryPoints']['ping']['address'],':8081')
        self.assertNotIn('http2',static['entryPoints']['h2c'])
        dynamic=yaml.safe_load(cm['data']['dynamic.yaml'])
        deny=dynamic['http']['routers']['deny-setup']['rule']
        for path in ['/api/setup','/api/users/invites','/oauth2/auth/local','/oauth2/signup']:
            self.assertIn(path,deny)
        self.assertIn('Path(`/api/setup`)',deny)
        self.assertIn('PathPrefix(`/api/setup/`)',deny)
        self.assertNotIn('PathPrefix(`/api/setup`)',deny)
        for d in docs:
            if d['kind']=='Service':
                self.assertNotIn('NodePort',str(d));self.assertNotIn('3478',str(d))
            if d['kind']=='Ingress':
                self.assertEqual(d['spec']['ingressClassName'],'traefik')
                self.assertEqual(d['spec']['tls'][0]['secretName'],'netbird-pilot-tls')
        policy=next(d for d in docs if d['kind']=='NetworkPolicy')
        rule=policy['spec']['ingress'][1]
        self.assertEqual(rule['ports'],[{'port':80,'protocol':'TCP'}])
        self.assertEqual(rule['from'][0]['namespaceSelector']['matchLabels'],{'kubernetes.io/metadata.name':'identity'})
        self.assertEqual(rule['from'][0]['podSelector']['matchLabels'],{'app':'netbird-edge-forwarder'})

    def test_grpc_scheme_is_on_dedicated_service_not_ingress(self):
        docs=entry.manifests()
        by_name={(d['kind'],d['metadata']['name']):d for d in docs}
        key='traefik.ingress.kubernetes.io/service.serversscheme'
        grpc=by_name['Service','netbird-edge-forwarder-grpc']
        web=by_name['Service','netbird-edge-forwarder']
        self.assertEqual(grpc['metadata']['annotations'][key],'h2c')
        self.assertEqual(grpc['spec']['selector'],web['spec']['selector'])
        self.assertEqual(grpc['spec']['ports'],[{'name':'h2c','port':8082,'targetPort':'h2c'}])
        self.assertNotIn(key,web['metadata'].get('annotations',{}))
        for name,target in [('netbird-grpc','netbird-edge-forwarder-grpc'),
                            ('netbird-http','netbird-edge-forwarder')]:
            ingress=by_name['Ingress',name]
            self.assertNotIn(key,ingress['metadata']['annotations'])
            self.assertTrue(all(p['backend']['service']['name']==target
                                for p in ingress['spec']['rules'][0]['http']['paths']))

    def fixture(self):
        return {'id':owner.subject(),'email':owner.EMAIL,'idp_id':owner.CONNECTOR,
                'is_service_user':False,'is_blocked':False,'pending_approval':False,'status':'active',
                'last_login':datetime.datetime.now(datetime.timezone.utc).isoformat(),'role':'user'}

    def test_exact_subject_matches_upstream_protobuf(self):
        data=base64.b64decode(owner.subject()+'==')
        self.assertEqual(data,b'\x0a\x24'+owner.UUID.encode()+b'\x12'+bytes([len(owner.CONNECTOR)])+owner.CONNECTOR.encode())
        self.assertEqual(owner.target_user([self.fixture()],owner.subject())['id'],owner.subject())

    def test_no_uuid_connector_email_fallback(self):
        for candidate in [owner.EMAIL,owner.UUID,owner.subject('0d2c194a-dee7-4226-b599-0a44ce2f2b76'),owner.subject(connector='local')]:
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):owner.target_user([self.fixture()],candidate)
        for key,value in [('email','other@example.invalid'),('idp_id','local'),('is_service_user',True),('last_login','0001-01-01T00:00:00Z')]:
            user=self.fixture();user[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):owner.target_user([user],owner.subject())
        with self.assertRaises(ValueError):owner.target_user([],owner.subject())

if __name__=='__main__':unittest.main()
