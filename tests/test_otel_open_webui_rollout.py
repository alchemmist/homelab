import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('webui_rollout', ROOT / 'scripts/otel-open-webui-sdk-rollout.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class OpenWebuiRolloutTests(unittest.TestCase):
    def test_sdk_environment_trace_only_private_mtls_and_long_request_drain(self):
        env = module().sdk_environment()
        self.assertEqual(env['OTEL_OTLP_SPAN_EXPORTER'], 'http')
        self.assertEqual(env['OTEL_EXPORTER_OTLP_ENDPOINT'], 'https://10.250.0.3:44318/v1/traces')
        self.assertEqual(env['OTEL_EXPORTER_OTLP_INSECURE'], 'false')
        self.assertEqual(env['ENABLE_OTEL_METRICS'], 'false')
        self.assertEqual(env['OTEL_METRICS_EXPORTER'], 'none')
        self.assertEqual(env['OTEL_LOGS_EXPORTER'], 'none')
        self.assertEqual(env['OTEL_TRACES_SAMPLER'], 'always_on')
        self.assertEqual(env['UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN'], '7200')
        self.assertIn('/app/backend', env['PYTHONPATH'].split(':'))

    def test_only_kubernetes_empty_env_default_is_normalized(self):
        helper = module()
        self.assertTrue(helper.environment_matches({'name': 'EMPTY'}, 'EMPTY', ''))
        self.assertTrue(helper.environment_matches({'name': 'EMPTY', 'value': ''}, 'EMPTY', ''))
        self.assertFalse(helper.environment_matches({'name': 'EMPTY', 'valueFrom': {'secretKeyRef': {}}}, 'EMPTY', ''))
        self.assertFalse(helper.environment_matches({'name': 'EMPTY'}, 'EMPTY', 'true'))
        self.assertFalse(helper.environment_matches(None, 'EMPTY', ''))

    def test_maintained_overlay_matches_exact_three_source_files_and_env(self):
        helper = module()
        overlay = yaml.safe_load((ROOT / 'deploy/monitoring/otel-open-webui-sdk-values.yaml').read_text())['otel']
        self.assertEqual(overlay['sourceConfigMap'], helper.source_configmap_name())
        self.assertEqual(overlay['environment'], helper.sdk_environment())
        self.assertEqual(set(helper.source_data()), {'source_privacy.py', 'sitecustomize.py', 'open_webui_source_profile.py'})
        self.assertIn('os._exit(78)', helper.source_data()['sitecustomize.py'])
