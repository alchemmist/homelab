import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "otel_registry", ROOT / "scripts/otel-source-registry.py"
)
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)


def fixtures():
    monitor = {
        "kind": "ServiceMonitor",
        "metadata": {
            "namespace": "monitoring",
            "name": "nodes",
            "resourceVersion": "1",
            "labels": {"release": "stack"},
        },
        "spec": {"endpoints": [{"port": "metrics", "interval": "5s"}]},
    }
    target = {
        "scrapePool": "serviceMonitor/monitoring/nodes/0",
        "scrapeUrl": "http://node:9100/metrics",
        "labels": {"job": "node-exporter", "instance": "node:9100"},
        "health": "up",
        "scrapeInterval": "5s",
        "scrapeTimeout": "4s",
    }
    prometheus = {
        "metadata": {"namespace": "monitoring"},
        "spec": {
            "serviceMonitorSelector": {"matchLabels": {"release": "stack"}},
            "serviceMonitorNamespaceSelector": {"matchLabels": {"selected": "yes"}},
        },
    }
    namespaces = {"items": [{"metadata": {"name": "monitoring", "labels": {"selected": "yes"}}}]}
    rules = {
        "groups": [
            {
                "name": "health",
                "rules": [
                    {"name": "NodeDown", "type": "alerting", "query": "up == 0", "health": "ok"}
                ],
            }
        ]
    }
    dashboards = {
        "items": [
            {
                "metadata": {"name": "dashboard", "namespace": "monitoring"},
                "data": {
                    "main.json": json.dumps(
                        {
                            "uid": "overview",
                            "refresh": "5s",
                            "panels": [{"id": 1, "targets": [{"refId": "A", "expr": "up"}]}],
                        }
                    )
                },
            }
        ]
    }
    return (
        {"items": [monitor]},
        {"activeTargets": [target]},
        prometheus,
        namespaces,
        rules,
        dashboards,
    )


