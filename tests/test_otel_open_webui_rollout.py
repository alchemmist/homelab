import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "webui_rollout", ROOT / "scripts/otel-open-webui-sdk-rollout.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class OpenWebuiRolloutTests(unittest.TestCase):
    def test_sdk_environment_trace_only_private_mtls_and_long_request_drain(self):
        env = module().sdk_environment()
        assert env["OTEL_OTLP_SPAN_EXPORTER"] == "http"
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://10.250.0.3:44318/v1/traces"
        assert env["OTEL_EXPORTER_OTLP_INSECURE"] == "false"
        assert env["ENABLE_OTEL_METRICS"] == "false"
        assert env["OTEL_METRICS_EXPORTER"] == "none"
        assert env["OTEL_LOGS_EXPORTER"] == "none"
        assert env["OTEL_TRACES_SAMPLER"] == "always_on"
        assert env["UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN"] == "7200"
        assert "/app/backend" in env["PYTHONPATH"].split(":")

    def test_only_kubernetes_empty_env_default_is_normalized(self):
        helper = module()
        assert helper.environment_matches({"name": "EMPTY"}, "EMPTY", "")
        assert helper.environment_matches({"name": "EMPTY", "value": ""}, "EMPTY", "")
        assert not helper.environment_matches(
            {"name": "EMPTY", "valueFrom": {"secretKeyRef": {}}}, "EMPTY", ""
        )
        assert not helper.environment_matches({"name": "EMPTY"}, "EMPTY", "true")
        assert not helper.environment_matches(None, "EMPTY", "")

    def test_maintained_overlay_matches_exact_three_source_files_and_env(self):
        helper = module()
        overlay = yaml.safe_load(
            (ROOT / "deploy/monitoring/otel-open-webui-sdk-values.yaml").read_text()
        )["otel"]
        assert overlay["sourceConfigMap"] == helper.source_configmap_name()
        assert overlay["environment"] == helper.sdk_environment()
        assert set(helper.source_data()) == {
            "source_privacy.py",
            "sitecustomize.py",
            "open_webui_source_profile.py",
        }
        assert "os._exit(78)" in helper.source_data()["sitecustomize.py"]
