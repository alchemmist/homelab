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
    def rows(self):
        with sqlite3.connect(self.path) as c:return list(c.iterdump())
    def mutate(self,sql,args=()):
        with sqlite3.connect(self.path) as c:c.execute(sql,args)
    def reject(self):
        before=self.rows()
        with self.assertRaises((ValueError,sqlite3.DatabaseError)):m.retry(self.path,self.auth,True)
        self.assertEqual(before,self.rows())
    def test_dry_run(self):
        before=self.rows();self.assertEqual(m.retry(self.path,self.auth)['eligible'],2);self.assertEqual(before,self.rows())
    def test_execute_preserves_counters_and_other_tables(self):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;before=m.table_hashes(c)
        self.assertEqual(m.retry(self.path,self.auth,True)['changed'],2)
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;after=m.table_hashes(c)
            for key in before:
                if key!='jobs':self.assertEqual(before[key],after[key])
            self.assertEqual([tuple(x) for x in c.execute('SELECT state,attempts,created,result FROM jobs')],[('retry',7,0.0,'{"history":"retained"}')]*2)
            self.assertEqual(c.execute('SELECT count(*) FROM operator_retry_audit').fetchone()[0],2)
            with self.assertRaises(sqlite3.DatabaseError):c.execute('DELETE FROM operator_retry_audit')
    def test_nonce_survives_redeath_restart(self):
        m.retry(self.path,self.auth,True);self.mutate("UPDATE jobs SET state='dead'");self.reject()
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