class SourceRegistryTests(unittest.TestCase):
    def test_complete_active_inventory_preserves_labels_and_ownership(self):
        args = fixtures()
        before = copy.deepcopy(args)
        result = REGISTRY.build(*args)
        assert result["liveInventoryVerified"]
        assert not result["readyForCutover"]
        assert not result["sourceCapabilitiesVerified"]
        assert result["targets"][0]["futureOwner"] == "node-systemd-agent"
        assert result["targets"][0]["labelNames"] == ["instance", "job"]
        assert result["activeIntervals"] == {"5s": 1}
        assert args == before

    def test_nondefault_intervals_are_reported_not_rewritten(self):
        args = fixtures()
        args[1]["activeTargets"][0]["scrapeInterval"] = "30s"
        result = REGISTRY.build(*args)
        assert result["activeIntervals"] == {"30s": 1}
        assert result["findings"][0]["targets"] == 1

    def test_unknown_jobs_and_monitor_endpoints_fail_closed(self):
        for field, value in [
            ("job", "unknown-new-exporter"),
            ("pool", "serviceMonitor/monitoring/nodes/9"),
        ]:
            args = fixtures()
            target = args[1]["activeTargets"][0]
            if field == "job":
                target["labels"]["job"] = value
            else:
                target["scrapePool"] = value
            assert not REGISTRY.build(*args)["liveInventoryVerified"]

    def test_unselected_monitors_are_retained_without_activation(self):
        args = fixtures()
        monitor = copy.deepcopy(args[0]["items"][0])
        monitor["metadata"]["name"] = "excluded"
        monitor["metadata"]["labels"] = {"release": "another-stack"}
        args[0]["items"].append(monitor)
        result = REGISTRY.build(*args)
        item = result["sources"]["serviceMonitor/monitoring/excluded"]
        assert not item["selectedByPrometheus"]
        assert item["activeTargetCount"] == 0
        assert result["liveInventoryVerified"]

    def test_active_target_outside_selector_is_an_error(self):
        args = fixtures()
        args[0]["items"][0]["metadata"]["labels"] = {}
        assert not REGISTRY.build(*args)["liveInventoryVerified"]

    def test_kubernetes_selector_semantics(self):
        cases = [
            (
                {"matchExpressions": [{"key": "x", "operator": "In", "values": ["a"]}]},
                {"x": "a"},
                True,
            ),
            ({"matchExpressions": [{"key": "x", "operator": "NotIn", "values": ["a"]}]}, {}, True),
            ({"matchExpressions": [{"key": "x", "operator": "Exists"}]}, {}, False),
            ({"matchExpressions": [{"key": "x", "operator": "DoesNotExist"}]}, {}, True),
        ]
        for selector, attributes, expected in cases:
            assert REGISTRY.selected(selector, attributes) == expected
        with self.assertRaises(ValueError):
            REGISTRY.selected({"matchExpressions": [{"key": "x", "operator": "unsupported"}]}, {})

    def test_unhealthy_or_missing_targets_block_inventory(self):
        args = fixtures()
        args[1]["activeTargets"][0]["health"] = "down"
        assert not REGISTRY.build(*args)["liveInventoryVerified"]
        args[1]["activeTargets"] = []
        assert not REGISTRY.build(*args)["liveInventoryVerified"]

    def test_secrets_urls_and_values_are_not_published(self):
        scrubbed = REGISTRY.scrub(
            {
                "authorization": {"credentials": "actual-secret"},
                "basicAuth": {"username": "private-user", "password": "hidden"},
                "params": {"target": ["https://user:pass@host/private-vpn-path?token=abc"]},
            }
        )
        value = json.dumps(scrubbed)
        for secret in (
            "actual-secret",
            "private-user",
            "hidden",
            "user:pass",
            "private-vpn-path",
            "token=abc",
        ):
            assert secret not in value
        target = fixtures()[1]["activeTargets"][0]
        target["labels"]["instance"] = "https://user:pass@host/private-vpn-path?token=abc"
        target["scrapeUrl"] = "http://node:9100/hidden-path?auth=secret"
        summary = json.dumps(REGISTRY.target_summary(target))
        for secret in ("user:pass", "private-vpn-path", "token=abc", "hidden-path", "auth=secret"):
            assert secret not in summary

    def test_nested_dashboard_queries_are_inventoried_without_mutation(self):
        document = {
            "panels": [{"id": 1, "panels": [{"id": 2, "targets": [{"expr": "up", "refId": "B"}]}]}]
        }
        assert list(REGISTRY.expressions(document)) == [(2, "B", "up")]

    def test_duplicate_dashboard_uid_is_rejected(self):
        args = fixtures()
        args[-1]["items"].append(copy.deepcopy(args[-1]["items"][0]))
        with self.assertRaises(ValueError):
            REGISTRY.build(*args)

    def test_known_producers_complete_the_registry_not_cutover(self):
        registry = REGISTRY.build(*fixtures())
        producers = {
            node: {"files": [], "timers": {}}
            for node in ["socrat-0", "socrat-1", "socrat-2", "socrat-3"]
        }
        producers["socrat-0"] = {
            "files": [{"file": "nvidia.prom", "producer": "monitoring_gpu"}],
            "timers": {"monitoring-gpu.timer": {"active": True}},
        }
        producers["socrat-2"] = {
            "files": [{"file": "vpn.prom", "producer": "monitoring_vpn"}],
            "timers": {"monitoring-vpn.timer": {"active": True}},
        }
        daemonsets = {
            "items": [
                {
                    "metadata": {"name": "thanos-disk"},
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {"env": [{"name": "INTERVAL_SECONDS", "value": "30"}]}
                                ]
                            }
                        }
                    },
                }
            ]
        }
        REGISTRY.attach_producers(registry, producers, daemonsets)
        assert registry["metricsSourceRegistryVerified"]
        assert not registry["sourceRegistryVerified"]
        assert not registry["readyForCutover"]
        assert registry["diskProducerRefreshSeconds"] == "30"

    def test_missing_producers_are_not_assumed_healthy(self):
        registry = REGISTRY.build(*fixtures())
        REGISTRY.attach_producers(registry, {}, {"items": []})
        assert not registry["sourceRegistryVerified"]
        assert len(registry["errors"]) > 0


if __name__ == "__main__":
    unittest.main()
