import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('panel_session',ROOT/'scripts/vpn-panel-session.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class SessionTests(unittest.TestCase):
    def test_unsafe_name_rejected(self):
        for name in ('install','cli-fallback','vpn83-../x','vpn83-a'):
            with self.assertRaises(ValueError):m.NativeSession('/tmp/'+name)

    def test_collision_refuses_even_preview(self):
        s=m.NativeSession('/tmp/vpn83-20261108-test')
        with patch.object(m,'token_rows',return_value=[{'name':s.names['worker']}]),patch.object(m,'pod_identity') as pod:
            with self.assertRaises(ValueError):s.preview()
            pod.assert_not_called()

    def test_api_paths_and_redirects_are_restricted(self):
        for path in ('/setting/reset','/inbounds/update/1?x=y','/../secret'):
            with self.assertRaises(ValueError):m.request('http://127.0.0.1:18082/base','A'*48,'POST',path,{})
        with self.assertRaises(ValueError):m.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_wrong_host_refuses_before_token_creation(self):
        s=m.NativeSession('/tmp/vpn83-20261108-host')
        with patch.object(m.socket,'gethostname',return_value='socrat-0'),patch.object(m.subprocess,'run') as run:
            with self.assertRaises(ValueError):s.open('bad')
            run.assert_not_called()

    def test_native_success_and_cleanup_preserve_original_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve()/'vpn83-20261108-success';s=m.NativeSession(state)
            original={'id':1,'name':'existing','scope':'admin','enabled':1,'token':'untouched-hash','created_at':1,'expires_at':0}
            rows=[original.copy()];calls=[]
            values={'bootstrap':'B'*48,'cleanup':'C'*48,'worker':'W'*48}
            def insert(kind,scope,expires=0):
                row={'id':max([x['id'] for x in rows]+[0])+1,'name':s.names[kind],
                     'scope':scope,'enabled':1,'expires_at':expires,'created_at':2,
                     'token':hashlib.sha256(values[kind].encode()).hexdigest()}
                rows.append(row)
                return {'id':row['id'],'name':row['name'],'scope':scope,'expiresAt':expires,'token':values[kind]}
            def cli(args,**kwargs):
                self.assertIn('-tokenName',args);self.assertIn(s.names['bootstrap'],args)
                self.assertNotIn('existing',args);insert('bootstrap','admin')
                kwargs['stdout'].write('apiToken: '+values['bootstrap']+'\n')
                return type('Result',(),{'returncode':0})()
            def api(base,token,method,path,body=None):
                calls.append((token,method,path,body))
                if path.endswith('/create'):
                    kind=next(k for k in values if s.names[k]==body['name'])
                    self.assertGreater(body['expiresAt'],0)
                    return insert(kind,body['scope'],body['expiresAt'])
                if '/delete/' in path:
                    target=int(path.rsplit('/',1)[1]);row=next(r for r in rows if r['id']==target)
                    self.assertEqual(row['scope'],body['expectedScope']);rows.remove(row);return None
                self.assertEqual(token,values['worker']);return []
            def directory(path):path.mkdir(mode=0o700);return path
            with patch.object(m.socket,'gethostname',return_value='socrat-2'),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'token_rows',side_effect=lambda *args:[x.copy() for x in rows]),patch.object(m,'pod_identity',return_value={'name':'pod','uid':'pinned','image':m.IMAGE}),patch.object(m.h,'inspect',return_value={'configuration_sha256':'cfg'}),patch.object(m.h,'private_directory',side_effect=directory),patch.object(m,'api_path',return_value='http://127.0.0.1:18082/base/panel/api'),patch.object(m.subprocess,'run',side_effect=cli),patch.object(m,'request',side_effect=api):
                approval=m.h.digest(s.preview());s.open(approval)
                self.assertFalse(any(r['name']==s.names['bootstrap'] for r in rows))
                self.assertEqual(s.credentials['worker']['scope'],'node-sync')
                s.call('GET','/inbounds/list')
                with self.assertRaises(ValueError):s.call('POST','/setting/apiTokens/create',{})
                # Ownership mismatch must never delete a credential.
                worker=next(r for r in rows if r['name']==s.names['worker']);old=worker['token'];worker['token']='foreign'
                with self.assertRaises(ValueError):s._owned('worker')
                worker['token']=old
                s.cleanup();s.cleanup()
            self.assertEqual(rows,[original])
            self.assertTrue(json.loads((state/'credential-cleanup.json').read_text())['existing_tokens_unchanged'])
            self.assertFalse((state/'uncertain.json').exists())
            for filename in ('bootstrap.stdout','bootstrap.json','cleanup.json','worker.json'):
                self.assertFalse((state/filename).exists())
            self.assertNotIn('B'*48,json.dumps(json.loads((state/'credential-cleanup.json').read_text())))

    def test_wrong_approval_does_not_invoke_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve()/'vpn83-20261108-approval';s=m.NativeSession(state)
            def directory(path):path.mkdir(mode=0o700);return path
            with patch.object(m.socket,'gethostname',return_value='socrat-2'),patch.object(m.os,'geteuid',return_value=0),patch.object(m.h,'private_directory',side_effect=directory),patch.object(s,'preview',return_value={'x':1}),patch.object(m.subprocess,'run') as run:
                with self.assertRaises(ValueError):s.open('wrong')
                run.assert_not_called()
            if s.lock:s.lock.close()
