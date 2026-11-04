import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'charts/spi-triage/files'))
from core import Store
from dispatcher import Dispatcher

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name+'/queue.sqlite')
    def enqueue(self,key='a'):
        return self.store.enqueue({'event_key':key,'episode':key})
    def test_empty_disabled_and_coalescing(self):
        calls=[]
        d=Dispatcher(self.store,'unused',post=lambda:calls.append(1))
        self.enqueue();d.tick();self.assertEqual(calls,[])
        d.enabled=True;d.tick();d.tick();self.assertEqual(calls,[1])
        self.assertGreater(self.store.dispatch_status()['deadline'],0)
    def test_empty(self):
        d=Dispatcher(self.store,'unused',True,lambda:self.fail('network'))
        self.assertIsNone(d.tick())
    def test_ambiguous_persists_and_ack_race(self):
        self.enqueue()
        def post():
            self.assertEqual(self.store.claim()['job_id'],'a')
            raise TimeoutError()
        Dispatcher(self.store,'unused',True,post).tick()
        self.assertEqual(self.store.dispatch_status()['attempts'],0)
        self.assertIsNone(self.store.reserve_dispatch()[0])
    def test_deadlines_recovery_and_terminal_lease(self):
        self.enqueue();self.enqueue('b')
        self.store.claim();self.store.save('a',4,{},state='dry_run')
        self.assertIsNotNone(self.store.reserve_dispatch()[0])
        self.assertEqual(self.store.claim()['job_id'],'b')
        self.assertEqual(self.store.recover_on_start(),1)
        self.assertIsNotNone(self.store.reserve_dispatch()[0])
    def test_backoff_restart_and_due_retry(self):
        with patch('core.time.time',return_value=100):
            self.enqueue();token,deadline=self.store.reserve_dispatch()
            self.assertEqual(deadline,130)
            reopened=Store(self.store.path)
            self.assertEqual(reopened.reserve_dispatch(129),(None,130))
            self.assertEqual(reopened.reserve_dispatch(130)[1],190)
            self.store.claim();self.store.fail('a','INTERNAL_ERROR')
            self.assertEqual(self.store.reserve_dispatch(101),(None,160))
    def test_expired_processing_lease(self):
        with patch('core.time.time',return_value=100):
            self.enqueue();self.store.claim()
        self.assertEqual(self.store.reserve_dispatch(1599),(None,1600))
        self.assertIsNotNone(self.store.reserve_dispatch(1600)[0])

if __name__=='__main__':unittest.main()
