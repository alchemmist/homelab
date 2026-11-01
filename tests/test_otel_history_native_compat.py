import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_compat', ROOT / 'scripts/otel-history-native-compat.py')
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class NativeHistoryQueryTests(unittest.TestCase):
    def test_exact_millisecond_query_does_not_round_through_seconds(self):
        response = io.BytesIO(json.dumps({'status': 'success', 'data': {'result': []}}).encode())
        with patch.object(compat.urllib.request, 'urlopen', return_value=response) as request:
            self.assertEqual(compat.query('metric', 1792652344262), [])
        url = request.call_args.args[0]
        self.assertIn('time=1792652344.262', url)
        self.assertIn('partial_response=false', url)
        self.assertIn('dedup=false', url)

    def test_partial_response_is_never_accepted_as_native_proof(self):
        response = io.BytesIO(json.dumps({'status': 'success', 'warnings': ['partial'], 'data': {'result': []}}).encode())
        with patch.object(compat.urllib.request, 'urlopen', return_value=response), self.assertRaises(ValueError):
            compat.query('metric', 1000)

    def test_no_native_repair_or_public_listener_is_used(self):
        text = (ROOT / 'scripts/otel-history-native-compat.py').read_text()
        self.assertNotIn('--repair', text)
        self.assertNotIn('0.0.0.0:', text)
        self.assertIn('--issues=index_known_issues', text)
        self.assertIn("point['metric'] != anchor['labels']", text)
        self.assertIn("struct.pack('>d'", text)
