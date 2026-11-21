"""Keep OpenTelemetry queue, retention, TLS, and sampling contracts."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1] / "deploy/monitoring/otel"


def config(name: str) -> dict[str, object]:
    document: object = yaml.safe_load((ROOT / (name + ".yaml")).read_text())
    assert isinstance(document, dict)
    return document


def _mapping(value: object) -> dict[str, object]:
    """Reach inside mappings the shipped configs already validate."""
    assert isinstance(value, dict)
    return value


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _text(value: object) -> str:
    assert isinstance(value, str)
    return value


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
            assert _mapping(_mapping(document["extensions"])["file_storage"])["fsync"]
            for exporter in _mapping(document["exporters"]).values():
                queue = _mapping(_mapping(exporter)["sending_queue"])
                assert queue["sizer"] == "bytes"
                assert queue["queue_size"] == limit
                assert queue["storage"] == "file_storage"

    def test_new_file_startup_records_and_historical_cut_are_separate(self) -> None:
        """Require new-file startup and the historical cut to stay separate."""
        filelog = _mapping(_mapping(config("agent")["receivers"])["filelog"])
        assert filelog["start_at"] == "beginning"
        for name in ["agent", "cluster"]:
            document = config(name)
            pipelines = _mapping(_mapping(document["service"])["pipelines"])
            processors = _list(_mapping(pipelines["logs"])["processors"])
            assert processors.index("filter/log-ingestion-cut") < len(processors) - 1
            cut = _mapping(_mapping(document["processors"])["filter/log-ingestion-cut"])
            condition = _text(_list(_mapping(cut["logs"])["log_record"])[0])
            assert "time_unix_nano == 0" in condition
            assert "${env:OTEL_LOG_INGESTION_START_NS}" in condition

    def test_public_otlp_cannot_be_enabled_without_client_authentication(self) -> None:
        """Require public OTLP listeners to present client-authenticated TLS."""
        for name in ["cluster", "trace-gateway"]:
            receivers = _mapping(config(name)["receivers"])
            protocols = _mapping(_mapping(receivers["otlp"])["protocols"])
            for protocol in protocols.values():
                listener = _mapping(protocol)
                assert "${env:OTEL_BIND_IP}" in _text(listener["endpoint"])
                tls = _mapping(listener["tls"])
                assert {"cert_file", "key_file", "client_ca_file"} <= set(tls)
                assert set(tls) <= {"cert_file", "key_file", "client_ca_file", "reload_interval"}
                if "reload_interval" in tls:
                    assert tls["reload_interval"] == "1m"

    def test_production_ingestion_uses_the_service_identity(self) -> None:
        """The host dials the Service IP but verifies its DNS SAN without a DNS dependency."""
        repo = ROOT.parents[2]
        (play,) = yaml.safe_load(
            (repo / "ansible/playbooks/otel-production-agents.yml").read_text()
        )
        tasks = {task["name"]: task for task in play["tasks"]}
        unit = tasks["Install native tail sampling gateway"]["ansible.builtin.copy"]["content"]
        assert "Environment=OTEL_TEMPO_ENDPOINT={{ trace_gateway_service.stdout }}:4317" in unit
        assert "--set=exporters.otlp/tempo.tls.server_name_override=" "otel-tempo.cattle-monitoring-system.svc.cluster.local" in unit
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
        loki = config("loki")
        assert _mapping(loki["limits_config"])["retention_period"] == "336h"
        retention = _mapping(loki["compactor"])["retention_enabled"]
        assert isinstance(retention, bool)
        assert retention
        tempo = _mapping(_mapping(config("tempo")["compactor"])["compaction"])
        assert tempo["block_retention"] == "168h"
        for name in ["loki", "tempo"]:
            server = _mapping(config(name)["server"])
            assert _mapping(server["http_tls_config"])["client_auth_type"] == "RequireAndVerifyClientCert"

    def test_sampling_contract_includes_both_http_conventions(self) -> None:
        """Require tail sampling to match both HTTP status conventions."""
        documents = _mapping(config("trace-gateway")["processors"])
        sampling = _mapping(documents["tail_sampling"])
        assert sampling["decision_wait"] == "30s"
        policies: dict[str, dict[str, object]] = {}
        for entry in _list(sampling["policies"]):
            policy = _mapping(entry)
            policies[_text(policy["name"])] = policy
        errors = _mapping(policies["errors"])
        assert _mapping(errors["status_code"])["status_codes"] == ["ERROR"]
        assert _mapping(_mapping(policies["slow"])["latency"])["threshold_ms"] == 2000
        probabilistic = _mapping(_mapping(policies["other"])["probabilistic"])
        assert probabilistic["sampling_percentage"] == 10
        for name, key in [
            ("http-5xx", "http.response.status_code"),
            ("legacy-http-5xx", "http.status_code"),
        ]:
            assert policies[name]["numeric_attribute"] == {"key": key, "min_value": 500, "max_value": 599}
