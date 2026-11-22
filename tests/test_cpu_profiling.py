"""CPU profiles are a separate private stack, not renamed tracing spans."""

import json
import subprocess
from pathlib import Path
from typing import TypedDict, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Metadata(TypedDict):
    """Shared Kubernetes object metadata section rendered by every chart."""

    name: str


class Security(TypedDict):
    """Container security knobs rendered by the chart."""

    capabilities: dict[str, object]
    readOnlyRootFilesystem: bool
    allowPrivilegeEscalation: bool


class Container(TypedDict):
    """One rendered workload container with its resource profile."""

    image: str
    args: list[str]
    env: list[dict[str, object]]
    securityContext: Security
    resources: dict[str, dict[str, str]]
    workingDir: str


class PodSpec(TypedDict):
    """Rendered pod spec of a Deployment's template."""

    automountServiceAccountToken: bool
    securityContext: dict[str, object]
    containers: list[Container]
    volumes: list[dict[str, object]]


class Template(TypedDict):
    """Pod template inside a Deployment spec."""

    spec: PodSpec


class DeploymentSpec(TypedDict):
    """Deployment-level rollout configuration."""

    replicas: int
    strategy: dict[str, str]
    template: Template


class DeploymentDoc(TypedDict):
    """A rendered Deployment manifest."""

    kind: str
    metadata: Metadata
    spec: DeploymentSpec


class ServiceDoc(TypedDict):
    """A rendered Service manifest."""

    kind: str
    metadata: Metadata
    spec: dict[str, str]


class Peer(TypedDict, total=False):
    """One network-policy peer selector."""

    podSelector: dict[str, dict[str, str]]
    namespaceSelector: dict[str, object]


class PolicySpec(TypedDict):
    """Rendered NetworkPolicy spec."""

    policyTypes: list[str]
    ingress: list[dict[str, object]]


class PolicyDoc(TypedDict):
    """A rendered NetworkPolicy manifest."""

    kind: str
    metadata: Metadata
    spec: PolicySpec


class ConfigMapDoc(TypedDict):
    """A rendered ConfigMap manifest."""

    kind: str
    metadata: Metadata
    data: dict[str, str]


def render(chart: str, *args: str) -> list[dict[str, object]]:
    """Render one chart offline and return its non-empty YAML documents."""
    return [
        d
        for d in yaml.safe_load_all(
            subprocess.check_output(
                ["helm", "template", chart, str(ROOT / "charts" / chart), *args],
                text=True,
            )
        )
        if d
    ]


def test_backend_is_persistent_bounded_unprivileged_and_private() -> None:
    """Keep Pyroscope persistent, bounded, unprivileged, and cluster-private."""
    docs = render("pyroscope")
    dep = cast("DeploymentDoc", next(d for d in docs if d["kind"] == "Deployment"))
    pod = dep["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert "@sha256:" in c["image"]
    assert "-architecture.storage=v2" in c["args"]
    assert "-retention-period=168h" in c["args"]
    assert "-usage-stats.enabled=false" in c["args"]
    assert c["resources"]["limits"]["memory"] == "1Gi"
    assert c["workingDir"] == "/data"
    assert dep["spec"]["replicas"] == 1
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    claim = yaml.safe_load((ROOT / "deploy/storage/pyroscope-drill/pvc.yaml").read_text())
    data = next(v for v in pod["volumes"] if v["name"] == "data")
    assert data == {
        "name": "data",
        "persistentVolumeClaim": {"claimName": claim["metadata"]["name"]},
    }
    assert any(
        d["kind"] == "PersistentVolumeClaim"
        and cast("Metadata", d["metadata"])["name"] == "pyroscope-data"
        for d in docs
    )
    service = next(d for d in docs if d["kind"] == "Service")
    assert cast("ServiceDoc", service)["spec"]["type"] == "ClusterIP"
    assert not any(d["kind"] == "Ingress" for d in docs)
    policy = cast("PolicyDoc", next(d for d in docs if d["kind"] == "NetworkPolicy"))["spec"]
    assert set(policy["policyTypes"]) == {"Ingress", "Egress"}
    assert policy["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 4040}]
    peers = cast("list[Peer]", policy["ingress"][0]["from"])
    assert {p["podSelector"]["matchLabels"]["app.kubernetes.io/name"] for p in peers} == {
        "lms",
        "grafana",
    }
    assert all("namespaceSelector" in p for p in peers)


def test_flamegraph_is_native_pyroscope_not_a_span_waterfall() -> None:
    """Expose native Pyroscope flamegraphs instead of a tracing waterfall."""
    docs = render("pyroscope")
    cm = cast(
        "ConfigMapDoc",
        next(
            d
            for d in docs
            if cast("Metadata", d["metadata"])["name"] == "service-cpu-profiling-dashboard"
        ),
    )
    d = json.loads(cm["data"]["service-cpu-profiling.json"])
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
    source = cast(
        "ConfigMapDoc",
        next(
            x
            for x in docs
            if cast("Metadata", x["metadata"])["name"] == "pyroscope-grafana-datasource"
        ),
    )
    ds = yaml.safe_load(source["data"]["pyroscope-datasource.yaml"])["datasources"][0]
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
        dep = cast(
            "DeploymentDoc",
            next(
                d
                for d in docs
                if d["kind"] == "Deployment" and cast("Metadata", d["metadata"])["name"] == "lms"
            ),
        )
        env = {
            e["name"]: e.get("value")
            for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]
        }
        assert (env.get("LMS_PROFILING_ENABLED") == "1") == enabled
        if enabled:
            assert cast("str", env["LMS_PROFILING_ENDPOINT"]).endswith(".svc.cluster.local:4040")
