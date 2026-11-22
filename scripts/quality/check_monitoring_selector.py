"""Offline negative control for the monitoring health Service (requires manifest tools)."""

from charts import authentik_accounts, kube_lint, render, targets


def main() -> None:
    """Check that the actual peer satisfies the Service, but not an incorrect selector."""
    releases = {t["id"]: t for t in targets()}
    target = releases["monitoring-k3s-0"]
    resources = render(target)
    peer_resources = render(releases["grafana-mcp-0"])
    assert resources and peer_resources
    (service,) = [
        doc
        for doc in resources
        if doc["kind"] == "Service"
        and doc["metadata"]["name"] == "monitoring-grafana-mcp-health"
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
        return {item["message"] for item in kube_lint(auth, workloads, accounts)
                if item["ruleId"] == "kube-linter-non-existent-service-account"}

    assert not missing()
    for doc in workloads:
        doc["spec"]["template"]["spec"]["serviceAccountName"] = "absent-runtime"
    assert len(missing()) == len(workloads)


if __name__ == "__main__":
    main()
