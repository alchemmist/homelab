"""Offline composed-render contract for LLM monitoring policy targets."""

import pathlib
import shutil
import unittest
from typing import Any

import yaml

from scripts.quality.common import command

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("helm"), "helm unavailable")
class MonitoringLlmNetworkPolicyTests(unittest.TestCase):
    """Verify monitoring policies against separately rendered workload owners."""

    def render(self, release: str, chart: str, namespace: str) -> list[dict[str, Any]]:
        """Render one Git-owned chart without contacting a cluster."""
        helm = shutil.which("helm")
        assert helm is not None
        result = command([helm, "template", release, chart, "--namespace", namespace])
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
        selector = policy["spec"]["podSelector"]["matchLabels"]
        workload_labels = workload["spec"]["template"]["metadata"]["labels"]
        assert selector == {"app": "vllm"}
        assert all(workload_labels.get(key) == value for key, value in selector.items())
        assert policy["spec"]["policyTypes"] == ["Ingress"]
        assert policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]
        assert policy["spec"]["ingress"][0]["from"] == [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "cattle-monitoring-system"}
                },
                "podSelector": {"matchLabels": {"prometheus": "kube-prometheus-stack-prometheus"}},
            }
        ]

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
        assert policy["spec"]["ingress"][0]["from"] == [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "cattle-monitoring-system"}
                },
                "podSelector": {"matchLabels": {"prometheus": "kube-prometheus-stack-prometheus"}},
            }
        ]
