"""Offline contracts for the native agent; no host log bodies are read."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class AgentLoggingTests(unittest.TestCase):
    def setUp(self):
        self.agent = yaml.safe_load((ROOT / 'deploy/monitoring/otel/agent.yaml').read_text())

    def test_rotation_and_restart_contract(self):
        receiver = self.agent['receivers']['filelog']
        self.assertEqual(receiver['operators'][0]['type'], 'container')
        self.assertEqual(receiver['start_at'], 'beginning')
        self.assertEqual(receiver['storage'], 'file_storage')
        self.assertEqual(receiver['retry_on_failure']['max_elapsed_time'], '0s')
        self.assertEqual(self.agent['receivers']['journald']['storage'], 'file_storage')
        self.assertTrue(self.agent['extensions']['file_storage']['fsync'])

    def test_privacy_precedes_durable_log_queue_without_async_batch(self):
        pipeline = self.agent['service']['pipelines']['logs']
        self.assertIn('transform/log-privacy', pipeline['processors'])
        self.assertNotIn('batch/logs', pipeline['processors'])
        self.assertEqual(pipeline['exporters'], ['otlp/logs'])
        queue = self.agent['exporters']['otlp/logs']['sending_queue']
        self.assertEqual(queue['sizer'], 'bytes')
        self.assertEqual(queue['queue_size'], 128 * 2**20)
        self.assertTrue(queue['block_on_overflow'])
        self.assertEqual(queue['storage'], 'file_storage')
        self.assertEqual(self.agent['service']['pipelines']['metrics']['exporters'], ['otlp'])

    def test_common_schema_and_priority_mapping(self):
        identity = str(self.agent['processors']['transform/log-identity'])
        for field in ['service.name', 'k8s.namespace.name', 'severity', 'unknown']:
            self.assertIn(field, identity)
        self.assertEqual(self.agent['processors']['groupbyattrs/log-severity']['keys'], ['severity'])
        self.assertIn('groupbyattrs/log-severity', self.agent['service']['pipelines']['logs']['processors'])
        self.assertIn('PRIORITY', str(self.agent['processors']['transform/journal']))
        self.assertIn('host.name', str(self.agent['processors']['resource']))

    def test_serial_rollout_validates_before_handler_flush(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/otel-production-agents.yml').read_text())[0]
        self.assertEqual(play['serial'], 1)
        names = [task['name'] for task in play['tasks']]
        self.assertLess(names.index('Validate installed host agent configuration before restart'),
                        names.index('Apply validated agent changes before advancing serial rollout'))


if __name__ == '__main__':
    unittest.main()
