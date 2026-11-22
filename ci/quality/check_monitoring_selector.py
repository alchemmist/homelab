"""Offline negative controls for rendered-object lint semantics (requires manifest tools)."""

from ci.quality.charts import (
    apply_release_namespace,
    authentik_accounts,
    kube_lint,
    render,
    targets,
)


def target_stub(identifier: str = "lint-semantics") -> dict[str, str]:
    """Build a synthetic, non-selecting lint target for direct kube_lint controls."""
    return {"id": identifier, "source": "synthetic"}


def probeless(kind: str, name: str) -> dict[str, object]:
    """Build a minimal completion- or serving-shaped workload without any probes."""
    doc = {
        "apiVersion": "batch/v1" if kind in {"Job", "CronJob"} else "apps/v1",
        "kind": kind,
        "metadata": {"name": name},
        "spec": {},
    }
    pod = {
        "containers": [
            {
                "name": "work",
                "image": "example.invalid/app@sha256:" + "0" * 64,
            }
        ]
    }
    if kind == "Job":
        doc["spec"] = {"template": {"metadata": {}, "spec": pod}}
    elif kind == "CronJob":
        doc["spec"] = {
            "schedule": "*/5 * * * *",
            "jobTemplate": {"spec": {"template": {"metadata": {}, "spec": pod}}},
        }
    else:
        doc["spec"] = {"template": {"metadata": {}, "spec": pod}}
    return doc


def probe_rules(findings: list[dict[str, object]]) -> set[str]:
    """Collect only the probe-presence rules from a kube_lint result."""
    return {
        str(item["ruleId"])
        for item in findings
        if item["ruleId"]
        in {"kube-linter-no-liveness-probe", "kube-linter-no-readiness-probe"}
    }


def require(condition: object, detail: str) -> None:
    """Fail the negative control explicitly instead of silently passing it."""
    if not condition:
        raise ValueError("Lint semantics control failed: " + detail)


def release_namespace_semantics() -> None:
    """Check Helm's release-namespace fill enables adjacency, defects included."""
    stub = {"id": "namespace-semantics", "source": "synthetic", "namespace": "release-ns"}
    # Helm-templated objects without an explicit namespace: install assigns the
    # release namespace, so offline lint must respect the same adjacency.
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "serving"},
        "spec": {
            "selector": {
                "app.kubernetes.io/name": "missing",
            },
        },
    }
    docs = apply_release_namespace(
        stub,
        [
            service,
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRole",
                "metadata": {"name": "cluster-scoped"},
                "rules": [],
            },
        ],
    )
    require(
        docs[0]["metadata"]["namespace"] == "release-ns",
        "namespace-inheriting object failed to inherit the release namespace",
    )
    require(
        "namespace" not in docs[1]["metadata"],
        "cluster-scoped object received a release namespace",
    )
    rules = {item["ruleId"] for item in kube_lint(stub, docs)}
    require(
        "kube-linter-use-namespace" not in rules,
        "object assigned its release namespace still reported use-namespace",
    )
    require(
        "kube-linter-dangling-service" in rules,
        "service with a selector matching no pod stopped being reported as dangling",
    )


def defaults_namespace_policy() -> None:
    """Check synthetic default-only renders never claim the shared default namespace."""
    checked = 0
    for target in targets():
        if target["id"].startswith("defaults-"):
            checked += 1
            require(
                target["namespace"] == "quality-check",
                "synthetic defaults render uses the shared default namespace",
            )
    require(checked >= 8, "defaults targets were not inventoried; control is vacuous")


def one_shot_probe_semantics() -> None:
    """Check one-shot Jobs need no scaffolding probes, while real defects stay."""
    stub = target_stub()
    # The absence of a probe is not a defect for a completion-based workload.
    require(
        probe_rules(
            kube_lint(stub, [probeless("Job", "one-shot"), probeless("CronJob", "per-run")])
        )
        == set(),
        "probeless one-shot Job/CronJob reported a probe-presence finding",
    )
    # A traffic-serving Deployment without probes remains a defect.
    require(
        probe_rules(kube_lint(stub, [probeless("Deployment", "serving")]))
        == {"kube-linter-no-liveness-probe", "kube-linter-no-readiness-probe"},
        "probeless serving Deployment lost its probe-presence findings",
    )
    # A declared one-shot probe with a real mismatched defect is still reported.
    job = probeless("Job", "broken-probe")
    container = job["spec"]["template"]["spec"]["containers"][0]
    container["livenessProbe"] = {"tcpSocket": {"port": 8123}}
    require(
        any(
            item["ruleId"] == "kube-linter-liveness-port"
            for item in kube_lint(stub, [job])
        ),
        "one-shot Job with a mismatched probe port was not reported",
    )


def main() -> None:
    """Check that the actual peer satisfies the Service, but not an incorrect selector."""
    one_shot_probe_semantics()
    release_namespace_semantics()
    defaults_namespace_policy()
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

    for target_id, ingress_name, provider_id, service_name in (
        ("litellm-2", "litellm-alias-browser", "litellm-0", "litellm"),
        ("rustfs-0", "rustfs-authentik-browser", "authentik-0", "authentik-server"),
    ):
        target = releases[target_id]
        ingress, = [r for r in render(target) or [] if r["kind"] == "Ingress"
                    and r["metadata"]["name"] == ingress_name]
        service, = [r for r in render(releases[provider_id]) or [] if r["kind"] == "Service"
                    and r["metadata"]["name"] == service_name]
        assert ingress["metadata"]["namespace"] == service["metadata"].get(
            "namespace", releases[provider_id]["namespace"]
        )
        routes = [p["backend"]["service"] for r in ingress["spec"]["rules"]
                  for p in r["http"]["paths"]]
        for route in routes:
            assert route["name"] == service_name
            assert route["port"]["number"] in {p["port"] for p in service["spec"]["ports"]}
        rule = "kube-linter-dangling-ingress"
        assert not any(f["ruleId"] == rule for f in kube_lint(target, [ingress], [service]))
        routes[0]["name"] = "absent-backend"
        assert any(f["ruleId"] == rule for f in kube_lint(target, [ingress], [service]))


if __name__ == "__main__":
    main()
