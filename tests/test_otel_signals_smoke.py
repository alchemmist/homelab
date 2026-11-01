import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('signals_smoke', ROOT / 'scripts/otel-signals-smoke.py')
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class SignalSmokeTests(unittest.TestCase):
    def test_trace_fixtures_cover_sampling_categories_with_unique_ids(self):
        body, groups = SMOKE.trace_fixtures(10**18)
        spans = body['resourceSpans'][0]['scopeSpans'][0]['spans']
        self.assertEqual(len(spans), 232)
        self.assertEqual(len({span['traceId'] for span in spans}), 232)
        self.assertEqual({key: len(value) for key, value in groups.items()},
                         {'error': 8, 'http5xx': 8, 'legacy5xx': 8, 'slow': 8, 'normal': 200})
        self.assertEqual(sum(span['status']['code'] == 2 for span in spans), 8)

    def test_slow_trace_duration_exceeds_the_native_sampling_threshold(self):
        body, groups = SMOKE.trace_fixtures(10**18)
        for span in body['resourceSpans'][0]['scopeSpans'][0]['spans']:
            duration = int(span['endTimeUnixNano']) - int(span['startTimeUnixNano'])
            self.assertEqual(duration, 3_000_000_000 if span['traceId'] in groups['slow'] else 100_000_000)

    def test_logs_include_separate_zero_historical_and_fresh_cases(self):
        now = 10**18
        records = SMOKE.logs_fixture(now)['resourceLogs'][0]['scopeLogs'][0]['logRecords']
        self.assertEqual([int(record['timeUnixNano']) for record in records], [now, 0, now - 3600 * 10**9])
        self.assertIn(SMOKE.SECRET, records[0]['body']['stringValue'])
        self.assertTrue(SMOKE.SERVICE.startswith('otel-isolated-'))
