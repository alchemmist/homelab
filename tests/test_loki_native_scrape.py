"""Owned Loki self-monitoring stays additive, idempotent, and fail-closed."""

import copy
import importlib.util
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scrape", ROOT / "scripts/otel-scrape-config.py")
assert spec is not None
assert spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LokiNativeScrapeTests(unittest.TestCase):
    """The native Loki target is appended once and rejected when it conflicts."""

    def test_additive_idempotent_verified_mtls(self) -> None:
        """Verify a missing Loki job is appended without mutating the caller input."""
        original = {"scrape_configs": [{"job_name": "existing", "static_configs": []}]}
        before = copy.deepcopy(original)
        result = m.add_logging_self_monitoring(original)
        assert original == before
        assert result["scrape_configs"][:-1] == before["scrape_configs"]
        assert m.add_logging_self_monitoring(result) == result
        job = result["scrape_configs"][-1]
        assert (job["scrape_interval"], job["scrape_timeout"]) == ("5s", "4s")
        assert job["scheme"] == "https"
        assert not job["tls_config"]["insecure_skip_verify"]
        assert job["tls_config"]["server_name"] == "otel-loki.cattle-monitoring-system.svc"
        assert job["static_configs"][0]["labels"]["scrape_owner"] == "otel-cluster"
        assert job["tls_config"]["cert_file"] == "/etc/otel/tls/client.crt"
        assert job["tls_config"]["key_file"] == "/etc/otel/tls/client.key"

    def test_conflict_fails_closed(self) -> None:
        """Verify an incompatible existing Loki job fails before acceptance."""
        with pytest.raises(ValueError, match="Conflicting Loki self-monitoring target"):
            m.add_logging_self_monitoring({"scrape_configs": [{"job_name": "otel-logging/loki"}]})


if __name__ == "__main__":
    unittest.main()
