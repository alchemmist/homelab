"""Keep OpenTelemetry queue, retention, TLS, and sampling contracts."""

import unittest
from pathlib import Path

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
            self.assertTrue(document["extensions"]["file_storage"]["fsync"])
            for exporter in document["exporters"].values():
                queue = exporter["sending_queue"]
                self.assertEqual(queue["sizer"], "bytes")
                self.assertEqual(queue["queue_size"], limit)
                self.assertEqual(queue["storage"], "file_storage")

    def test_new_file_startup_records_and_historical_cut_are_separate(self) -> None:
        """Require new-file startup and the historical cut to stay separate."""
        self.assertEqual(config("agent")["receivers"]["filelog"]["start_at"], "beginning")
        for name in ["agent", "cluster"]:
            document = config(name)
            processors = document["service"]["pipelines"]["logs"]["processors"]
            self.assertLess(processors.index("filter/log-ingestion-cut"), len(processors) - 1)
            condition = document["processors"]["filter/log-ingestion-cut"]["logs"]["log_record"][0]
            self.assertIn("time_unix_nano == 0", condition)
            self.assertIn("${env:OTEL_LOG_INGESTION_START_NS}", condition)

    def test_public_otlp_cannot_be_enabled_without_client_authentication(self) -> None:
        """Require public OTLP listeners to present client-authenticated TLS."""
        for name in ["cluster", "trace-gateway"]:
            for protocol in config(name)["receivers"]["otlp"]["protocols"].values():
                self.assertIn("${env:OTEL_BIND_IP}", protocol["endpoint"])
                self.assertTrue({"cert_file", "key_file", "client_ca_file"} <= set(protocol["tls"]))
                self.assertTrue(
                    set(protocol["tls"])
                    <= {"cert_file", "key_file", "client_ca_file", "reload_interval"}
                )
                if "reload_interval" in protocol["tls"]:
                    self.assertEqual(protocol["tls"]["reload_interval"], "1m")

    def test_production_ingestion_uses_the_service_identity(self) -> None:
        """The host dials the Service IP but verifies its DNS SAN without a DNS dependency."""
        repo = ROOT.parents[2]
        play, = yaml.safe_load((repo / "ansible/playbooks/otel-production-agents.yml").read_text())
        tasks = {task["name"]: task for task in play["tasks"]}
        unit = tasks["Install native tail sampling gateway"]["ansible.builtin.copy"]["content"]
        self.assertIn("Environment=OTEL_TEMPO_ENDPOINT={{ trace_gateway_service.stdout }}:4317", unit)
        self.assertIn("--set=exporters.otlp/tempo.tls.server_name_override="
                      "otel-tempo.cattle-monitoring-system.svc.cluster.local", unit)
        for source in ("charts/prometheus/values.yaml", "deploy/monitoring/otel-production-values.yaml",
                       "scripts/otel-production-cluster.py"):
            text = (repo / source).read_text()
            self.assertIn("https://otel-loki.cattle-monitoring-system.svc:3100/otlp", text)
            self.assertNotIn("https://10.250.0.3:3100/otlp", text)

    def test_retention_is_not_shortened(self) -> None:
        """Require Loki and Tempo retention periods to stay at their current lengths."""
        self.assertEqual(config("loki")["limits_config"]["retention_period"], "336h")
        self.assertTrue(config("loki")["compactor"]["retention_enabled"])
        self.assertEqual(config("tempo")["compactor"]["compaction"]["block_retention"], "168h")
        for name in ["loki", "tempo"]:
            self.assertEqual(
                config(name)["server"]["http_tls_config"]["client_auth_type"],
                "RequireAndVerifyClientCert",
            )

    def test_sampling_contract_includes_both_http_conventions(self) -> None:
        """Require tail sampling to match both HTTP status conventions."""
        sampling = config("trace-gateway")["processors"]["tail_sampling"]
        self.assertEqual(sampling["decision_wait"], "30s")
        policies = {entry["name"]: entry for entry in sampling["policies"]}
        self.assertEqual(policies["errors"]["status_code"]["status_codes"], ["ERROR"])
        self.assertEqual(policies["slow"]["latency"]["threshold_ms"], 2000)
        self.assertEqual(policies["other"]["probabilistic"]["sampling_percentage"], 10)
        for name, key in [
            ("http-5xx", "http.response.status_code"),
            ("legacy-http-5xx", "http.status_code"),
        ]:
            self.assertEqual(
                policies[name]["numeric_attribute"],
                {"key": key, "min_value": 500, "max_value": 599},
            )
