"""Tests for the OpenTelemetry scrape configuration generator."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "scrape_config", ROOT / "scripts/otel-scrape-config.py"
)
SCRAPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRAPE)


class _Target(TypedDict):
    scrapePool: str
    health: str
    labels: dict[str, str]
    discoveredLabels: NotRequired[dict[str, str]]


class _ScrapeJob(TypedDict, total=False):
    job_name: str
    scrape_interval: str
    kubernetes_sd_configs: list[dict[str, object]]
    relabel_configs: list[dict[str, object]]
    metric_relabel_configs: list[dict[str, object]]
    authorization: NotRequired[dict[str, object]]


_Source = TypedDict(
    "_Source", {"global": dict[str, object], "scrape_configs": list[_ScrapeJob]}
)


class _Targets(TypedDict):
    activeTargets: list[_Target]


def fixtures() -> tuple[_Source, _Targets]:
    """Test behavior for fixtures."""
    cluster: _ScrapeJob = {
        "job_name": "serviceMonitor/llm/vllm/0",
        "scrape_interval": "30s",
        "kubernetes_sd_configs": [{"role": "pod"}],
        "relabel_configs": [
            {
                "source_labels": ["app"],
                "regex": "(vllm)$",
                "replacement": "$1",
                "target_label": "job",
            }
        ],
        "metric_relabel_configs": [
            {"source_labels": ["__name__"], "regex": "junk.*", "action": "drop"}
        ],
    }
    node: _ScrapeJob = {
        "job_name": "serviceMonitor/monitoring/nodes/0",
        "kubernetes_sd_configs": [{"role": "endpoints"}],
        "relabel_configs": [{"target_label": "job", "replacement": "node-exporter"}],
    }
    source: _Source = {
        "global": {
            "external_labels": {"prometheus": "legacy-context"},
            "evaluation_interval": "30s",
        },
        "scrape_configs": [cluster, node, {"job_name": "empty-pool"}],
    }
    active: list[_Target] = [
        {
            "scrapePool": cluster["job_name"],
            "health": "up",
            "labels": {"job": "vllm", "instance": "vllm:8000"},
        }
    ]
    for index, name in enumerate(SCRAPE.NODES):
        active.append(
            {
                "scrapePool": node["job_name"],
                "health": "up",
                "labels": {
                    "job": "node-exporter",
                    "instance": name + ":9100",
                    "pod": "legacy-" + str(index),
                },
                "discoveredLabels": {"__meta_kubernetes_pod_node_name": name},
            }
        )
    return source, {"activeTargets": active}


class ScrapeConfigTests(unittest.TestCase):
    """Validate scrape config edits stay narrow and reversible."""

    def test_public_edge_refresh_is_narrow_and_preserves_original(self) -> None:
        """Public edge refresh is narrow and preserves original."""
        job = {
            "job_name": "serviceMonitor/cattle-monitoring-system/monitoring-service-probes/26",
            "params": {"module": ["tcp_connect"], "target": ["192.0.2.1:443"]},
            "relabel_configs": [
                {"target_label": "service_id", "replacement": "edge-vps"}
            ],
        }
        other = {"job_name": "unrelated", "params": {"target": ["192.0.2.1:443"]}}
        original = {"scrape_configs": [job, other]}
        before = copy.deepcopy(original)
        result = SCRAPE.refresh_public_edge_probe(original)
        assert original == before
        assert result["scrape_configs"][0]["params"]["target"] == ["109.120.141.60:443"]
        assert result["scrape_configs"][1] == other
        expected_scrape_configs = 3
        assert len(result["scrape_configs"]) == expected_scrape_configs
        assert result["scrape_configs"][2]["params"]["target"] == ["91.189.82.238:443"]
        assert {"target_label": "service_id", "replacement": "edge-moscow"} in result[
            "scrape_configs"
        ][2]["relabel_configs"]
        assert SCRAPE.refresh_public_edge_probe(result) == result

    def test_moscow_job_does_not_reuse_frozen_numeric_endpoint_indices(self) -> None:
        """Moscow job does not reuse frozen numeric endpoint indices."""
        targets = yaml.safe_load(
            (SCRAPE.ROOT / "charts/monitoring-k3s/values.yaml").read_text()
        )["serviceProbes"]["targets"]
        index = 1 + next(i for i, t in enumerate(targets) if t["id"] == "edge-moscow")
        prefix = "serviceMonitor/cattle-monitoring-system/monitoring-service-probes/"
        old = {"job_name": prefix + str(index), "params": {"target": ["legacy:443"]}}
        vps = {
            "job_name": prefix + "26",
            "params": {"module": ["tcp_connect"], "target": ["109.120.141.60:443"]},
            "relabel_configs": [
                {"target_label": "service_id", "replacement": "edge-vps"}
            ],
        }
        original = {"scrape_configs": [vps, old]}
        result = SCRAPE.add_moscow_edge_probe(original)
        assert result["scrape_configs"][:2] == original["scrape_configs"]
        assert result["scrape_configs"][2]["job_name"] == prefix + "edge-moscow"
        assert SCRAPE.add_moscow_edge_probe(result) == result

    def test_ownership_discovery_labels_and_relabeling_are_preserved(self) -> None:
        """Ownership discovery labels and relabeling are preserved."""
        source, targets = fixtures()
        before = copy.deepcopy(source)
        outputs, contract = SCRAPE.compile_config(source, targets)
        cluster = outputs["cluster"]["scrape_configs"][0]
        assert (
            cluster["kubernetes_sd_configs"]
            == before["scrape_configs"][0]["kubernetes_sd_configs"]
        )
        assert (
            cluster["metric_relabel_configs"]
            == before["scrape_configs"][0]["metric_relabel_configs"]
        )
        assert cluster["relabel_configs"][0]["replacement"] == "$$1"
        assert cluster["relabel_configs"][0]["regex"] == "(vllm)$$"
        assert cluster["scrape_interval"] == "5s"
        assert cluster["scrape_timeout"] == "4s"
        assert "external_labels" not in outputs["cluster"]["global"]
        assert source == before
        for index, node in enumerate(SCRAPE.NODES):
            job = outputs[node]["scrape_configs"][0]
            assert "kubernetes_sd_configs" not in job
            assert "relabel_configs" not in job
            assert job["static_configs"][0]["targets"] == ["127.0.0.1:19100"]
            assert (
                job["static_configs"][0]["labels"]
                == targets["activeTargets"][index + 1]["labels"]
            )
        assert contract["excludedEmptyPools"] == ["empty-pool"]
        assert contract["legacyTargetIdentityAliasesRequireAcceptance"]
        assert not contract["readyForCutover"]

    def test_secret_selector_becomes_a_file_not_a_masked_credential(self) -> None:
        """Secret selector becomes a file not a masked credential."""
        source, targets = fixtures()
        source["scrape_configs"][0]["authorization"] = {
            "type": "Bearer",
            "credentials": "<secret>",
        }
        monitors = {
            "serviceMonitor/llm/vllm": {
                "metadata": {"namespace": "llm"},
                "spec": {
                    "endpoints": [
                        {
                            "authorization": {
                                "credentials": {
                                    "name": "metrics-auth",
                                    "key": "api-key",
                                },
                                "type": "Bearer",
                            }
                        }
                    ]
                },
            }
        }
        outputs, contract = SCRAPE.compile_config(source, targets, monitors)
        authorization = outputs["cluster"]["scrape_configs"][0]["authorization"]
        assert authorization == {
            "type": "Bearer",
            "credentials_file": "/etc/otel/source-auth/llm/metrics-auth/api-key",
        }
        assert "<secret>" not in json.dumps(outputs)
        required_key = contract["requiredSecretKeys"][0]["secret"]
        assert required_key == "metrics-auth"
        assert not contract["secretAssetSynchronizationRuntimeVerified"]

    def test_unattributed_inline_secret_is_rejected(self) -> None:
        """Unattributed inline secret is rejected."""
        source, targets = fixtures()
        source["scrape_configs"][0]["authorization"] = {"credentials": "<secret>"}
        with pytest.raises(ValueError, match="monitor"):
            SCRAPE.compile_config(source, targets)

    def test_unknown_owner_and_missing_node_fail_closed(self) -> None:
        """Unknown owner and missing node fail closed."""
        for mutate in ["owner", "node"]:
            source, targets = fixtures()
            if mutate == "owner":
                targets["activeTargets"][0]["labels"]["job"] = "unregistered"
            else:
                targets["activeTargets"].pop()
            with self.subTest(mutate=mutate), pytest.raises(ValueError):
                SCRAPE.compile_config(source, targets)

    def test_validation_assets_are_inert_and_do_not_mutate_the_real_config(
        self,
    ) -> None:
        """Validation assets are inert and do not mutate the real config."""
        document = {
            "authorization": {
                "credentials_file": "/etc/otel/source-auth/ns/name/token"
            },
            "tls_config": {
                "ca_file": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            },
            "replacement": "$$1",
        }
        before = copy.deepcopy(document)
        result = SCRAPE.validation_config(document)
        assert (
            result["authorization"]["credentials_file"]
            == "${env:OTEL_VALIDATION_ASSET_DIR}/token"
        )
        assert result["tls_config"]["ca_file"] == "${env:OTEL_TLS_DIR}/ca.crt"
        assert result["replacement"] == "$$1"
        assert document == before

    def test_unsafe_file_dependency_is_rejected(self) -> None:
        """Unsafe file dependency is rejected."""
        with pytest.raises(ValueError):
            SCRAPE.assets({"credentials_file": "/etc/otel/source-auth/../outside"})
        with pytest.raises(ValueError):
            SCRAPE.assets({"credentials_file": "/etc/shadow"})


def test_native_scrape_cost_is_scoped_and_idempotent():
    base = "serviceMonitor/cattle-monitoring-system/kube-prometheus-stack-"
    src = {
        "scrape_configs": [
            {"job_name": base + n, "scrape_interval": "5s"}
            for n in ("kubelet/0", "kubelet/1", "apiserver/0", "grafana/0")
        ]
    }
    result = SCRAPE.select_native_scrape_cost(src)
    assert SCRAPE.select_native_scrape_cost(result) == result
    kube, cadvisor, api, grafana = result["scrape_configs"]
    assert [cadvisor, api] == src["scrape_configs"][1:3]
    assert kube["metric_relabel_configs"][0]["regex"].endswith("_count")
    assert grafana["scrape_interval"] == "15s"
    assert src["scrape_configs"][-1]["scrape_interval"] == "5s"
