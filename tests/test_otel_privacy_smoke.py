"""Privacy smoke tests for the OpenTelemetry pipeline."""

import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "privacy_smoke", ROOT / "ansible/scripts/otel-privacy-smoke.py"
)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class PrivacySmokeTests(unittest.TestCase):
    """Ensure the smoke configuration never touches production sources."""

    def test_smoke_configuration_cannot_read_production_sources(self) -> None:
        """Smoke configuration cannot read production sources."""
        source = {
            "receivers": {
                "prometheus": {"config": "production"},
                "filelog": {"include": ["/var/log/pods/*"]},
                "otlp": {
                    "protocols": {
                        "http": {
                            "endpoint": "production:4318",
                            "tls": {"client_ca_file": "validation-ca"},
                        }
                    }
                },
            },
            "processors": {"privacy": {}, "unused": {}},
            "exporters": {"production": {"endpoint": "production"}},
            "extensions": {"file_storage": {}, "health_check": {}},
            "service": {
                "extensions": ["file_storage", "health_check"],
                "pipelines": {
                    "logs": {
                        "processors": ["privacy"],
                        "receivers": ["otlp"],
                        "exporters": ["production"],
                    },
                    "metrics": {"receivers": ["prometheus"]},
                },
            },
        }
        before = json.dumps(source, sort_keys=True)
        result = SMOKE.isolated_config(source, Path("/private/synthetic.json"))
        assert set(result["receivers"]) == {"otlp"}
        assert set(result["service"]["pipelines"]) == {"logs"}
        assert set(result["exporters"]) == {"file"}
        assert result["receivers"]["otlp"]["protocols"]["http"]["endpoint"] == "127.0.0.1:14318"
        assert (
            result["receivers"]["otlp"]["protocols"]["http"]["tls"]["client_ca_file"]
            == "validation-ca"
        )
        assert json.dumps(source, sort_keys=True) == before

    def test_host_network_namespace_is_rejected_before_startup(self) -> None:
        """Host network namespace is rejected before startup."""
        with patch.object(SMOKE.os, "readlink", return_value="net:[same]"):
            with pytest.raises(ValueError, match="separate network namespace"):
                SMOKE.run(Path("/unused"), Path("/unused"), Path("/unused"), Path("/unused"))

    def test_otlp_partial_rejection_is_a_failure(self) -> None:
        """Otlp partial rejection is a failure."""
        with (
            patch.object(
                SMOKE.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b'{"partialSuccess":{"rejectedLogRecords":"1"}}'),
            ),
            pytest.raises(ValueError, match="rejected"),
        ):
            SMOKE.send(None, {})
