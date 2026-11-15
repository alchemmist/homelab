"""Native auth/storage-preserving VM105 application-only placement contracts."""
from pathlib import Path
import hashlib,json,subprocess,tempfile,unittest,yaml
R=Path(__file__).resolve().parents[1]
def load(p):return yaml.safe_load((R/p).read_text())
def render(chart,values,release,ns):
 with tempfile.NamedTemporaryFile(mode='w',suffix='.yaml') as f:
  yaml.safe_dump(values,f);f.flush()
  raw=subprocess.check_output(['helm','template',release,str(R/chart),'--namespace',ns,'--kube-version','1.36.5','-f',f.name],stderr=subprocess.DEVNULL,text=True)
 return {(o['kind'],o['metadata']['name']):o for o in yaml.safe_load_all(raw) if o}
class MigrationTests(unittest.TestCase):
 def test_renderer_recovery_stays_local_to_grafana_after_failed_vm_deadlines(self):
  v=load('charts/grafana/alert-graphs.runtime.values.yaml')
  self.assertEqual(v['grafana']['imageRenderer']['nodeSelector'],{'kubernetes.io/hostname':'socrat-1'})
  self.assertEqual(v['alertGraphs']['nodeSelector'],{'kubernetes.io/hostname':'socrat-1'})
  self.assertEqual(v['grafana']['imageRenderer']['existingSecret'],'socrat-grafana-renderer')
 def test_lms_single_worker_and_original_database_and_identity(self):
  v=load('charts/lms/values.yaml');v.update(load('deploy/lms/values.yaml'))
  docs=render('charts/lms',v,'lms','lms');d=docs[('Deployment','lms')]
  self.assertEqual(d['spec']['strategy'],{'type':'Recreate'});self.assertEqual(d['spec']['replicas'],1)
  s=d['spec']['template']['spec'];self.assertEqual(s['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchExpressions'][0]['values'],['socrat-5'])
  self.assertEqual(s['hostAliases'],[{'ip':'10.43.218.222','hostnames':['auth.socrat.alchemmist.xyz']}])
  self.assertFalse(any('persistentVolumeClaim' in x for x in s['volumes']))
  env={e['name']:e for e in s['containers'][0]['env']}
  self.assertEqual(env['LMS_DATABASE_URL']['valueFrom']['secretKeyRef']['name'],'lms-db')
  self.assertEqual(env['LMS_OIDC_CLIENT_SECRET']['valueFrom']['secretKeyRef']['name'],'socrat-authentik-lms')
 def test_vendor_preserves_every_upstream_file_except_two_minimal_extensions(self):
  root=R/'charts/litellm';manifest=json.loads((root/'upstream-file-sha256.json').read_text())
  for name,digest in manifest.items():
   s=(root/name).read_bytes()
   if name=='templates/deployment.yaml':s=s.replace(b'      {{- with .Values.hostAliases }}\n      hostAliases:\n        {{- toYaml . | nindent 8 }}\n      {{- end }}\n',b'')
   if name=='templates/migrations-job.yaml':s=s[s.index(b'{{- if .Values.migrationJob.enabled }}'):]
   self.assertEqual(hashlib.sha256(s).hexdigest(),digest,name)
 def test_litellm_only_deployment_changes_no_migration_job_or_config_or_secrets(self):
  v=load('deploy/platform/litellm/values.yaml');after=render('charts/litellm',v,'litellm','llm')
  old=dict(v);old['nodeSelector']={'kubernetes.io/hostname':'socrat-0'};old['hostAliases']=[];old['migrationJob']=dict(old['migrationJob']);old['migrationJob'].pop('placementOnlyImage',None);old['migrationJob']['enabled']=True;old['envVars']=dict(old['envVars']);old['envVars'].pop('DISABLE_SCHEMA_UPDATE',None)
  before=render('charts/litellm',old,'litellm','llm');changed=[k for k in before if k in after and before[k]!=after[k]]
  self.assertEqual(changed,[('Deployment','litellm')])
  d=after[('Deployment','litellm')];self.assertEqual(d['spec']['replicas'],1)
  self.assertEqual(d['spec']['template']['spec']['terminationGracePeriodSeconds'],7260)
  s=d['spec']['template']['spec'];self.assertEqual(s['nodeSelector'],{'kubernetes.io/hostname':'socrat-5'})
  self.assertEqual(s['hostAliases'],[{'ip':'10.43.218.222','hostnames':['auth.socrat.alchemmist.xyz']}])
  self.assertTrue(any(k[0]=='Job' for k in before));self.assertFalse(any(k[0]=='Job' for k in after))
  broken=dict(v);broken['image']=dict(v['image']);broken['image']['tag']='not-reviewed-next-version'
  with self.assertRaises(subprocess.CalledProcessError):render('charts/litellm',broken,'litellm','llm')
  self.assertEqual(v['envVars']['DISABLE_SCHEMA_UPDATE'].lower(),'true');self.assertEqual(v['image']['tag'],'1.105.1');self.assertEqual(v['masterkeySecretName'],'litellm-env')
 def test_app_source_keeps_version_and_selective_sync_safety(self):
  a=load('deploy/argocd/apps/litellm.yaml')['spec'];self.assertEqual(a['sources'][0]['path'],'charts/litellm')
  self.assertFalse(a['syncPolicy']['automated']['prune']);self.assertIn('ApplyOutOfSyncOnly=true',a['syncPolicy']['syncOptions'])
  self.assertEqual(load('charts/litellm/Chart.yaml')['version'],'1.105.1')

 def test_ansible_cannot_silently_revert_to_old_node_or_oci_chart(self):
  s=(R/'ansible/playbooks/litellm.yml').read_text()
  self.assertIn('src: ../../deploy/platform/litellm/values.yaml',s)
  self.assertIn('src: ../../charts/litellm/',s)
  self.assertNotIn('oci://ghcr.io/berriai/litellm-helm',s)
  g=(R/'ansible/roles/monitoring_llm_gateway/files/configure_gateway.py').read_text()
  self.assertLess(g.index("source.get('path') == 'charts/litellm'"),g.index("run(helm + ['upgrade'"))
