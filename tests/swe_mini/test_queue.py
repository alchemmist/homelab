"""Exercise real queue state transitions with API/model boundaries mocked."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2] / 'services/swe-mini'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


policy = module('policy')
with patch.dict(sys.modules, {'policy': policy, 'jwt': MagicMock(), 'requests': MagicMock(), 'kubernetes': MagicMock()}), patch.dict(os.environ, {'STATE_PATH': ':memory:'}):
    c = module('controller')


class QueueTransitions(unittest.TestCase):
    def setUp(self):
        c.DB.execute('DELETE FROM runs')
        c.DB.execute("INSERT INTO runs (id,lane,revision,state,job,created) VALUES ('test','backend',?,'work','test-work',0)", ('a' * 40,))
        c.DB.commit()
        c.CORE = MagicMock()
        c.BATCH = MagicMock()
        c.BATCH.read_namespaced_job.return_value.status = SimpleNamespace(succeeded=1, failed=0)
        c.CORE.list_namespaced_pod.return_value.items = [SimpleNamespace(metadata=SimpleNamespace(name='worker'))]
        self.result = {'revision': 'a' * 40, 'agent_status': 'Submitted', 'agent_rc': 0, 'checks': {'backend': 0}, 'baseline': {'backend': 0}, 'changes': [], 'report': 'evidence'}

    def state(self):
        return c.DB.execute("SELECT state FROM runs WHERE id='test'").fetchone()[0]

    def tick(self):
        c.CORE.read_namespaced_pod_log.return_value = policy.encode_result(self.result, c.signing_key('test', self.state()))
        c.tick()

    def test_clean_no_finding_done(self):
        self.tick()
        self.assertEqual(self.state(), 'done')

    def test_failed_baseline_never_published(self):
        self.result['baseline']['backend'] = 1
        self.tick()
        self.assertEqual(self.state(), 'rejected')

    def test_failed_postcheck_rejected(self):
        self.result['checks']['backend'] = 1
        self.tick()
        self.assertEqual(self.state(), 'rejected')

    def test_model_limit_not_completion(self):
        self.result['agent_status'] = 'LimitsExceeded'
        self.tick()
        self.assertEqual(self.state(), 'failed')

    def test_wrong_revision_failed(self):
        self.result['revision'] = 'b' * 40
        self.tick()
        self.assertEqual(self.state(), 'failed')

    def test_candidate_requires_review(self):
        self.result['changes'] = [{'path': 'server/app/a.py', 'content': base64.b64encode(b'x=1\n').decode()}]
        with patch.object(c, 'start_job') as start:
            self.tick()
            self.assertEqual(start.call_args.args[1], 'review')
            self.assertNotEqual(self.state(), 'publishing')

    def test_review_rejection(self):
        c.save('test', state='review')
        self.result['review'] = {'approved': False, 'reason': 'reproduction fails'}
        self.tick()
        self.assertEqual(self.state(), 'rejected')

    def test_review_approval_queues_publication(self):
        c.save('test', state='review')
        self.result['review'] = {'approved': True, 'reason': 'test reproduced'}
        self.tick()
        self.assertEqual(self.state(), 'publishing')
        c.CORE.delete_namespaced_config_map.assert_called_once()

    def test_no_unstructured_log_completion(self):
        c.CORE.read_namespaced_pod_log.return_value = 'I am done!'
        c.tick()
        self.assertEqual(self.state(), 'failed')

    def test_pending_job_is_not_restarted(self):
        c.BATCH.read_namespaced_job.return_value.status = SimpleNamespace(succeeded=None, failed=None)
        with patch.object(c, 'start_job') as start:
            c.tick()
            start.assert_not_called()
        self.assertEqual(self.state(), 'work')

    def test_expired_job_fails_and_next_task_is_admitted(self):
        class NotFound(Exception):
            status = 404
        c.client.ApiException = NotFound
        c.BATCH.read_namespaced_job.side_effect = NotFound()
        c.tick()
        self.assertEqual(self.state(), 'failed')
        with patch.object(c, 'github', side_effect=[[], {'sha': 'b' * 40}]):
            c.tick()
        self.assertEqual(c.DB.execute("SELECT count(*) FROM runs WHERE state='queued'").fetchone()[0], 1)

    def test_missing_terminal_pod_does_not_wedge_queue(self):
        c.CORE.list_namespaced_pod.return_value.items = []
        c.tick()
        self.assertEqual(self.state(), 'failed')

    def test_persisted_queued_run_resumes(self):
        c.save('test', state='queued')
        with patch.object(c, 'start_job') as start:
            c.tick()
            self.assertEqual(start.call_args.args[1], 'work')


if __name__ == '__main__':
    unittest.main()
