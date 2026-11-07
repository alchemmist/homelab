import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('operator_retry',ROOT/'scripts/n8n/spi_operator_retry.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db'
        self.auth={'authorization_text':'Да, все рзрешаю','nonce':m.NONCE,'job_ids':list(m.TARGETS),'reason':'reviewed two jobs','recorded_at':'2026-11-07T07:30:00+00:00','authorized_message_timestamp':None,'supervisor_run_id':'497906c9-c254-4586-9762-e1aa195b8f24'}
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,episode TEXT,stage INTEGER,state TEXT,lease REAL,error TEXT,intent TEXT,available REAL,updated REAL,created REAL,attempts INTEGER,result TEXT)')
            for i,(key,error) in enumerate(m.TARGETS.items()):
                c.execute('INSERT INTO jobs VALUES(?,?,2,\'dead\',0,?,NULL,1,2,0,7,?)',(key,str(i),error,'{"history":"retained"}'))
            for table in ('job_failure_budget','snapshot_budget','cache','ledger','outbox','upload_receipts'):
                c.execute('CREATE TABLE '+table+'(id TEXT,value INTEGER)');c.execute('INSERT INTO '+table+' VALUES(\'original\',99)')
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row
            self.manifest={'version':1,'nonce':m.NONCE,'original_target_file_sha256':'0'*64,'rows':[dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY id')]}
        self.auth['target_manifest_digest']=m.manifest_digest(self.manifest)
    def test_individual_drift(self):
        for field,value in [('result','unreviewed'),('episode','other'),('attempts',999),('created',99)]:
            with self.subTest(field=field):
                original=self.manifest['rows'][0][field]
                self.mutate('UPDATE jobs SET '+field+'=? WHERE id=?',(value,self.manifest['rows'][0]['id']))
                self.reject()
                self.mutate('UPDATE jobs SET '+field+'=? WHERE id=?',(original,self.manifest['rows'][0]['id']))
    def test_extra_column(self):
        self.mutate('ALTER TABLE jobs ADD COLUMN extra TEXT');self.reject()
    def test_manifest_missing(self):
        self.manifest=None;self.reject()
    def test_manifest_tamper(self):
        self.manifest['rows'][0]['result']='tampered';self.reject()
    def test_manifest_bad_ids(self):
        self.manifest['rows'][0]['id']='bad';self.reject()
    def test_manifest_digest(self):
        self.auth['target_manifest_digest']='0'*64;self.reject()
    def test_audit_trigger_injection(self):
        self.mutate('CREATE TABLE operator_retry_audit (nonce TEXT,job_id TEXT,authorization_hash TEXT,pre_row_hash TEXT,executed_at REAL,reason TEXT,explicit_change TEXT,manifest_digest TEXT,post_row_hash TEXT,PRIMARY KEY(nonce,job_id))')
        self.mutate("CREATE TRIGGER inject AFTER INSERT ON operator_retry_audit WHEN NEW.nonce != 'injected' BEGIN INSERT INTO operator_retry_audit VALUES('injected','x','','',0,'','','',''); END")
        self.reject()
    def test_manifest_malformed(self):
        self.manifest={'version':99};self.reject()
    def test_audit_schema_tamper(self):
        self.mutate('CREATE TABLE operator_retry_audit (nonce TEXT,job_id TEXT)')
        self.mutate('CREATE TRIGGER operator_retry_audit_no_update BEFORE UPDATE ON operator_retry_audit BEGIN SELECT 1; END')
        self.reject()
    def test_audit_posthash_tamper(self):
        self.mutate('CREATE TABLE operator_retry_audit (nonce TEXT,job_id TEXT,authorization_hash TEXT,pre_row_hash TEXT,executed_at REAL,reason TEXT,explicit_change TEXT,manifest_digest TEXT,post_row_hash TEXT,PRIMARY KEY(nonce,job_id))')
        self.mutate("CREATE TRIGGER corrupt AFTER INSERT ON operator_retry_audit BEGIN UPDATE operator_retry_audit SET post_row_hash='bad'; END")
        self.reject()
    def test_final_bound_target_recheck(self):
        self.mutate('CREATE TABLE operator_retry_audit (nonce TEXT,job_id TEXT,authorization_hash TEXT,pre_row_hash TEXT,executed_at REAL,reason TEXT,explicit_change TEXT,manifest_digest TEXT,post_row_hash TEXT,PRIMARY KEY(nonce,job_id))')
        self.mutate("CREATE TRIGGER corrupt AFTER INSERT ON operator_retry_audit BEGIN UPDATE jobs SET result='unreviewed' WHERE id=NEW.job_id; END")
        self.reject()
    def rows(self):
        with sqlite3.connect(self.path) as c:return list(c.iterdump())
    def mutate(self,sql,args=()):
        with sqlite3.connect(self.path) as c:c.execute(sql,args)
    def reject(self):
        before=self.rows()
        with self.assertRaises((ValueError,sqlite3.DatabaseError)):m.retry(self.path,self.auth,True,self.manifest)
        self.assertEqual(before,self.rows())
    def test_dry_run(self):
        before=self.rows();self.assertEqual(m.retry(self.path,self.auth,manifest=self.manifest)['eligible'],2);self.assertEqual(before,self.rows())
    def test_execute_preserves_counters_and_other_tables(self):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;before=m.table_hashes(c)
        self.assertEqual(m.retry(self.path,self.auth,True,self.manifest)['changed'],2)
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;after=m.table_hashes(c)
            for key in before:
                if key!='jobs':self.assertEqual(before[key],after[key])
            self.assertEqual([tuple(x) for x in c.execute('SELECT state,attempts,created,result FROM jobs')],[('retry',7,0.0,'{"history":"retained"}')]*2)
            self.assertEqual(c.execute('SELECT count(*) FROM operator_retry_audit').fetchone()[0],2)
            with self.assertRaises(sqlite3.DatabaseError):c.execute('DELETE FROM operator_retry_audit')
    def test_nonce_survives_redeath_restart(self):
        m.retry(self.path,self.auth,True,self.manifest);self.mutate("UPDATE jobs SET state='dead'");self.reject()
    def test_wrong_id(self):
        self.auth['job_ids'][0]='a'*64;self.reject()
    def test_wrong_auth(self):
        self.auth['authorization_text']='yes';self.reject()
    def test_lease(self):
        self.mutate('UPDATE jobs SET lease=1');self.reject()
    def test_intent(self):
        self.mutate("UPDATE jobs SET intent='publication'");self.reject()
    def test_stage(self):
        self.mutate('UPDATE jobs SET stage=1');self.reject()
    def test_error(self):
        self.mutate("UPDATE jobs SET error='unexpected'");self.reject()
    def test_completed(self):
        self.mutate("UPDATE jobs SET state='complete'");self.reject()
    def test_full64_collision(self):
        key=next(iter(m.TARGETS));self.mutate('UPDATE jobs SET id=? WHERE id=?',(key[:12]+'f'*52,key));self.reject()
    def test_trigger_other_row_rollback(self):
        self.mutate('CREATE TRIGGER sabotage AFTER UPDATE ON jobs BEGIN UPDATE ledger SET value=0; END');self.reject()
    def test_missing_row_atomic(self):
        self.mutate('DELETE FROM jobs WHERE id=?',(next(iter(m.TARGETS)),));self.reject()

if __name__=='__main__':unittest.main()

class ProductionStoreTests(unittest.TestCase):
    def test_v3_reopen_three_times_and_old_writer(self):
        import sys
        sys.path.insert(0,str(ROOT/'charts/spi-triage/files'))
        from core import Store
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'production-schema'
            Store(path)
            with sqlite3.connect(path) as c:
                for i,(key,error) in enumerate(m.TARGETS.items()):
                    c.execute("INSERT INTO jobs(id,episode,event,stage,state,created,updated,available,error) VALUES(?,?,?,2,'dead',1,2,3,?)",(key,str(i),'{}',error))
                c.execute("INSERT INTO jobs(id,episode,event,state,created,updated,available,lease) VALUES('old','old','{}','running',1,1,1,999)")
                c.row_factory=sqlite3.Row
                manifest={'version':1,'nonce':m.NONCE,'original_target_file_sha256':'0'*64,'rows':[dict(r) for r in c.execute("SELECT * FROM jobs WHERE state='dead' ORDER BY id")]}
            auth={'authorization_text':'Да, все рзрешаю','nonce':m.NONCE,'job_ids':list(m.TARGETS),'reason':'synthetic review','recorded_at':'2026-11-07T07:30:00+00:00','authorized_message_timestamp':None,'supervisor_run_id':'497906c9-c254-4586-9762-e1aa195b8f24','target_manifest_digest':m.manifest_digest(manifest)}
            m.retry(path,auth,True,manifest)
            def audit():
                with sqlite3.connect(path) as c:
                    return c.execute('SELECT * FROM operator_retry_audit ORDER BY job_id').fetchall()
            original=audit()
            for _ in range(3):Store(path)
            self.assertEqual(audit(),original)
            # Old writer touching its own leased row cannot erase audit history.
            with sqlite3.connect(path) as c:
                self.assertEqual(c.execute("SELECT lease FROM jobs WHERE id='old'").fetchone()[0],999)
                c.execute("UPDATE jobs SET result='old writer',lease=0 WHERE id='old'")
            self.assertEqual(audit(),original)
