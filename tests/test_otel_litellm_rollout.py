import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('litellm_rollout', ROOT / 'scripts/otel-litellm-sdk-rollout.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiteLLMRolloutTests(unittest.TestCase):
    def test_only_callback_and_source_privacy_settings_change(self):
        module = load()
        before = {'model_list': [{'model_name': 'existing', 'litellm_params': {'api_key': 'os.environ.EXISTING'}}],
                  'general_settings': {'master_key': 'os.environ.MASTER'},
                  'litellm_settings': {'callbacks': ['prometheus'], 'require_auth_for_metrics_endpoint': True, 'num_retries': 0}}
        untouched = copy.deepcopy(before)
        after = module.configuration(before)
        self.assertEqual(before, untouched)
        self.assertEqual(after['model_list'], before['model_list'])
        self.assertEqual(after['general_settings'], before['general_settings'])
        self.assertEqual(after['litellm_settings']['callbacks'], ['prometheus', 'otel'])
        self.assertTrue(after['litellm_settings']['require_auth_for_metrics_endpoint'])
        self.assertTrue(after['litellm_settings']['turn_off_message_logging'])

    def test_missing_existing_metrics_callback_is_rejected(self):
        with self.assertRaises(ValueError):
            load().configuration({'litellm_settings': {'callbacks': []}})

    def test_sdk_does_not_create_second_metrics_or_log_owner(self):
        environment = load().sdk_environment()
        self.assertEqual(environment['OTEL_TRACES_SAMPLER'], 'always_on')
        self.assertEqual(environment['OTEL_METRICS_EXPORTER'], 'none')
        self.assertEqual(environment['OTEL_LOGS_EXPORTER'], 'none')
        self.assertEqual(environment['OTEL_EXPORTER_OTLP_INSECURE'], 'false')
        self.assertEqual(environment['OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT'], 'NO_CONTENT')

    def test_apply_is_blocked_before_cluster_access_without_verified_reload(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            evidence = home / 'deploy/monitoring/migration-evidence'
            evidence.mkdir(parents=True)
            source = ROOT / 'deploy/monitoring/migration-evidence/litellm-proxy-sdk-canary-20261101.json'
            (evidence / source.name).write_text(source.read_text())
            (evidence.parent / 'otel-application-scope.json').write_text(json.dumps({'dedicatedClientCertificates': {}}))
            output = home / 'Library/Application Support/homelab/otel-controller/must-not-exist'
            with patch.object(module, 'ROOT', home), patch.object(module.Path, 'home', return_value=home), patch.object(module.BOOTSTRAP, 'kube') as kube:
                with self.assertRaisesRegex(ValueError, 'renewable SDK credential reload'):
                    module.run(output, True)
                kube.assert_not_called()
            self.assertFalse(output.exists())
