import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/reconcile-active-logging.py'

class ReconciliationTests(unittest.TestCase):
    def run_case(self, names, counts, aligned=True):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            pods = {'items': [{'metadata': {'namespace': 'cattle-monitoring-system', 'name': name}, 'spec': {'containers': [{'name': container}]}, 'status': {'phase': 'Running', 'containerStatuses': [{'name': container, 'state': {'running': {}}}]}} for name, container in names]}
            metadata = {'observedAtUnix': 1000, 'evaluationTimeFixed': aligned, '600': [], '3600': []}
            sources = {'start': 400, 'end': 1000, 'sources': [{'namespace': 'cattle-monitoring-system', 'pod': name, 'container': container, 'status': 'ok', 'count': count} for (name, container), count in zip(names, counts)]}
            for file, data in [('pods', pods), ('meta', metadata), ('counts', sources)]:
                (p / file).write_text(json.dumps(data))
            for n in range(4):
                (p / f'host{n}.txt').write_text('JOURNAL_COUNTS {}')
            result = subprocess.run([sys.executable, str(SCRIPT), '--pods', str(p/'pods'), '--metadata', str(p/'meta'), '--source-counts', str(p/'counts'), '--host-prefix', str(p/'host'), '--output', str(p/'out')], capture_output=True, text=True)
            return result, json.loads((p/'out.json').read_text()) if result.returncode == 0 else None

    def test_silent_window_is_explicit_not_loss(self):
        result, report = self.run_case([('app', 'app')], [0])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report['sources'][0]['cause'], 'no-heartbeat-exclusion-no-stdout-in-window')
        self.assertEqual(report['sources'][0]['normalization'], 'unobserved')
        self.assertIsNone(report['sources'][0]['emits'])

    def test_only_actual_collector_excluded_not_backends(self):
        _, report = self.run_case([('prometheus-kube-prometheus-stack-prometheus-0', 'otel-cluster'), ('otel-loki-123', 'loki'), ('otel-tempo-123', 'tempo')], [3, 3, 3])
        self.assertEqual(report['sources'][0]['cause'], 'agent-self-logs-explicitly-excluded')
        self.assertTrue(all(r['cause'] == 'stdout-emission-without-receipt-investigate' for r in report['sources'][1:]))

    def test_unaligned_windows_fail_closed(self):
        result, report = self.run_case([('app', 'app')], [0], aligned=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not aligned', result.stderr)
        self.assertIsNone(report)
