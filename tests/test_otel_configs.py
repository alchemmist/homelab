"""Keep OpenTelemetry queue, retention, TLS, and sampling contracts."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1] / "deploy/monitoring/otel"


def config(name):
    return yaml.safe_load((ROOT / (name + ".yaml")).read_text())


class ObservabilityConfigTests(unittest.TestCase):
    """Check owned collector and store documents."""

    def test_persistent_queues_have_byte_not_request_limits(self) -> None:
        """Require persistent exporter queues to use bytes and file storage."""
        for name, limit in [
            ("agent", 128 * 2**20),
            ("cluster", 256 * 2**20),
            ("trace-gateway", 256 * 2**20),
        ]:
            document = config(name)
            assert document["extensions"]["file_storage"]["fsync"]
            for exporter in document["exporters"].values():
                queue = exporter["sending_queue"]
                assert queue["sizer"] == "bytes"
                assert queue["queue_size"] == limit
                assert queue["storage"] == "file_storage"

    def test_new_file_startup_records_and_historical_cut_are_separate(self) -> None:
        """Require new-file startup and the historical cut to stay separate."""
        assert config("agent")["receivers"]["filelog"]["start_at"] == "beginning"
        for name in ["agent", "cluster"]:
            document = config(name)
            processors = document["service"]["pipelines"]["logs"]["processors"]
            assert processors.index("filter/log-ingestion-cut") < len(processors) - 1
            condition = document["processors"]["filter/log-ingestion-cut"]["logs"]["log_record"][0]
            assert "time_unix_nano == 0" in condition
            assert "${env:OTEL_LOG_INGESTION_START_NS}" in condition

    def test_public_otlp_cannot_be_enabled_without_client_authentication(self) -> None:
        """Require public OTLP listeners to present client-authenticated TLS."""
        for name in ["cluster", "trace-gateway"]:
            for protocol in config(name)["receivers"]["otlp"]["protocols"].values():
                assert "${env:OTEL_BIND_IP}" in protocol["endpoint"]
                assert {"cert_file", "key_file", "client_ca_file"} <= set(protocol["tls"])
                assert set(protocol["tls"]) <= {
                    "cert_file",
                    "key_file",
                    "client_ca_file",
                    "reload_interval",
                }
                if "reload_interval" in protocol["tls"]:
                    assert protocol["tls"]["reload_interval"] == "1m"

    def test_production_ingestion_uses_the_service_identity(self) -> None:
        """The host dials the Service IP but verifies its DNS SAN without a DNS dependency."""
        repo = ROOT.parents[2]
        (play,) = yaml.safe_load(
            (repo / "ansible/playbooks/otel-production-agents.yml").read_text()
        )
        tasks = {task["name"]: task for task in play["tasks"]}
        unit = tasks["Install native tail sampling gateway"]["ansible.builtin.copy"]["content"]
        assert "Environment=OTEL_TEMPO_ENDPOINT={{ trace_gateway_service.stdout }}:4317" in unit
        assert (
            "--set=exporters.otlp/tempo.tls.server_name_override="
            "otel-tempo.cattle-monitoring-system.svc.cluster.local" in unit
        )
        for source in (
            "charts/prometheus/values.yaml",
            "deploy/monitoring/otel-production-values.yaml",
            "scripts/otel-production-cluster.py",
        ):
            text = (repo / source).read_text()
            assert "https://otel-loki.cattle-monitoring-system.svc:3100/otlp" in text
            assert "https://10.250.0.3:3100/otlp" not in text

    def test_retention_is_not_shortened(self) -> None:
        """Require Loki and Tempo retention periods to stay at their current lengths."""
        assert config("loki")["limits_config"]["retention_period"] == "336h"
        assert config("loki")["compactor"]["retention_enabled"]
        assert config("tempo")["compactor"]["compaction"]["block_retention"] == "168h"
        for name in ["loki", "tempo"]:
            assert (
                config(name)["server"]["http_tls_config"]["client_auth_type"]
                == "RequireAndVerifyClientCert"
            )

    def test_sampling_contract_includes_both_http_conventions(self) -> None:
        """Require tail sampling to match both HTTP status conventions."""
        sampling = config("trace-gateway")["processors"]["tail_sampling"]
        assert sampling["decision_wait"] == "30s"
        policies = {entry["name"]: entry for entry in sampling["policies"]}
        assert policies["errors"]["status_code"]["status_codes"] == ["ERROR"]
        slow_threshold_ms = 2000
        assert policies["slow"]["latency"]["threshold_ms"] == slow_threshold_ms
        other_sampling_percentage = 10
        assert (
            policies["other"]["probabilistic"]["sampling_percentage"] == other_sampling_percentage
        )
        for name, key in [
            ("http-5xx", "http.response.status_code"),
            ("legacy-http-5xx", "http.status_code"),
        ]:
            assert policies[name]["numeric_attribute"] == {
                "key": key,
                "min_value": 500,
                "max_value": 599,
            }
