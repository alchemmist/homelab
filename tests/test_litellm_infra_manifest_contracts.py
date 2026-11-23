"""Offline render checks for LiteLLM infrastructure's cross-release contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from ci.quality import charts


def render(release: str, chart: str, *values: str) -> list[dict]:
    """Render one actual owning chart in its Argo destination namespace."""
    target = {
        "release": release,
        "chart": ROOT / chart,
        "namespace": "llm",
        "values": [ROOT / value for value in values],
        "parameters": [],
    }
    result = charts.render(target)
    assert result, f"empty or failed Helm render for {chart}"
    return result


def test_gateway_and_monitoring_policies_select_real_cross_release_workloads() -> None:
    """Compose vLLM, LiteLLM and monitoring renders before judging policy selectors."""
    vllm = render("vllm", "charts/vllm", "charts/vllm/values.yaml")
    litellm = render("litellm", "charts/litellm", "deploy/platform/litellm/values.yaml")
    monitoring = render("monitoring-llm", "charts/monitoring-llm")
    infra = render("litellm-infra", "charts/litellm-infra")
    composed = vllm + litellm + monitoring + infra

    workload_labels = [
        obj["spec"]["template"]["metadata"]["labels"]
        for obj in composed
        if obj.get("kind") == "Deployment"
    ]
    policies = [obj for obj in composed if obj.get("kind") == "NetworkPolicy"]
    gateway_policy = next(obj for obj in policies if obj["metadata"]["name"] == "vllm-gateway-only")
    monitor_policy = next(obj for obj in policies if obj["metadata"]["name"] == "vllm-monitoring")

    assert any(
        labels.get("app") == "vllm"
        and gateway_policy["spec"]["podSelector"]["matchLabels"].items() <= labels.items()
        for labels in workload_labels
    )
    assert any(
        labels.get("app.kubernetes.io/name") == "litellm"
        and labels.get("app.kubernetes.io/instance") == "litellm"
        and gateway_policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"].items()
        <= labels.items()
        for labels in workload_labels
    )
    assert gateway_policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]
    assert any(
        labels.get("app") == "vllm"
        and monitor_policy["spec"]["podSelector"]["matchLabels"].items() <= labels.items()
        for labels in workload_labels
    )
    monitor_peer = monitor_policy["spec"]["ingress"][0]["from"][0]
    assert (
        monitor_peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        == "cattle-monitoring-system"
    )
    prometheus = render(
        "kube-prometheus-stack",
        "charts/prometheus",
        "charts/prometheus/alert-graphs.values.yaml",
    )
    prometheus_service = next(
        obj
        for obj in prometheus
        if obj.get("kind") == "Service"
        and obj["metadata"]["name"] == "kube-prometheus-stack-prometheus"
    )
    assert monitor_peer["podSelector"]["matchLabels"] == prometheus_service["spec"]["selector"]


def test_branding_runtime_probes_and_read_only_contract_render() -> None:
    """Exercise rendered Nginx lifecycle and init-container filesystem policy."""
    objects = render("litellm-infra", "charts/litellm-infra")
    deployment = next(
        obj
        for obj in objects
        if obj.get("kind") == "Deployment" and obj["metadata"]["name"] == "litellm-branding"
    )
    pod = deployment["spec"]["template"]["spec"]
    init = next(
        container
        for container in pod["initContainers"]
        if container["name"] == "require-existing-branding"
    )
    nginx = next(container for container in pod["containers"] if container["name"] == "nginx")

    assert init["securityContext"]["readOnlyRootFilesystem"] is True
    assert init["volumeMounts"][0]["readOnly"] is True
    assert nginx["securityContext"]["readOnlyRootFilesystem"] is True
    assert nginx["livenessProbe"] == {
        "httpGet": {"path": "/health", "port": "http"},
        "periodSeconds": 30,
        "timeoutSeconds": 5,
        "failureThreshold": 3,
    }
