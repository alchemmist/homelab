import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from test_triage import event, report
from core import Store, digest, Failure
from service import Engine
from evidence_bundle import prepare_bundle
from s3_evidence import StorageTransient

class EngineStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db');self.key=self.store.enqueue(event())['job_id'];self.store.claim()
        self.bundle=prepare_bundle(event(),{},[{'name':'logs.json','content':'private diagnostic'}])
        self.r={'report':report(),'match':{'candidates':[]},'open_signature':digest([]),'evidence':{'bundle':self.bundle}}
        self.store.save(self.key,3,self.r)
        self.g=Mock();self.g.snapshot.return_value=[];self.g.request.return_value={'number':9}
        self.s=Mock();self.s.ensure_object.side_effect=self.verify
        self.engine=Engine(self.store,self.g,Mock(),Mock(),write=True,storage=self.s,storage_backend='s3')
    def verify(self,key,raw):
        self.assertEqual(self.store.get(self.key)['result']['publication_backend'],'s3')
        self.g.request.assert_not_called()
        return {'bucket':'spi-evidence','key':key,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'verified':True}
    def test_verified_before_single_primary(self):
        self.engine.run('publish',self.key)
        self.assertEqual(self.s.ensure_object.call_count,2);self.assertEqual(self.g.request.call_count,1)
        body=self.g.request.call_args.args[2]['body'];self.assertIn('https://spi-evidence.',body);self.assertNotIn('private diagnostic',body)
    def test_per_file_checkpoint_restart_toggle(self):
        n=[0]
        def upload(k,b):
            n[0]+=1
            if n[0]==2:raise StorageTransient(2)
            return self.verify(k,b)
        self.s.ensure_object.side_effect=upload
        with self.assertRaisesRegex(Failure,'STORAGE_TRANSIENT'):self.engine.run('publish',self.key)
        saved=self.store.get(self.key);self.assertEqual(len(saved['result']['storage_publication']['verified']),1)
        self.g.request.assert_not_called()
        self.store.save(self.key,3,saved['result'],state='processing')
        self.s.ensure_object.side_effect=self.verify
        engine=Engine(self.store,self.g,Mock(),Mock(),write=True,storage=self.s)
        engine.run('publish',self.key);self.assertEqual(self.s.ensure_object.call_count,3)
        self.assertEqual(self.g.request.call_count,1)
    def test_patient_budgets_independent(self):
        for code,count in [('LLM_HTTP_429',20),('STORAGE_TRANSIENT',12)]:
            for _ in range(count):self.store.fail(self.key,code,2)
        with self.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM job_failure_budget').fetchone()[0],0)
        self.assertEqual(self.store.get(self.key)['state'],'retry')
        self.store.save(self.key,3,self.r,state='processing');self.engine.run('publish',self.key)
        self.assertEqual(self.g.request.call_count,1)
    def test_changed_snapshot_preserves_lock(self):
        self.g.snapshot.side_effect=[[],[{'number':3,'updated_at':'new'}]]
        with self.assertRaisesRegex(Failure,'OPEN_SPI_CHANGED'):self.engine.run('publish',self.key)
        self.g.request.assert_not_called();self.assertEqual(self.store.get(self.key)['result'],{'publication_backend':'s3'})
    def test_checkpoint_tampering_rejected(self):
        self.r['publication_backend']='s3';self.r['storage_publication']={'binding':[],'verified':[]}
        self.store.save(self.key,3,self.r)
        with self.assertRaisesRegex(Failure,'STORAGE_INTEGRITY'):self.engine.run('publish',self.key)
        self.g.request.assert_not_called();self.s.ensure_object.assert_not_called()
    def test_empty_bundle(self):
        self.r['evidence']={};self.store.save(self.key,3,self.r)
        self.engine.run('publish',self.key);self.s.ensure_object.assert_not_called();self.assertEqual(self.g.request.call_count,1)
    def test_new_legacy_lock_survives_toggle_after_rejection(self):
        self.engine.storage_backend='legacy';self.g.comments.return_value=[]
        self.g.request.side_effect=Failure('HTTP_429')
        with self.assertRaises(Failure):self.engine.run('publish',self.key)
        saved=self.store.get(self.key);self.assertEqual(saved['result']['publication_backend'],'legacy')
        self.store.save(self.key,3,saved['result'],state='processing')
        self.engine.storage_backend='s3';self.g.request.side_effect=None
        self.engine.run('publish',self.key);self.s.ensure_object.assert_not_called()
