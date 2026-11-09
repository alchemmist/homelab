"""Offline source/Helm invariants for the full-service extraction; no live calls."""
import json
from pathlib import Path
import subprocess
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]

class FullServiceBundleTests(unittest.TestCase):
    def render(self, bundled=False):
        args=['helm','template','spi-triage',str(ROOT/'charts/spi-triage'),'-n','automation',
              '-f',str(ROOT/'deploy/spi-triage/values.yaml'),'--set','bundleEnabled=false']
        if bundled:args += ['--set','bundleEnabled=true','--set','image.tag='+'b'*40,
                           '--set','image.digest=sha256:'+'a'*64]
        return {(x['kind'],x['metadata'].get('namespace','automation'),x['metadata']['name']):x
                for x in yaml.safe_load_all(subprocess.check_output(args)) if x}
    def test_same_release_image_for_backend_frontend_and_scoped_broker(self):
        docs=self.render(True);image='harbor.socrat.alchemmist.xyz/homelab/spi-triage@sha256:'+'a'*64
        for name in ('spi-triage','spi-queue-ui'):
            pod=docs['Deployment','automation',name]['spec']['template']['spec']
            self.assertEqual(pod['containers'][0]['image'],image)
            self.assertFalse(any(v['name'] in ('code','ui') for v in pod['volumes']))
        pod=docs['CronJob','pr-agent','spi-github-broker']['spec']['jobTemplate']['spec']['template']['spec']
        self.assertEqual(pod['containers'][0]['image'],image)
        self.assertNotIn('volumes',pod)
        self.assertNotIn(('ConfigMap','automation','spi-triage-code'),docs)
        self.assertNotIn(('ConfigMap','pr-agent','spi-github-broker-code'),docs)
        self.assertNotIn(('ConfigMap','automation','spi-queue-ui'),docs)
    def test_queue_identity_is_not_replaced_or_exposed_to_web(self):
        docs=self.render(True);dep=docs['Deployment','automation','spi-triage']
        self.assertEqual(dep['spec']['replicas'],1)
        self.assertEqual(dep['spec']['strategy'],{'type':'Recreate'})
        pod=dep['spec']['template']['spec']
        self.assertIn({'name':'data','persistentVolumeClaim':{'claimName':'spi-triage-data'}},pod['volumes'])
        frontend=docs['Deployment','automation','spi-queue-ui']['spec']['template']['spec']
        self.assertFalse(frontend['automountServiceAccountToken'])
        self.assertNotIn('envFrom',frontend['containers'][0])
        self.assertEqual(frontend['volumes'],[{'name':'queue-control','secret':{'secretName':'spi-queue-control','defaultMode':288}}])
        self.assertIn('Delete=false',docs['PersistentVolumeClaim','automation','spi-triage-data']['metadata']['annotations']['argocd.argoproj.io/sync-options'])
    def test_bundle_does_not_change_resources_credentials_fences_or_quotas(self):
        legacy=self.render();bundled=self.render(True)
        a=legacy['Deployment','automation','spi-triage']['spec']['template']['spec']['containers'][0]
        b=bundled['Deployment','automation','spi-triage']['spec']['template']['spec']['containers'][0]
        for field in ('env','envFrom','resources','securityContext','command','readinessProbe','livenessProbe'):
            self.assertEqual(a[field],b[field],field)
        for kind in ('PersistentVolumeClaim','Service','NetworkPolicy','ServiceAccount','Role','RoleBinding'):
            self.assertEqual({k:v for k,v in legacy.items()if k[0]==kind},{k:v for k,v in bundled.items()if k[0]==kind})
    def test_legacy_code_is_frozen_and_no_second_argo_publisher_exists(self):
        import hashlib
        manifest=json.loads((ROOT/'charts/spi-triage/LEGACY-SOURCE-MANIFEST.json').read_text())
        for name,digest in manifest['backend_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/'charts/spi-triage/files'/name).read_bytes()).hexdigest(),digest,name)
        self.assertFalse((ROOT/'deploy/argocd/apps/spi-queue-ui.yaml').exists())
        app=yaml.safe_load((ROOT/'deploy/argocd/apps/spi-triage.yaml').read_text())
        self.assertEqual(app['spec']['source']['helm']['parameters'],[])
        self.assertEqual(app['spec']['source']['helm']['valueFiles'],['../../deploy/spi-triage/values.yaml'])
        self.assertEqual(app['spec']['project'],'default')

if __name__=='__main__':unittest.main()
