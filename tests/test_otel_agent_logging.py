"""Offline contracts for the native agent; no host log bodies are read."""

from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _mapping(value: object) -> dict[str, object]:
    """Reach into the shipped agent collector document."""
    assert isinstance(value, dict)
    return value


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _text(value: object) -> str:
    assert isinstance(value, str)
    return value


class AgentLoggingTests(unittest.TestCase):
    """Validate the OpenTelemetry agent's logging configuration."""
    def setUp(self) -> None:
        document: object = yaml.safe_load((ROOT / "deploy/monitoring/otel/agent.yaml").read_text())
        assert isinstance(document, dict)
        self.agent: dict[str, object] = document

    def test_self_log_exclusion_does_not_drop_backends_or_adjacent_containers(
        self,
    ) -> None:
        from fnmatch import fnmatchcase

        patterns = _list(_mapping(_mapping(self.agent["receivers"])["filelog"])["exclude"])

        def excluded(pod: str, container: str) -> bool:
            path = f"/var/log/pods/cattle-monitoring-system_{pod}_uid/{container}/0.log"
            return any(fnmatchcase(path, _text(pattern)) for pattern in patterns)

        assert excluded("prometheus-kube-prometheus-stack-prometheus-0", "otel-cluster")
        for pod, container in [
            ("otel-loki-58655fcd84-mvsbt", "loki"),
            ("otel-tempo-7b5d947c8b-gc9lj", "tempo"),
            ("prometheus-kube-prometheus-stack-prometheus-0", "prometheus"),
            ("prometheus-kube-prometheus-stack-prometheus-0", "thanos-sidecar"),
            ("otel-application", "app"),
        ]:
            assert not excluded(pod, container), (pod, container)

    def test_rotation_and_restart_contract(self) -> None:
        receiver = _mapping(_mapping(self.agent["receivers"])["filelog"])
        assert _mapping(_list(receiver["operators"])[0])["type"] == "container"
        assert receiver["start_at"] == "beginning"
        assert receiver["storage"] == "file_storage"
        assert _mapping(receiver["retry_on_failure"])["max_elapsed_time"] == "0s"
        assert receiver["poll_interval"] == "1s"
        journal = _mapping(_mapping(self.agent["receivers"])["journald"])
        assert journal["storage"] == "file_storage"
        assert _mapping(journal["retry_on_failure"])["enabled"]
        assert _mapping(journal["retry_on_failure"])["max_elapsed_time"] == "0s"
        assert _mapping(_mapping(self.agent["extensions"])["file_storage"])["fsync"]

    def test_privacy_precedes_durable_log_queue_without_async_batch(self) -> None:
        pipeline = _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])
        assert "transform/log-privacy" in _list(pipeline["processors"])
        assert "batch/logs" not in _list(pipeline["processors"])
        assert _list(pipeline["exporters"]) == ["otlp/logs"]
        queue = _mapping(_mapping(_mapping(self.agent["exporters"])["otlp/logs"])["sending_queue"])
        assert queue["sizer"] == "bytes"
        assert queue["queue_size"] == 128 * 2 ** 20
        assert queue["block_on_overflow"]
        assert queue["storage"] == "file_storage"
        assert _list(_mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["metrics"])["exporters"]) == ["otlp"]

    def test_common_schema_and_priority_mapping(self) -> None:
        processors_document = _mapping(self.agent["processors"])
        identity = str(processors_document["transform/log-identity"])
        for field in ["service.name", "k8s.namespace.name", "severity", "unknown"]:
            assert field in identity
        assert _mapping(processors_document["groupbyattrs/log-severity"])["keys"] == ["severity"]
        logs_processors = _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])[
            "processors"
        ]
        assert "groupbyattrs/log-severity" in _list(logs_processors)
        assert "PRIORITY" in str(processors_document["transform/journal"])
        assert "host.name" in str(processors_document["resource"])

    def test_journal_identity_is_split_before_shared_resource_promotion(self) -> None:
        processors = _mapping(self.agent["processors"])
        identity = str(processors["transform/journal-identity"])
        assert 'set(attributes["service.name"], body["_SYSTEMD_UNIT"])' in identity
        assert "resource.attributes" not in identity
        assert _mapping(processors["groupbyattrs/journal-identity"])["keys"] == ["service.name"]
        assert "service.name" not in str(processors["transform/journal"])
        chain = _list(
            _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])["processors"]
        )
        assert chain.index("transform/journal-identity") < chain.index("groupbyattrs/journal-identity")
        assert chain.index("groupbyattrs/journal-identity") < chain.index("transform/journal")

    def test_serial_rollout_validates_before_handler_flush(self) -> None:
        play = yaml.safe_load((ROOT / "ansible/playbooks/otel-production-agents.yml").read_text())[
            0
        ]
        assert play["serial"] == 1
        names = [task["name"] for task in play["tasks"]]
        assert names.index("Validate installed host agent configuration before restart") < names.index("Apply validated agent changes before advancing serial rollout")


if __name__ == "__main__":
    unittest.main()
