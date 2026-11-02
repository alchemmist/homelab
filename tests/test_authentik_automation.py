import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'ansible/roles/authentik/files'
spec=importlib.util.spec_from_file_location('automation',FILES/'automation.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class Fake:
 def __init__(self):
  self.users=[{'pk':5,'uuid':a.OWNER_UUID,'username':'alchemmist','is_superuser':True,'is_active':True}]
  self.groups=[];self.tokens=[];self.writes=[]
 def __call__(self,token,method,path,data=None):
  endpoint,_,query=path.partition('?');parts=endpoint.strip('/').split('/')
  if method!='GET':self.writes.append((method,path,data))
  if endpoint in ['providers/all/','core/applications/','flows/instances/','outposts/instances/']:return {'results':[]}
  rows={'users':self.users,'groups':self.groups,'tokens':self.tokens}[parts[1]]
  if method=='DELETE':
   row=next(r for r in rows if str(r.get('pk'))==parts[2]);rows.remove(row)
   self.tokens[:]=[t for t in self.tokens if t['user']!=row['pk']]
   return None
  if method=='POST':
   if parts[1]=='groups':r=dict(pk='group-machine',users=[],**data)
   elif parts[1]=='users':
    r=dict(pk=7,uuid='machine-uuid',is_superuser=True,**data)
    self.groups[0]['users'].append(r['pk'])
   else:r=dict(data)
   rows.append(r);return r
  if len(parts)>2:
   if parts[-1]=='view_key':return {'key':'unit-machine-token'}
   return next(r for r in rows if str(r.get('pk',r.get('identifier')))==parts[2] or r.get('identifier')==parts[2])
  for key,values in parse_qs(query).items():
   if key!='page_size':rows=[r for r in rows if r.get(key)==values[0]]
  return {'results':rows}

class AutomationTests(unittest.TestCase):
 def root(self,d):
  p=Path(d);p.chmod(0o700);a.save(p/'credentials.json',{'AUTHENTIK_BOOTSTRAP_TOKEN':'unit-old-token','AUTHENTIK_BOOTSTRAP_PASSWORD':'unit-old-password','AUTHENTIK_SECRET_KEY':'unit-signing-key'})
  return p
 def test_apply_and_repeat_do_not_delete_or_change_humans(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();output=io.StringIO()
   with patch.object(a,'api',fake),contextlib.redirect_stdout(output):
    a.migrate(p,'apply');writes=len(fake.writes);a.migrate(p,'check');a.migrate(p,'apply')
   self.assertEqual(writes,len(fake.writes))
   self.assertNotIn('unit-machine-token',output.getvalue())
   self.assertNotIn('unit-old-token',output.getvalue())
   self.assertEqual(fake.users[0]['uuid'],a.OWNER_UUID)
   self.assertFalse(any(m=='DELETE' for m,_,_ in fake.writes))
   self.assertEqual(json.loads((p/'credentials.json').read_text())['AUTHENTIK_BOOTSTRAP_TOKEN'],'unit-machine-token')
   self.assertEqual((p/'automation-api.json').stat().st_mode & 0o077,0)
   before=list(p.glob('credentials-before-automation-*.json'));self.assertEqual(len(before),1)
   self.assertEqual(json.loads(before[0].read_text())['AUTHENTIK_BOOTSTRAP_TOKEN'],'unit-old-token')
 def test_check_without_migration_does_not_write(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d)
   with patch.object(a,'api') as api,contextlib.redirect_stdout(io.StringIO()):a.migrate(p,'check')
   api.assert_not_called();self.assertFalse((p/'automation-api.json').exists())
 def test_foreign_account_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();fake.users.append({'username':a.NAME})
   with patch.object(a,'api',fake),self.assertRaises(RuntimeError):a.migrate(p,'apply')
   self.assertEqual(fake.writes,[])
 def test_wrong_owner_uuid_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();fake.users[0]['uuid']='different-owner'
   with patch.object(a,'api',fake),self.assertRaises(RuntimeError):a.migrate(p,'apply')
   self.assertEqual(fake.writes,[])
 def test_alias_drift_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake()
   with patch.object(a,'api',fake),contextlib.redirect_stdout(io.StringIO()):a.migrate(p,'apply')
   a.save(p/'credentials.json',{'AUTHENTIK_BOOTSTRAP_TOKEN':'other'})
   with patch.object(a,'api',fake),self.assertRaises(RuntimeError):a.migrate(p,'check')
 def bootstrap(self,p):
  with patch('sys.argv',['bootstrap.py',str(p)]),patch('subprocess.run') as run,contextlib.redirect_stdout(io.StringIO()):
   runpy.run_path(str(FILES/'bootstrap.py'),run_name='__main__')
  return json.loads(run.call_args.kwargs['input'])
 def test_runtime_excludes_admin_secrets_after_migration(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);a.save(p/'automation-api.json',{'status':'active','token':'unit-old-token'})
   manifest=self.bootstrap(p)['stringData']
   self.assertNotIn('AUTHENTIK_BOOTSTRAP_TOKEN',manifest);self.assertNotIn('AUTHENTIK_BOOTSTRAP_PASSWORD',manifest)
   self.assertEqual(manifest['AUTHENTIK_SECRET_KEY'],'unit-signing-key')
 def test_fresh_install_still_has_initial_bootstrap(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);self.assertIn('AUTHENTIK_BOOTSTRAP_TOKEN',self.bootstrap(p)['stringData'])
 def test_incomplete_journal_refuses_secret_apply(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);a.save(p/'automation-api.json',{'status':'preparing'})
   with self.assertRaises(SystemExit):self.bootstrap(p)

 def ready_retirement(self,p,fake):
  with patch.object(a,'api',fake),contextlib.redirect_stdout(io.StringIO()):a.migrate(p,'apply')
  j=json.loads((p/'automation-api.json').read_text())
  j['recovery_evidence']={'fixture_admin_session_verified':True,'fixture_cleanup_verified':True,'owner_uuid':a.OWNER_UUID}
  j['encrypted_backup_sha256']='unit-digest';a.save(p/'automation-api.json',j)
  (p/'bootstrap.py').write_text((FILES/'bootstrap.py').read_text())
 def kube_read(self,args,**kwargs):
  if 'secret' in args:return json.dumps({'data':{},'metadata':{'annotations':{}}}).encode()
  return json.dumps({'spec':{'template':{'spec':{'containers':[{'env':[]}]}}}}).encode()
 def test_retirement_requires_recovery_and_backup(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake()
   with patch.object(a,'api',fake),contextlib.redirect_stdout(io.StringIO()):a.migrate(p,'apply')
   with patch.object(a,'api',fake),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):a.retire_default_admin(p)
   self.assertFalse(any(m=='DELETE' for m,_,_ in fake.writes))
 def test_retirement_refuses_different_default_admin_uuid(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();self.ready_retirement(p,fake)
   fake.users.append({'pk':4,'username':'akadmin','uuid':'not-reviewed'})
   with patch.object(a,'api',fake),patch('subprocess.check_output',self.kube_read),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):a.retire_default_admin(p)
   self.assertFalse(any(m=='DELETE' for m,_,_ in fake.writes))
 def test_retirement_refuses_runtime_bootstrap_secret(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();self.ready_retirement(p,fake)
   secret=json.dumps({'data':{'AUTHENTIK_BOOTSTRAP_TOKEN':'unit-old'},'metadata':{}}).encode()
   with patch.object(a,'api',fake),patch('subprocess.check_output',return_value=secret),contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):a.retire_default_admin(p)
   self.assertFalse(any(m=='DELETE' for m,_,_ in fake.writes))
 def test_retirement_exact_identity_and_idempotence(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.root(d);fake=Fake();self.ready_retirement(p,fake)
   fake.users.append({'pk':4,'username':'akadmin','uuid':'fc86d87d-3a72-4cfb-8ba1-aa6bf6b017e7'})
   fake.tokens.append({'identifier':'authentik-bootstrap-token','user':4})
   with patch.object(a,'api',fake),patch('subprocess.check_output',self.kube_read),contextlib.redirect_stdout(io.StringIO()):
    a.retire_default_admin(p);a.retire_default_admin(p)
   self.assertEqual([(m,path) for m,path,_ in fake.writes if m=='DELETE'],[('DELETE','core/users/4/')])
   self.assertTrue(any(t['identifier']==a.NAME for t in fake.tokens))
   self.assertNotIn('AUTHENTIK_BOOTSTRAP_PASSWORD',json.loads((p/'credentials.json').read_text()))

if __name__=='__main__':unittest.main()
