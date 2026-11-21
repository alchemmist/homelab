"""Tests for the OpenTelemetry Open WebUI rollout."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module() -> ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(
        "webui_rollout", ROOT / "scripts/otel-open-webui-sdk-rollout.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_stale_source_receipt_refuses_candidate_before_cluster_access(
    tmp_path, monkeypatch
) -> None:
    """An offline candidate digest is not proof that the runtime may change."""
    helper = module()
    candidate = helper.source_data()
    previous = {**candidate, "sitecustomize.py": candidate["sitecustomize.py"] + "# stale\n"}
    evidence = tmp_path / "deploy/monitoring/migration-evidence"
    evidence.mkdir(parents=True)
    (evidence / "open-webui-sdk-early-bootstrap-20261101.json").write_text(
        json.dumps(
            {
                "sourceConfigMapData": previous,
                "source": {
                    "success": True,
                    "earlyBootstrapRequiredWithoutManualFallback": True,
                    "unsafeAndDuplicateInstrumentorsDisabled": {"fixture": True},
                },
                "backend": {"success": True},
            }
        )
    )
    (evidence / "open-webui-sdk-leaf-renewal-20261101.json").write_text(
        json.dumps(
            {
                "source": {
                    "success": True,
                    "sameNativeProviderAndExporterInstance": True,
                    "sdkLeafReloadVerified": True,
                },
                "rotation": {"clientKeypairRotationVerified": True},
                "backend": [{"success": True}, {"success": True}],
            }
        )
    )
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper, "source_data", lambda: candidate)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(helper.os, "umask", lambda _mask: None)
    monkeypatch.setattr(helper.BOOTSTRAP, "kube", lambda *_args: pytest.fail("cluster access"))
    output = tmp_path / "Library/Application Support/homelab/otel-controller/candidate"
    with pytest.raises(ValueError, match="Exact source/profile/bootstrap/renewal/backend gates"):
        helper.run(output, apply=False)
    assert not output.exists()


class OpenWebuiRolloutTests(unittest.TestCase):
    """Validate the Open WebUI rollout's SDK tracing environment."""

    def test_sdk_environment_trace_only_private_mtls_and_long_request_drain(self) -> None:
        """Sdk environment trace only private mtls and long request drain."""
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

    def test_only_kubernetes_empty_env_default_is_normalized(self) -> None:
        """Only kubernetes empty env default is normalized."""
        helper = module()
        assert helper.environment_matches({"name": "EMPTY"}, "EMPTY", "")
        assert helper.environment_matches({"name": "EMPTY", "value": ""}, "EMPTY", "")
        assert not helper.environment_matches(
            {"name": "EMPTY", "valueFrom": {"secretKeyRef": {}}}, "EMPTY", ""
        )
        assert not helper.environment_matches({"name": "EMPTY"}, "EMPTY", "true")
        assert not helper.environment_matches(None, "EMPTY", "")

    def test_maintained_overlay_matches_exact_three_source_files_and_env(self) -> None:
        """Maintained overlay matches exact three source files and env."""
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
