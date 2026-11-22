"""Offline composed-render contract for LLM monitoring policy targets."""

import pathlib
import shutil
import unittest
from typing import Any

import yaml

from scripts.quality.common import command

ROOT = pathlib.Path(__file__).resolve().parents[1]


def selector_matches(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    """Apply Kubernetes label-selector semantics; unsupported operators fail closed."""
    if not all(labels.get(key) == value for key, value in selector.get("matchLabels", {}).items()):
        return False
    for expression in selector.get("matchExpressions", []):
        key, operator = expression["key"], expression["operator"]
        values = expression.get("values", [])
        present = key in labels
        if operator == "In" and (not present or labels[key] not in values):
            return False
        if operator == "NotIn" and present and labels[key] in values:
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            return False
    return True


@unittest.skipUnless(shutil.which("helm"), "helm unavailable")
class MonitoringLlmNetworkPolicyTests(unittest.TestCase):
    """Verify monitoring policies against separately rendered workload owners."""

    def render(
        self, release: str, chart: str, namespace: str, *values: str
    ) -> list[dict[str, Any]]:
        """Render one Git-owned chart without contacting a cluster."""
        helm = shutil.which("helm")
        assert helm is not None
        args = [helm, "template", release, chart, "--namespace", namespace]
        for value in values:
            args += ["--values", value]
        result = command(args)
        return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]

    def test_vllm_policy_selects_only_the_separately_owned_vllm_pod(self) -> None:
        """The ingress policy matches the actual vLLM release label, not a guess."""
        policy_docs = self.render("monitoring-llm", "charts/monitoring-llm", "llm")
        vllm_docs = self.render("vllm", "charts/vllm", "llm")
        policy = next(
            doc
            for doc in policy_docs
            if doc.get("kind") == "NetworkPolicy" and doc["metadata"]["name"] == "vllm-monitoring"
        )
        workload = next(doc for doc in vllm_docs if doc.get("kind") == "Deployment")
        selector = policy["spec"]["podSelector"]
        workload_labels = workload["spec"]["template"]["metadata"]["labels"]
        assert selector == {"matchLabels": {"app": "vllm"}}
        assert selector_matches(selector, workload_labels)
        assert workload["metadata"].get("namespace", "llm") == policy["metadata"].get("namespace", "llm")
        assert policy["spec"]["policyTypes"] == ["Ingress"]
        assert policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]
        peers = policy["spec"]["ingress"][0]["from"]
        assert peers == [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "cattle-monitoring-system"}
                },
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "prometheus",
                        "operator.prometheus.io/name": "kube-prometheus-stack-prometheus",
                    }
                },
            }
        ]
        # Render the real Argo-owned prometheus release. Its Service selector is
        # the operator-backed Pod label contract; no synthetic workload is used.
        prometheus_docs = self.render(
            "kube-prometheus-stack",
            "charts/prometheus",
            "cattle-monitoring-system",
            "charts/prometheus/alert-graphs.values.yaml",
        )
        prometheus_service = next(
            obj for obj in prometheus_docs
            if obj.get("kind") == "Service"
            and obj["metadata"]["name"] == "kube-prometheus-stack-prometheus"
        )
        assert prometheus_service["spec"]["selector"] == peers[0]["podSelector"]["matchLabels"]

    def test_target_selector_fails_closed_without_the_separately_rendered_owner(self) -> None:
        """Removing or changing the real owner must not manufacture a selector match."""
        policies = self.render("monitoring-llm", "charts/monitoring-llm", "llm")
        owners = self.render("vllm", "charts/vllm", "llm")
        policy = next(
            doc for doc in policies
            if doc.get("kind") == "NetworkPolicy" and doc["metadata"]["name"] == "vllm-monitoring"
        )
        workload = next(doc for doc in owners if doc.get("kind") == "Deployment")
        selector = policy["spec"]["podSelector"]
        labels = workload["spec"]["template"]["metadata"]["labels"]
        assert selector_matches(selector, labels)
        assert not selector_matches(selector, {**labels, "app": "not-vllm"})
        assert not any(
            selector_matches(selector, obj.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}))
            for obj in policies
            if obj.get("kind") in {"Deployment", "DaemonSet", "StatefulSet", "Job"}
        )

    def test_status_policy_remains_narrow_pending_its_external_owner(self) -> None:
        """Do not broaden an unverified status selector to mask its dangling target."""
        docs = self.render("monitoring-llm", "charts/monitoring-llm", "llm")
        policy = next(
            doc
            for doc in docs
            if doc.get("kind") == "NetworkPolicy"
            and doc["metadata"]["name"] == "monitoring-llm-status"
        )
        assert policy["spec"]["podSelector"]["matchLabels"] == {"app": "monitoring-llm-status"}
        assert policy["spec"]["policyTypes"] == ["Ingress"]
        assert policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 9108}]
        peers = policy["spec"]["ingress"][0]["from"]
        assert peers[0]["podSelector"]["matchLabels"] == {
            "app.kubernetes.io/name": "prometheus",
            "operator.prometheus.io/name": "kube-prometheus-stack-prometheus",
        }
