"""Rendered PostgreSQL selectors against CloudNativePG's generated Pod labels."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/postgres-platform"


def _render(
    chart: Path = CHART,
    *,
    release: str = "postgres-platform",
    namespace: str = "postgres",
    enabled: bool = True,
) -> list[dict[str, object]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            release,
            str(chart),
            "--namespace",
            namespace,
            "--set",
            f"enabled={str(enabled).lower()}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def _matches(selector: dict[str, object], labels: dict[str, str]) -> bool:
    match_labels = selector.get("matchLabels", selector)
    if not isinstance(match_labels, dict) or any(
        labels.get(key) != value for key, value in match_labels.items()
    ):
        return False
    expressions = selector.get("matchExpressions", [])
    if not isinstance(expressions, list):
        return False
    for expression in expressions:
        if not isinstance(expression, dict):
            return False
        key, operator = expression.get("key"), expression.get("operator")
        values = expression.get("values", [])
        if operator == "In" and (key not in labels or labels[key] not in values):
            return False
        if operator == "NotIn" and key in labels and labels[key] in values:
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            raise AssertionError(
                f"unsupported Kubernetes selector operator: {operator}"
            )
    return True


def test_rendered_cnpg_services_and_policies_follow_operator_role_labels() -> None:
    """CNPG creates these Pods; role changes must move metrics endpoints, not policy scope."""
    objects = _render()
    services = {
        obj["metadata"]["name"]: obj for obj in objects if obj.get("kind") == "Service"
    }
    policies = {
        obj["metadata"]["name"]: obj
        for obj in objects
        if obj.get("kind") == "NetworkPolicy"
    }
    assert set(services) == {"pg-common-primary-metrics", "pg-critical-primary-metrics"}
    assert set(policies) == {
        "pg-common-ingress",
        "pg-critical-ingress",
        "pg-internal-ingress",
        "pg-common-writer-service-probes",
    }

    # CNPG's documented Pod labels: cnpg.io/cluster and cnpg.io/instanceRole.
    # Model promotions by changing only the primary role, as the operator does.
    for cluster in ("pg-common", "pg-critical"):
        policy = policies[f"{cluster}-ingress"]["spec"]
        selected_by_policy = policy["podSelector"]
        selector = services[f"{cluster}-primary-metrics"]["spec"]["selector"]
        assert selector == {
            "cnpg.io/cluster": cluster,
            "cnpg.io/instanceRole": "primary",
        }
        for role in ("primary", "replica"):
            pod = {"cnpg.io/cluster": cluster, "cnpg.io/instanceRole": role}
            assert _matches(selected_by_policy, pod)
            assert _matches(selector, pod) is (role == "primary")
        # Promoting a standby transfers the metrics endpoint without changing ingress policy.
        promoted = {"cnpg.io/cluster": cluster, "cnpg.io/instanceRole": "primary"}
        assert _matches(selector, promoted)
        assert _matches(selected_by_policy, promoted)

    internal = {"cnpg.io/cluster": "pg-internal", "cnpg.io/instanceRole": "primary"}
    assert _matches(policies["pg-internal-ingress"]["spec"]["podSelector"], internal)
    # 77c83ffd retired the standalone async standby and its inbound peer grant.
    assert all(obj["metadata"]["name"] != "pg-critical-async" for obj in objects)
    critical = policies["pg-critical-ingress"]["spec"]["ingress"]
    assert not any(peer.get("podSelector", {}).get("matchLabels", {}).get("cnpg.io/cluster")
                   == "pg-critical-async" for rule in critical for peer in rule["from"])


def test_database_client_and_probe_policy_peers_remain_narrow() -> None:
    """Render regressions guard the explicit namespaces, labels, and ports for real clients."""
    objects = _render()
    policies = {
        obj["metadata"]["name"]: obj
        for obj in objects
        if obj.get("kind") == "NetworkPolicy"
    }
    common = policies["pg-common-ingress"]["spec"]["ingress"]
    critical = policies["pg-critical-ingress"]["spec"]["ingress"]
    common_clients = common[2]
    critical_clients = critical[2]
    namespaces = {
        peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        for peer in common_clients["from"]
        if "namespaceSelector" in peer
    }
    assert namespaces == {
        "llm",
        "monori",
        "openhands",
        "wiki",
        "uptime-kuma",
        "lms",
        "automation",
        "umami",
        "socrat-bot",
        "harbor",
        "wishlist",
        "cattle-monitoring-system",
    }
    assert common_clients["ports"] == [{"port": 5432}]
    assert critical_clients["ports"] == [{"port": 5432}]
    assert {"ipBlock" in peer for peer in common_clients["from"]} == {False, True}
    assert {"ipBlock" in peer for peer in critical_clients["from"]} == {False}

    probe = policies["pg-common-writer-service-probes"]["spec"]
    peer = probe["ingress"][0]["from"][0]
    assert (
        peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        == "cattle-monitoring-system"
    )
    assert peer["podSelector"]["matchLabels"] == {"app": "monitoring-service-probes"}
    assert probe["ingress"][0]["ports"] == [{"port": 5432, "protocol": "TCP"}]

    # The permitted probe workload is owned by the monitoring-k3s chart, not this one.
    monitor = _render(
        ROOT / "charts/monitoring-k3s",
        release="monitoring-k3s",
        namespace="cattle-monitoring-system",
        enabled=False,
    )
    deployment = next(
        obj
        for obj in monitor
        if obj.get("kind") == "Deployment"
        and obj["metadata"]["name"] == "monitoring-service-probes"
    )
    assert deployment["metadata"]["namespace"] == "cattle-monitoring-system"
    template = deployment["spec"]["template"]["metadata"]["labels"]
    assert template["app"] == "monitoring-service-probes"
    assert _matches(peer["podSelector"], template)
