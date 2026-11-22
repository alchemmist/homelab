"""Offline negative control for the monitoring health Service (requires manifest tools)."""

from ci.quality.charts import authentik_accounts, kube_lint, render, targets


def main() -> None:
    """Check that the actual peer satisfies the Service, but not an incorrect selector."""
    releases = {t["id"]: t for t in targets()}
    target = releases["monitoring-k3s-0"]
    resources = render(target)
    peer_resources = render(releases["grafana-mcp-0"])
    assert resources
    assert peer_resources
    (service,) = [
        doc
        for doc in resources
        if doc["kind"] == "Service" and doc["metadata"]["name"] == "monitoring-grafana-mcp-health"
    ]
    (deployment,) = [doc for doc in peer_resources if doc["kind"] == "Deployment"]

    def dangling() -> bool:
        return any(
            item["ruleId"] == "kube-linter-dangling-service"
            for item in kube_lint(target, [service], [deployment])
        )

    assert not dangling()
    service["spec"]["selector"]["app.kubernetes.io/instance"] = "wrong-release"
    assert dangling()

    # Authentik references an Ansible-owned ServiceAccount, not a chart-owned one.
    auth = releases["authentik-0"]
    workloads = [doc for doc in render(auth) or [] if doc["kind"] == "Deployment"]
    assert len(workloads) == 2
    accounts = authentik_accounts()

    def missing() -> set[str]:
        return {
            item["message"]
            for item in kube_lint(auth, workloads, accounts)
            if item["ruleId"] == "kube-linter-non-existent-service-account"
        }

    assert not missing()
    for doc in workloads:
        doc["spec"]["template"]["spec"]["serviceAccountName"] = "absent-runtime"
    assert len(missing()) == len(workloads)

    for target_id, ingress_name, provider_id, service_name in (
        ("litellm-2", "litellm-alias-browser", "litellm-0", "litellm"),
        ("rustfs-0", "rustfs-authentik-browser", "authentik-0", "authentik-server"),
    ):
        target = releases[target_id]
        (ingress,) = [
            r
            for r in render(target) or []
            if r["kind"] == "Ingress" and r["metadata"]["name"] == ingress_name
        ]
        (service,) = [
            r
            for r in render(releases[provider_id]) or []
            if r["kind"] == "Service" and r["metadata"]["name"] == service_name
        ]
        assert ingress["metadata"]["namespace"] == service["metadata"].get(
            "namespace", releases[provider_id]["namespace"]
        )
        routes = [
            p["backend"]["service"] for r in ingress["spec"]["rules"] for p in r["http"]["paths"]
        ]
        for route in routes:
            assert route["name"] == service_name
            assert route["port"]["number"] in {p["port"] for p in service["spec"]["ports"]}
        rule = "kube-linter-dangling-ingress"
        assert not any(f["ruleId"] == rule for f in kube_lint(target, [ingress], [service]))
        routes[0]["name"] = "absent-backend"
        assert any(f["ruleId"] == rule for f in kube_lint(target, [ingress], [service]))


if __name__ == "__main__":
    main()
