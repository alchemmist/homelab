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

        self.assertTrue(excluded("prometheus-kube-prometheus-stack-prometheus-0", "otel-cluster"))
        for pod, container in [
            ("otel-loki-58655fcd84-mvsbt", "loki"),
            ("otel-tempo-7b5d947c8b-gc9lj", "tempo"),
            ("prometheus-kube-prometheus-stack-prometheus-0", "prometheus"),
            ("prometheus-kube-prometheus-stack-prometheus-0", "thanos-sidecar"),
            ("otel-application", "app"),
        ]:
            self.assertFalse(excluded(pod, container), (pod, container))

    def test_rotation_and_restart_contract(self) -> None:
        receiver = _mapping(_mapping(self.agent["receivers"])["filelog"])
        self.assertEqual(_mapping(_list(receiver["operators"])[0])["type"], "container")
        self.assertEqual(receiver["start_at"], "beginning")
        self.assertEqual(receiver["storage"], "file_storage")
        self.assertEqual(_mapping(receiver["retry_on_failure"])["max_elapsed_time"], "0s")
        self.assertEqual(receiver["poll_interval"], "1s")
        journal = _mapping(_mapping(self.agent["receivers"])["journald"])
        self.assertEqual(journal["storage"], "file_storage")
        self.assertTrue(_mapping(journal["retry_on_failure"])["enabled"])
        self.assertEqual(_mapping(journal["retry_on_failure"])["max_elapsed_time"], "0s")
        self.assertTrue(_mapping(_mapping(self.agent["extensions"])["file_storage"])["fsync"])

    def test_privacy_precedes_durable_log_queue_without_async_batch(self) -> None:
        pipeline = _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])
        self.assertIn("transform/log-privacy", _list(pipeline["processors"]))
        self.assertNotIn("batch/logs", _list(pipeline["processors"]))
        self.assertEqual(_list(pipeline["exporters"]), ["otlp/logs"])
        queue = _mapping(_mapping(_mapping(self.agent["exporters"])["otlp/logs"])["sending_queue"])
        self.assertEqual(queue["sizer"], "bytes")
        self.assertEqual(queue["queue_size"], 128 * 2**20)
        self.assertTrue(queue["block_on_overflow"])
        self.assertEqual(queue["storage"], "file_storage")
        self.assertEqual(
            _list(
                _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["metrics"])[
                    "exporters"
                ]
            ),
            ["otlp"],
        )

    def test_common_schema_and_priority_mapping(self) -> None:
        processors_document = _mapping(self.agent["processors"])
        identity = str(processors_document["transform/log-identity"])
        for field in ["service.name", "k8s.namespace.name", "severity", "unknown"]:
            self.assertIn(field, identity)
        self.assertEqual(
            _mapping(processors_document["groupbyattrs/log-severity"])["keys"],
            ["severity"],
        )
        logs_processors = _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])[
            "processors"
        ]
        self.assertIn("groupbyattrs/log-severity", _list(logs_processors))
        self.assertIn("PRIORITY", str(processors_document["transform/journal"]))
        self.assertIn("host.name", str(processors_document["resource"]))

    def test_journal_identity_is_split_before_shared_resource_promotion(self) -> None:
        processors = _mapping(self.agent["processors"])
        identity = str(processors["transform/journal-identity"])
        self.assertIn('set(attributes["service.name"], body["_SYSTEMD_UNIT"])', identity)
        self.assertNotIn("resource.attributes", identity)
        self.assertEqual(
            _mapping(processors["groupbyattrs/journal-identity"])["keys"],
            ["service.name"],
        )
        self.assertNotIn("service.name", str(processors["transform/journal"]))
        chain = _list(
            _mapping(_mapping(_mapping(self.agent["service"])["pipelines"])["logs"])["processors"]
        )
        self.assertLess(
            chain.index("transform/journal-identity"),
            chain.index("groupbyattrs/journal-identity"),
        )
        self.assertLess(
            chain.index("groupbyattrs/journal-identity"),
            chain.index("transform/journal"),
        )

    def test_serial_rollout_validates_before_handler_flush(self) -> None:
        play = yaml.safe_load((ROOT / "ansible/playbooks/otel-production-agents.yml").read_text())[
            0
        ]
        self.assertEqual(play["serial"], 1)
        names = [task["name"] for task in play["tasks"]]
        self.assertLess(
            names.index("Validate installed host agent configuration before restart"),
            names.index("Apply validated agent changes before advancing serial rollout"),
        )


if __name__ == "__main__":
    unittest.main()
