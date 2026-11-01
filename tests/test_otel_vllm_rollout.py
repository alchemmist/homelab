import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('vllm_rollout', ROOT / 'scripts/otel-vllm-sdk-rollout.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class VllmRolloutTests(unittest.TestCase):
    def test_only_native_trace_flag_added_model_args_unmodified(self):
        helper = module()
        original = ['model', '--max-model-len', '114688', '--gpu-memory-utilization', '.95']
        updated = helper.trace_arguments(original)
        self.assertEqual(updated[:-2], original)
        self.assertEqual(helper.trace_arguments(updated), updated)
        self.assertEqual(len(original), 5)
        for args in [['model', '--otlp-traces-endpoint=http://public'], ['model', '--otlp-traces-endpoint', 'grpc://insecure']]:
            with self.assertRaises(ValueError):helper.trace_arguments(args)

    def test_exact_mtls_protocol_always_on_no_duplicate_signals(self):
        env = module().sdk_environment()
        self.assertEqual(env['OTEL_EXPORTER_OTLP_TRACES_PROTOCOL'], 'http/protobuf')
        self.assertEqual(env['OTEL_EXPORTER_OTLP_INSECURE'], 'false')
        self.assertEqual(env['OTEL_TRACES_SAMPLER'], 'always_on')
        self.assertEqual(env['OTEL_METRICS_EXPORTER'], 'none')
        self.assertEqual(env['OTEL_LOGS_EXPORTER'], 'none')
        self.assertEqual(env['OTEL_EXPORTER_OTLP_HEADERS'], 'Connection=close')

    def test_maintained_overlay_matches_exact_guard_sources_and_environment(self):
        helper = module()
        overlay = yaml.safe_load((ROOT / 'deploy/monitoring/otel-vllm-sdk-values.yaml').read_text())['otel']
        self.assertEqual(overlay['sourceConfigMap'], helper.source_configmap_name())
        self.assertEqual(overlay['environment'], helper.sdk_environment())

    def test_sitecustomize_refuses_startup_without_dumping_failure_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'sitecustomize.py').write_text((ROOT / 'deploy/monitoring/otel/vllm-sitecustomize.py').read_text())
            (path / 'source_privacy.py').write_text("raise RuntimeError('synthetic-private-credential')\n")
            env = dict(os.environ, PYTHONPATH=directory)
            result = subprocess.run([sys.executable, '-c', "print('UNSAFE_APPLICATION_STARTED')"], env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 78)
            self.assertNotIn('synthetic-private-credential', result.stderr)
            self.assertNotIn('UNSAFE_APPLICATION_STARTED', result.stdout)
