"""Tests for the OpenTelemetry LiteLLM rollout."""

import copy
import importlib.util
import types
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load() -> types.ModuleType:
    """Test behavior for load."""
    spec = importlib.util.spec_from_file_location(
        "litellm_rollout", ROOT / "scripts/otel-litellm-sdk-rollout.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiteLLMRolloutTests(unittest.TestCase):
    """Callback privacy, exporter pins, and refusal before cluster access."""

    def test_only_callback_and_source_privacy_settings_change(self) -> None:
        """Preserve model settings while adding only the otel callback and privacy flag."""
        module = load()
        before = {
            "model_list": [
                {
                    "model_name": "existing",
                    "litellm_params": {"api_key": "os.environ.EXISTING"},
                }
            ],
            "general_settings": {"master_key": "os.environ.MASTER"},
            "litellm_settings": {
                "callbacks": ["prometheus"],
                "require_auth_for_metrics_endpoint": True,
                "num_retries": 0,
            },
        }
        untouched = copy.deepcopy(before)
        after = module.configuration(before)
        assert before == untouched
        assert after["model_list"] == before["model_list"]
        assert after["general_settings"] == before["general_settings"]
        assert after["litellm_settings"]["callbacks"] == ["prometheus", "otel"]
        assert after["litellm_settings"]["require_auth_for_metrics_endpoint"]
        assert after["litellm_settings"]["turn_off_message_logging"]

    def test_missing_existing_metrics_callback_is_rejected(self) -> None:
        """Reject a configuration that drops the Prometheus callback."""
        with self.assertRaises(ValueError):
            load().configuration({"litellm_settings": {"callbacks": []}})

    def test_sdk_does_not_create_second_metrics_or_log_owner(self) -> None:
        """Keep metrics and log exporters disabled on the SDK environment."""
        environment = load().sdk_environment()
        assert environment["OTEL_TRACES_SAMPLER"] == "always_on"
        assert environment["OTEL_METRICS_EXPORTER"] == "none"
        assert environment["OTEL_LOGS_EXPORTER"] == "none"
        assert environment["OTEL_EXPORTER_OTLP_INSECURE"] == "false"
        assert environment["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "NO_CONTENT"

    def test_apply_is_blocked_before_cluster_access_without_verified_reload(
        self,
    ) -> None:
        """Refuse apply before any cluster call when SDK reload is not verified."""
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            evidence = home / "deploy/monitoring/migration-evidence"
            evidence.mkdir(parents=True)
            (evidence.parent / "otel-application-scope.json").write_text(
                json.dumps({"dedicatedClientCertificates": {}})
            )
            output = home / "Library/Application Support/homelab/otel-controller/must-not-exist"
            with (
                patch.object(module, "ROOT", home),
                patch.object(module.Path, "home", return_value=home),
                patch.object(module.BOOTSTRAP, "kube") as kube,
            ):
                with self.assertRaisesRegex(ValueError, "renewable SDK credential reload"):
                    module.run(output, True)
                kube.assert_not_called()
            assert not output.exists()
