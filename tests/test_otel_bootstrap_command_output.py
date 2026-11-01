import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def module():
    spec = importlib.util.spec_from_file_location('bootstrap_output', Path(__file__).resolve().parents[1] / 'scripts/otel-production-bootstrap.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CommandOutputTests(unittest.TestCase):
    def test_successful_delete_is_not_retried_due_to_text_output(self):
        helper = module()
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='job.batch "owned" deleted\n')) as call:
            self.assertIsNone(helper.kube('-n', 'llm', 'delete', 'job', 'owned', '--wait=false'))
            self.assertEqual(call.call_count, 1)

    def test_failed_delete_still_fails_closed_without_response_disclosure(self):
        helper = module()
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='sensitive response')):
            with self.assertRaisesRegex(RuntimeError, 'sensitive response omitted'):
                helper.kube('delete', 'job', 'owned')

    def test_resource_named_delete_does_not_disable_json_parsing(self):
        helper = module()
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{"kind":"Pod"}')):
            self.assertEqual(helper.kube('-n', 'llm', 'get', 'pod', 'delete', '-o', 'json'), {'kind': 'Pod'})
