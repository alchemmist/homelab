"""CPU profiles are a separate private stack, not renamed tracing spans."""

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

type Json = "str | int | float | bool | None | Sequence[Json] | Mapping[str, Json]"


def child(parent: Mapping[str, Json], key: str) -> Mapping[str, Json]:
    """Narrow the value stored under ``key`` to a nested mapping."""
    value = parent[key]
    assert isinstance(value, Mapping)
    return value


def render(chart: str, *args: str) -> list[Mapping[str, Json]]:
    """Render the chart's helm template into parsed YAML documents."""
    return [
        d
        for d in yaml.safe_load_all(
            subprocess.check_output(
                ["helm", "template", chart, str(ROOT / "charts" / chart), *args], text=True
            )
        )
        if d
    ]


def test_backend_is_persistent_bounded_unprivileged_and_private() -> None:
    """Keep Pyroscope persistent, bounded, unprivileged, and cluster-private."""
    docs = render("pyroscope")
    dep = next(d for d in docs if d["kind"] == "Deployment")
    pod = child(child(child(dep, "spec"), "template"), "spec")
    pod_security = child(pod, "securityContext")
    assert pod["automountServiceAccountToken"] is False
    assert pod_security["runAsNonRoot"] is True
    containers = pod["containers"]
    assert isinstance(containers, list)
    c = containers[0]
    assert isinstance(c, Mapping)
    c_security = child(c, "securityContext")
    assert child(c_security, "capabilities")["drop"] == ["ALL"]
    assert c_security["readOnlyRootFilesystem"] is True
    assert c_security["allowPrivilegeEscalation"] is False
    assert "@sha256:" in str(c["image"])
    args = c["args"]
    assert isinstance(args, list)
    assert "-architecture.storage=v2" in args
    assert "-retention-period=168h" in args
    assert "-usage-stats.enabled=false" in args
    assert child(child(c, "resources"), "limits")["memory"] == "1Gi"
    assert c["workingDir"] == "/data"
    spec = child(dep, "spec")
    assert spec["replicas"] == 1
    assert child(spec, "strategy")["type"] == "Recreate"
    claim = yaml.safe_load((ROOT / "deploy/storage/pyroscope-drill/pvc.yaml").read_text())
    volumes = pod["volumes"]
    assert isinstance(volumes, list)
    data = next(v for v in volumes if isinstance(v, Mapping) and v["name"] == "data")
    assert data == {
        "name": "data",
        "persistentVolumeClaim": {"claimName": claim["metadata"]["name"]},
    }
    assert any(
        d["kind"] == "PersistentVolumeClaim" and child(d, "metadata")["name"] == "pyroscope-data"
        for d in docs
    )
    service = next(d for d in docs if d["kind"] == "Service")
    assert child(service, "spec")["type"] == "ClusterIP"
    assert not any(d["kind"] == "Ingress" for d in docs)
    policy = child(next(d for d in docs if d["kind"] == "NetworkPolicy"), "spec")
    policy_types = policy["policyTypes"]
    assert isinstance(policy_types, list)
    assert set(policy_types) == {"Ingress", "Egress"}
    ingress = policy["ingress"]
    assert isinstance(ingress, list)
    rule = ingress[0]
    assert isinstance(rule, Mapping)
    assert rule["ports"] == [{"protocol": "TCP", "port": 4040}]
    peers = rule["from"]
    assert isinstance(peers, list)
    assert {
        child(child(p, "podSelector"), "matchLabels")["app.kubernetes.io/name"]
        for p in peers
        if isinstance(p, Mapping)
    } == {"lms", "grafana"}
    assert all(isinstance(p, Mapping) and "namespaceSelector" in p for p in peers)


def test_flamegraph_is_native_pyroscope_not_a_span_waterfall() -> None:
    """Expose native Pyroscope flamegraphs instead of a tracing waterfall."""
    docs = render("pyroscope")
    cm = next(d for d in docs if child(d, "metadata")["name"] == "service-cpu-profiling-dashboard")
    d = json.loads(str(child(cm, "data")["service-cpu-profiling.json"]))
    assert d["uid"] == "service-cpu-profiling"
    assert d["panels"][0]["type"] == "flamegraph"
    assert d["panels"][1]["type"] == "timeseries"
    assert not any(p["type"] == "traces" for p in d["panels"])
    for panel in d["panels"]:
        assert panel["datasource"]["uid"] == "pyroscope"
        assert panel["targets"][0]["profileTypeId"] == "process_cpu:cpu:nanoseconds:cpu:nanoseconds"
    assert d["templating"]["list"][0]["query"]["labelName"] == "service_name"
    assert (
        d["templating"]["list"][0]["query"]["profileTypeId"]
        == "process_cpu:cpu:nanoseconds:cpu:nanoseconds"
    )
    source = next(x for x in docs if child(x, "metadata")["name"] == "pyroscope-grafana-datasource")
    ds = yaml.safe_load(str(child(source, "data")["pyroscope-datasource.yaml"]))["datasources"][0]
    assert ds["uid"] == "pyroscope"
    assert ds["editable"] is False
    assert ds["url"] == "http://pyroscope.cattle-monitoring-system.svc.cluster.local:4040"


def test_lms_profiling_is_opt_in_and_production_enabled() -> None:
    """Enable LMS profiling only for the production values overlay."""
    for args, enabled in [
        ((), False),
        (("-f", str(ROOT / "deploy/lms/values.yaml")), True),
    ]:
        docs = render("lms", *args)
        dep = next(
            d for d in docs if d["kind"] == "Deployment" and child(d, "metadata")["name"] == "lms"
        )
        pod = child(child(child(dep, "spec"), "template"), "spec")
        containers = pod["containers"]
        assert isinstance(containers, list)
        container = containers[0]
        assert isinstance(container, Mapping)
        env_entries = container["env"]
        assert isinstance(env_entries, list)
        env = {str(e["name"]): e.get("value") for e in env_entries if isinstance(e, Mapping)}
        assert (env.get("LMS_PROFILING_ENABLED") == "1") == enabled
        if enabled:
            assert str(env["LMS_PROFILING_ENDPOINT"]).endswith(".svc.cluster.local:4040")
