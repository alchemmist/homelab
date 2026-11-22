"""Offline negative control for the monitoring health Service (requires manifest tools)."""

from charts import kube_lint, render, targets


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


if __name__ == "__main__":
    main()
