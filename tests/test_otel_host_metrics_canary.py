"""Tests for the OpenTelemetry host metrics canary."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "host_metrics_canary", ROOT / "scripts/otel-host-metrics-canary.py"
)
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def log(message: str, **fields: object) -> str:
    """Test behavior for log."""
    return "2026-10-30T20:33:41.405+0300\terror\t" + message + "\t" + json.dumps(fields)


def shutdown() -> str:
    """Test behavior for shutdown."""
    return log(
        "Exporting failed. Dropping data.",
        resource={"service.version": "0.164.0"},
        **{
            "otelcol.component.id": "otlp",
            "otelcol.signal": "metrics",
            "error": "interrupted due to shutdown: rpc error: Unavailable",
        },
    )


class HostMetricsCanaryTests(unittest.TestCase):
    """Verify only exact pinned host-metrics canary errors count."""
    def test_only_exact_pinned_shutdown_errors_with_actual_replay_are_accounted(
        self,
    ) -> None:
        """Only exact pinned shutdown errors with replay are accounted."""

        text = shutdown() + "\n" + log("Moved items for dispatching back to queue", numberOfItems=1)
        result = canary.classify_shutdown_replay(text)
        assert result["shutdownReplayAccounted"]
        assert result["shutdownSendErrorEvents"] == 1
        assert result["restoredInFlightRequests"] == 1
        assert not canary.classify_shutdown_replay(shutdown())["shutdownReplayAccounted"]

    def test_generic_or_different_version_drop_is_never_exempted(self) -> None:
        """Generic or different-version drops are never exempted."""

        for text in [
            shutdown().replace("interrupted due to shutdown:", "permanent error:"),
            shutdown().replace("0.164.0", "0.163.0"),
            shutdown().replace("metrics", "logs"),
            "Exporting failed. Dropping data. malformed json",
        ]:
            assert not canary.classify_shutdown_replay(text)["shutdownReplayAccounted"]

    def test_persistent_metadata_error_or_replay_mismatch_fails(self) -> None:
        """Persistent metadata errors or replay mismatch fail the canary."""

        for suffix in [
            "\nFailed getting metadata",
            "\nError deleting item from queue",
            "\nErrors occurred while moving items",
        ]:
            text = (
                shutdown()
                + "\n"
                + log("Moved items for dispatching back to queue", numberOfItems=1)
                + suffix
            )
            assert not canary.classify_shutdown_replay(text)["shutdownReplayAccounted"]
        text = shutdown() + "\n" + log("Moved items for dispatching back to queue", numberOfItems=2)
        assert not canary.classify_shutdown_replay(text)["shutdownReplayAccounted"]

    def test_metrics_only_configs_preserve_native_limits_and_queue_fsync(self) -> None:
        """Metrics-only configs preserve native limits and queue fsync."""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for role in ("agent", "cluster"):
                source = yaml.safe_load(
                    (ROOT / "deploy/monitoring/otel" / (role + ".yaml")).read_text()
                )
                (directory / (role + "-source.json")).write_text(json.dumps(source))
            agent, gateway = canary.configs(directory, {"backendIP": "10.250.0.3"})
            assert set(agent["receivers"]) == {"prometheus"}
            assert set(agent["service"]["pipelines"]) == {"metrics"}
            agent_limit_mib = 208
            assert agent["processors"]["memory_limiter"]["limit_mib"] == agent_limit_mib
            assert agent["exporters"]["otlp"]["sending_queue"]["queue_size"] == 128 * 2**20
            assert agent["extensions"]["file_storage"]["fsync"]
            gateway_limit_mib = 896
            assert gateway["processors"]["memory_limiter"]["limit_mib"] == gateway_limit_mib
            assert set(gateway["exporters"]) == {"otlp_http/metrics"}
            grpc = gateway["receivers"]["otlp"]["protocols"]["grpc"]
            assert grpc["endpoint"] == "10.250.0.3:43170"
            assert "client_ca_file" in grpc["tls"]
            assert "insecure" not in json.dumps(agent)

    def test_backend_cleanup_is_after_all_agent_barrier_and_never_delegated(
        self,
    ) -> None:
        """Backend cleanup follows the agent barrier and is never delegated."""

        plays = yaml.safe_load(
            (ROOT / "ansible/playbooks/otel-host-metrics-canary.yml").read_text()
        )
        cleanup = plays[1]["tasks"][0]["always"]
        names = [task["name"] for task in cleanup]
        assert names.index(
            "Stop all native agents before stopping their shared test backend"
        ) < names.index("Stop gateway then shadow Prometheus only after the agent barrier")
        for task in plays[1]["tasks"][0]["block"] + cleanup:
            assert task.get("delegate_to") != "socrat-1"

    def test_outage_proof_uses_raw_range_vector_not_query_range_lookback(self) -> None:
        """The outage proof uses a raw range vector, not query-range lookback."""

        text = (ROOT / "scripts/otel-host-metrics-canary.py").read_text()
        assert "query(root, 'up[10m]')" in text
        assert "stops < float(timestamp) < restart" in text
        assert "RuntimeMaxSec=900" in text
        assert "'User=65534'" in text
        assert "queueSaturationOrFullHighWaterVerified" in text

    def test_native_contract_is_fresh_and_content_bound(self) -> None:
        """The native contract is fresh and content-bound."""

        import datetime
        import hashlib
        import socket

        now = datetime.datetime.now(datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            document = {"scrape_configs": []}
            (directory / "scrape.json").write_text(json.dumps(document))
            digest = hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            request = {
                "scrapeContractCollectedAt": now.isoformat(),
                "hostScrapeSHA256": {socket.gethostname(): digest},
            }
            canary.validate_contract(directory, request, now)
            for delta in (901, -1):
                with self.subTest(delta=delta), self.assertRaises(ValueError):
                    canary.validate_contract(
                        directory, request, now + datetime.timedelta(seconds=delta)
                    )
            (directory / "scrape.json").write_text('{"scrape_configs":[{}]}')
            with self.assertRaises(ValueError):
                canary.validate_contract(directory, request, now)

    def test_request_binary_receipt_requires_image_and_executable_digest(self) -> None:
        """Binary receipts require matching image and executable digests."""

        import hashlib

        spec = importlib.util.spec_from_file_location(
            "host_request", ROOT / "scripts/otel-host-metrics-request.py"
        )
        request = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(request)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "binary").write_bytes(b"fixture")
            digest = hashlib.sha256(b"fixture").hexdigest()
            receipt = {
                "architecture": "linux/amd64",
                "binaries": {"collector": {"image": "official@sha256:abc", "sha256": digest}},
            }
            (directory / "receipt.json").write_text(json.dumps(receipt))
            images = {"collector": {"image": "official@sha256:abc"}}
            assert request.pinned_binary(directory, "collector", "binary", images) == digest
            (directory / "binary").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                request.pinned_binary(directory, "collector", "binary", images)

    def test_request_refuses_public_backend_before_source_access(self) -> None:
        """Requests refuse a public backend before any source access."""

        spec = importlib.util.spec_from_file_location(
            "host_request", ROOT / "scripts/otel-host-metrics-request.py"
        )
        request = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(request)
        with self.assertRaises(ValueError):
            request.create(
                Path("/missing"),
                Path("/missing"),
                Path("/missing"),
                Path("/missing"),
                "0.0.0.0",
            )
