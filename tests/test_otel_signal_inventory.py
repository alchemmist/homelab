import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('signal_inventory', ROOT / 'scripts/otel-signal-inventory.py')
SIGNALS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIGNALS)


class SignalInventoryTests(unittest.TestCase):
    def test_observations_are_not_a_capacity_approval(self):
        pods = {'windowSeconds': 600, 'sources': [
            {'measurementAvailable': True, 'bytes': 1200, 'lines': 10, 'truncated': False}]}
        journals = {node: {'systemJournalAccessVerified': True} for node in ['socrat-0', 'socrat-1', 'socrat-2', 'socrat-3']}
        result = SIGNALS.summarize(pods, journals)
        self.assertEqual(result['observedContainerBytesPerSecond'], 2)
        self.assertTrue(result['observedSourcesReadable'])
        self.assertFalse(result['logRatesComplete'])
        self.assertFalse(result['traceRateMeasured'])
        self.assertFalse(result['diskProjectionVerified'])
        self.assertFalse(result['rawLogBodiesPersisted'])
        self.assertTrue(result['countsAreLowerBounds'])

    def test_truncation_unavailable_logs_and_journal_gaps_are_explicit(self):
        pods = {'windowSeconds': 600, 'sources': [
            {'measurementAvailable': True, 'bytes': 1048576, 'lines': 10, 'truncated': True},
            {'measurementAvailable': False, 'reason': 'api-unavailable'}]}
        result = SIGNALS.summarize(pods, {'socrat-0': {'systemJournalAccessVerified': False}})
        self.assertEqual(result['truncatedContainerCount'], 1)
        self.assertEqual(result['unavailableContainerCount'], 1)
        self.assertFalse(result['observedSourcesReadable'])

    def test_empty_sources_and_missing_nodes_cannot_pass(self):
        result = SIGNALS.summarize({'windowSeconds': 600, 'sources': []}, {})
        self.assertFalse(result['observedSourcesReadable'])

    def test_zero_measurement_window_is_rejected(self):
        with self.assertRaises(ValueError):
            SIGNALS.summarize({'windowSeconds': 0, 'sources': []}, {})

    def test_probe_returns_counts_not_log_contents_or_env_values(self):
        self.assertNotIn("'body':", SIGNALS.POD_PROBE)
        self.assertIn("'bytes':size", SIGNALS.POD_PROBE)
        self.assertIn("entry['name']", SIGNALS.POD_PROBE)
        self.assertNotIn("entry['value']", SIGNALS.POD_PROBE)
        self.assertIn('stderr=subprocess.DEVNULL', SIGNALS.POD_PROBE)
        compile(SIGNALS.POD_PROBE, 'pod_probe', 'exec')
        compile(SIGNALS.JOURNAL_PROBE, 'journal_probe', 'exec')


if __name__ == '__main__':
    unittest.main()


class PrivilegedJournalTests(unittest.TestCase):
    def evidence(self, directory, **updates):
        from datetime import datetime, timezone
        document = {'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
                    'windowSeconds': 600, 'records': 2, 'serializedBytes': 100, 'messageBytes': 20,
                    'invalidRecords': 0, 'rootAccessVerified': True, 'systemJournalReadSucceeded': True,
                    'truncated': False, 'rawLogBodiesPersisted': False, 'productionModified': False}
        document.update(updates)
        for node in ['socrat-0', 'socrat-1', 'socrat-2', 'socrat-3']:
            path = directory / (node + '.json')
            path.write_text(json.dumps(document))
            path.chmod(0o600)

    def test_merges_only_whitelisted_counts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.evidence(directory, MESSAGE='not-persisted-in-report')
            result = SIGNALS.privileged_journals(directory)
            self.assertEqual(len(result), 4)
            self.assertTrue(all(item['systemJournalAccessVerified'] for item in result.values()))
            self.assertNotIn('not-persisted-in-report', str(result))

    def test_stale_or_incomplete_evidence_is_rejected(self):
        import tempfile
        for update in [{'collectedAt': '2020-01-01T00:00:00+00:00'}, {'truncated': True},
                       {'rootAccessVerified': False}, {'invalidRecords': 1}, {'records': True}]:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                self.evidence(directory, **update)
                with self.assertRaises(ValueError):
                    SIGNALS.privileged_journals(directory)

    def test_public_evidence_file_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.evidence(directory)
            (directory / 'socrat-0.json').chmod(0o644)
            with self.assertRaises(ValueError):
                SIGNALS.privileged_journals(directory)

class ActiveLogSourceTests(unittest.TestCase):
    def test_historical_unavailable_sources_are_not_hidden_by_active_counts(self):
        data = {'windowSeconds': 600, 'sources': [
            {'containerState': 'running', 'measurementAvailable': True, 'bytes': 100, 'truncated': False},
            {'containerState': 'terminated', 'measurementAvailable': False}]}
        report = SIGNALS.summarize(data, {})
        self.assertEqual(report['unavailableContainerCount'], 1)
        self.assertEqual(report['activeUnavailableContainerCount'], 0)
        self.assertTrue(report['activeLogAPIsReadable'])
        self.assertFalse(report['observedSourcesReadable'])
        self.assertFalse(report['logRatesComplete'])

    def test_missing_active_or_unknown_state_does_not_pass(self):
        for sources in [[{'containerState': 'running', 'measurementAvailable': False}],
                        [{'containerState': 'running', 'measurementAvailable': True, 'bytes': 1, 'truncated': False},
                         {'measurementAvailable': False}]]:
            self.assertFalse(SIGNALS.summarize({'windowSeconds': 600, 'sources': sources}, {})['activeLogAPIsReadable'])
