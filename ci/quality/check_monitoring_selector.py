"""Offline negative control for the monitoring health Service (requires manifest tools)."""

from ci.quality.charts import RenderTarget, authentik_accounts, kube_lint, render, targets
from ci.quality.closed_root_backend import entries, plain, view

HEALTH_SERVICE = "monitoring-grafana-mcp-health"
DANGLING_SERVICE = "kube-linter-dangling-service"
DANGLING_INGRESS = "kube-linter-dangling-ingress"
MISSING_ACCOUNT = "kube-linter-non-existent-service-account"
EXPECTED_AUTHENTIK_DEPLOYMENTS = 2
INGRESS_CHECKS = (
    ("litellm-2", "litellm-alias-browser", "litellm-0", "litellm"),
    ("rustfs-0", "rustfs-authentik-browser", "authentik-0", "authentik-server"),
)


def require(condition: object, what: str) -> None:
    """Stop the negative control with a named reason when an expectation breaks."""
    if not condition:
        msg = "Monitoring negative control failed: " + what
        raise ValueError(msg)


def docs(target: RenderTarget, kind: str) -> list[dict[str, object]]:
    """Select the kind documents from one render, or stop if the render is empty."""
    resources = render(target)
    require(resources, "render of " + plain(target["id"]) + " must not be empty")
    return [doc for doc in resources or [] if plain(doc["kind"]) == kind]


def by_name(documents: list[dict[str, object]], kind: str, name: str) -> dict[str, object]:
    """Return the single document of a kind carrying the given metadata name."""
    (chosen,) = [
        doc
        for doc in documents
        if plain(doc["kind"]) == kind and plain(view(doc["metadata"])["name"]) == name
    ]
    return chosen


def dangling(
    target: RenderTarget, checked: list[dict[str, object]], peers: list[dict[str, object]]
) -> bool:
    """Tell whether kube-linter reports the dangling-service rule for these objects."""
    return any(
        plain(item["ruleId"]) == DANGLING_SERVICE for item in kube_lint(target, checked, peers)
    )


def main() -> None:
    """Check that the actual peer satisfies the Service, but not an incorrect selector."""
    releases = {plain(t["id"]): t for t in targets()}
    target = releases["monitoring-k3s-0"]
    peer = releases["grafana-mcp-0"]
    services = docs(target, "Service")
    deployments = docs(peer, "Deployment")
    service = by_name(services, "Service", HEALTH_SERVICE)
    (deployment,) = deployments
    require(not dangling(target, [service], [deployment]), "the health Service must not dangle")
    view(view(service["spec"])["selector"])["app.kubernetes.io/instance"] = "wrong-release"
    require(dangling(target, [service], [deployment]), "a wrong selector must dangle")

    # Authentik references an Ansible-owned ServiceAccount, not a chart-owned one.
    auth = releases["authentik-0"]
    workloads = docs(auth, "Deployment")
    require(len(workloads) == EXPECTED_AUTHENTIK_DEPLOYMENTS, "authentik deployment count")
    accounts = authentik_accounts()

    def missing() -> set[str]:
        return {
            plain(item["message"])
            for item in kube_lint(auth, workloads, accounts)
            if plain(item["ruleId"]) == MISSING_ACCOUNT
        }

    require(not missing(), "authentik accounts must all exist")
    for doc in workloads:
        view(view(view(view(doc["spec"])["template"])["spec"]))["serviceAccountName"] = (
            "absent-runtime"
        )
    require(
        len(missing()) == len(workloads),
        "renaming every serviceAccountName must surface the missing-account rule",
    )

    for target_id, ingress_name, provider_id, service_name in INGRESS_CHECKS:
        target = releases[target_id]
        cluster = docs(target, "Ingress")
        (ingress,) = [
            doc for doc in cluster if plain(view(doc["metadata"])["name"]) == ingress_name
        ]
        service = by_name(docs(releases[provider_id], "Service"), "Service", service_name)
        require(
            plain(view(ingress["metadata"])["namespace"])
            == plain(
                view(service["metadata"]).get("namespace", releases[provider_id]["namespace"])
            ),
            "ingress/service namespaces must agree",
        )
        routes = [
            view(view(p)["backend"])["service"]
            for r in entries(view(ingress["spec"])["rules"])
            for p in entries(view(view(r)["http"])["paths"])
        ]
        for route in routes:
            require(
                plain(view(route)["name"]) == service_name,
                "every route must target the named Service",
            )
            require(
                view(view(route)["port"])["number"]
                in {view(view(p)["port"]) for p in entries(view(service["spec"])["ports"])},
                "every route port must exist on the Service",
            )
        require(
            not any(
                plain(f["ruleId"]) == DANGLING_INGRESS
                for f in kube_lint(target, [ingress], [service])
            ),
            "the actual ingress backend must not dangle",
        )
        view(routes[0])["name"] = "absent-backend"
        require(
            any(
                plain(f["ruleId"]) == DANGLING_INGRESS
                for f in kube_lint(target, [ingress], [service])
            ),
            "an absent backend must dangle",
        )


if __name__ == "__main__":
    main()
