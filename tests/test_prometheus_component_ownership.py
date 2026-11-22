"""Exactly the same 77 resources, split between five single-service Applications."""

import copy
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch

import pytest
import yaml

from tests.portable_placement import home_affinity

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = (
    "prometheus",
    "alertmanager",
    "prometheus-operator",
    "node-exporter",
    "kube-state-metrics",
)
CLUSTER = {
    "CustomResourceDefinition",
    "ClusterRole",
    "ClusterRoleBinding",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
}
yaml.SafeLoader.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
)


class _Metadata(TypedDict):
    name: str


class _Probe(TypedDict):
    exec: dict[str, list[str]]


class _Container(TypedDict, total=False):
    name: str
    image: str
    args: list[str]
    securityContext: dict[str, object]
    ports: list[dict[str, object]]
    volumeMounts: list[dict[str, object]]
    readinessProbe: _Probe


class _Spec(TypedDict, total=False):
    containers: list[_Container]
    type: str
    podMetadata: dict[str, dict[str, str]]
    volumes: list[dict[str, object]]


class _RenderedDoc(TypedDict, total=False):
    kind: str
    metadata: _Metadata
    data: dict[str, str]
    spec: _Spec


@lru_cache(maxsize=None)
def render(name) -> list[_RenderedDoc]:
    """Test behavior for render."""
    text = subprocess.check_output(
        [
            "helm",
            "template",
            "kube-prometheus-stack",
            str(ROOT / "charts" / name),
            "-n",
            "cattle-monitoring-system",
            "--include-crds",
        ],
        text=True,
    )
    return [
        d
        for d in yaml.safe_load_all(text)
        if d and not (d["metadata"].get("annotations") or {}).get("helm.sh/hook")
    ]


def key(d) -> str:
    """Test behavior for key."""
    return "/".join(
        [
            d["kind"],
            ""
            if d["kind"] in CLUSTER
            else d["metadata"].get("namespace", "cattle-monitoring-system"),
            d["metadata"]["name"],
        ]
    )


def software_update_extension(document) -> None:
    """Review the one additive receiver without refreshing any handoff hash."""
    assert document == {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "software-update-otel",
            "namespace": "cattle-monitoring-system",
        },
        "data": {"collector.yaml": document["data"]["collector.yaml"]},
    }
    assert yaml.safe_load(document["data"]["collector.yaml"]) == {
        "receivers": {
            "prometheus/software_updates": {
                "config": {
                    "scrape_configs": [
                        {
                            "job_name": "monitoring-update-watch",
                            "scrape_interval": "60s",
                            "scrape_timeout": "10s",
                            "static_configs": [
                                {
                                    "targets": [
                                        "monitoring-update-watch.cattle-monitoring-system.svc.cluster.local:8080"
                                    ],
                                    "labels": {
                                        "namespace": "cattle-monitoring-system",
                                        "service": "monitoring-update-watch",
                                    },
                                }
                            ],
                        },
                        {
                            "job_name": "socrat-actionable-alerts",
                            "metrics_path": "/actionable-alerts",
                            "scrape_interval": "30s",
                            "scrape_timeout": "8s",
                            "static_configs": [
                                {
                                    "targets": [
                                        "monitoring-update-watch.cattle-monitoring-system.svc.cluster.local:8080"
                                    ],
                                    "labels": {
                                        "namespace": "cattle-monitoring-system",
                                        "service": "monitoring-update-watch",
                                    },
                                }
                            ],
                        },
                    ]
                }
            }
        },
        "service": {
            "pipelines": {
                "metrics": {
                    "receivers": ["prometheus", "otlp", "prometheus/software_updates"]
                }
            }
        },
    }, "Software update receiver scope changed"


def migration_payload(document) -> dict[str, object]:
    """Check declared runtime overrides before comparing the unchanged handoff payload."""
    kind = document["kind"]
    name = document["metadata"]["name"]
    # Verify the exact registry-resolved tag+digest before comparing to the
    # original tag-only handoff. Never normalize an arbitrary image suffix.
    pinned = {
        "kube-prometheus-stack-operator": (
            "quay.io/prometheus-operator/prometheus-operator:v0.94.1",
            "sha256:7c88d4e7bae63bd8d0f8da986054337c23b4472fa8d3c6817f5bc4b8407a2d6a",
        ),
        "kube-prometheus-stack-kube-state-metrics": (
            "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0",
            "sha256:42cfe3723a5f058171c627537fb57a3ea0f26e4380fa18555a95cb1a1b4cfc5b",
        ),
        "kube-prometheus-stack-prometheus-node-exporter": (
            "quay.io/prometheus/node-exporter:v1.12.1-distroless",
            "sha256:8c9bac11973b94b59be88d6e11fee4429aa743c8846cdc75d65b18db33f6a106",
        ),
    }
    if kind in {"Deployment", "DaemonSet"} and name in pinned:
        document = copy.deepcopy(document)
        tag, digest = pinned[name]
        (container,) = document["spec"]["template"]["spec"]["containers"]
        assert container["image"] == tag + "@" + digest
        container["image"] = tag
    if (kind, name) == ("PrometheusRule", "kube-prometheus-stack-node-exporter"):
        result = copy.deepcopy(document)
        (group,) = result["spec"]["groups"]
        assert not any(
            rule.get("alert") == "NodeSystemSaturation" for rule in group["rules"]
        )
        # Restore the one replaced upstream rule for comparison with the frozen handoff.
        group["rules"].insert(
            17,
            json.loads(
                (ROOT / "tests/fixtures/upstream-node-saturation.json").read_text()
            ),
        )
        return result
    if (kind, name) == ("PrometheusRule", "kube-prometheus-stack-kubernetes-apps"):
        # Undo just the retired upstream rule for comparison to the frozen handoff.
        result = copy.deepcopy(document)
        (group,) = result["spec"]["groups"]
        assert group["name"] == "kubernetes-apps"
        assert not any(rule.get("alert") == "KubeJobFailed" for rule in group["rules"])
        group["rules"].insert(
            13,
            {
                "alert": "KubeJobFailed",
                "expr": 'kube_job_failed{job="kube-state-metrics", namespace=~".*"}  > 0',
                "for": "15m",
                "labels": {"severity": "warning"},
                "annotations": {
                    "description": "Job {{ $labels.namespace }}/{{ $labels.job_name }} failed to complete. "
                    "Removing failed job after investigation should clear this alert on cluster {{ $labels.cluster }}.",
                    "runbook_url": "https://runbooks.prometheus-operator.dev/runbooks/kubernetes/kubejobfailed",
                    "summary": "Job failed to complete.",
                },
            },
        )
        return result
    if kind not in {"Prometheus", "Alertmanager", "Deployment"} and (kind, name) != (
        "ServiceMonitor",
        "kube-prometheus-stack-apiserver",
    ):
        return cast("dict[str, object]", document)
    result = copy.deepcopy(document)
    spec = result["spec"]
    if kind == "ServiceMonitor":
        (endpoint,) = spec["endpoints"]
        (rule,) = endpoint["relabelings"]
        assert rule["regex"] == r"10\.250\.0\.(1|3|41):6443"
        rule["regex"] = r"10\.250\.0\.(1|3|5):6443"
        return result
    if kind in {"Alertmanager", "Deployment"}:
        pod = spec if kind == "Alertmanager" else spec["template"]["spec"]
        assert pod["nodeSelector"] == {"kubernetes.io/os": "linux"}
        if kind == "Deployment":
            assert pod.pop("affinity") == home_affinity()
        if name == "kube-prometheus-stack-kube-state-metrics":
            pod["nodeSelector"].clear()
        pod["nodeSelector"]["kubernetes.io/hostname"] = "socrat-1"
        return result
    # Reverse only the verified warm-S3 shipper delta (2948f0e2).
    shipper = spec["thanos"]
    assert shipper["objectStorageConfig"] == {
        "name": "thanos-warm-shipper",
        "key": "objstore.yml",
    }
    shipper["objectStorageConfig"]["name"] = "thanos-objstore-raw"
    assert shipper["volumeMounts"] == [
        {"mountPath": "/trust", "name": "thanos-warm-ca", "readOnly": True}
    ]
    shipper["volumeMounts"] = [
        {"mountPath": "/var/lib/socrat-thanos", "name": "thanos-data"}
    ]
    assert spec["volumes"][0] == {
        "name": "thanos-warm-ca",
        "secret": {
            "secretName": "thanos-warm-api-tls",
            "items": [{"key": "ca.crt", "path": "ca.crt"}],
        },
    }
    spec["volumes"][0] = {
        "name": "thanos-data",
        "hostPath": {"path": "/var/lib/socrat-thanos", "type": "Directory"},
    }
    source = yaml.safe_load((ROOT / "charts/prometheus/values.yaml").read_text())[
        "kube-prometheus-stack"
    ]["prometheus"]["prometheusSpec"]
    assert spec["containers"] == source["containers"], (
        "OTel overrides differ from owning inputs"
    )
    collector, probes = spec["containers"]
    assert collector["name"] == "otel-cluster"
    assert collector["args"] == [
        "--config=/etc/otel/config/collector.yaml",
        "--config=/etc/otel/software-updates/collector.yaml",
    ]
    assert (
        collector["image"]
        == "docker.io/otel/opentelemetry-collector-contrib@sha256:ac0bb9cdc844b55d2fd2655d03e596243787d6a8c52dd408b1dc96dd1bd372ee"
    )
    assert collector["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "runAsGroup": 2000,
        "runAsNonRoot": True,
        "runAsUser": 1000,
    }
    assert collector["ports"] == [
        {
            "containerPort": 4317,
            "hostIP": "10.250.0.1",
            "hostPort": 4317,
            "name": "otel-grpc",
            "protocol": "TCP",
        }
    ]
    assert collector["volumeMounts"] == [
        {"mountPath": "/etc/otel/config", "name": "otel-config", "readOnly": True},
        {"mountPath": "/etc/otel/tls", "name": "otel-tls", "readOnly": True},
        {
            "mountPath": "/etc/otel/source-auth",
            "name": "otel-source-auth",
            "readOnly": True,
        },
        {
            "mountPath": "/etc/prometheus/certs",
            "name": "otel-source-tls",
            "readOnly": True,
        },
        {
            "mountPath": "/var/lib/otel-data",
            "name": "prometheus-kube-prometheus-stack-prometheus-db",
            "subPath": "prometheus-db",
        },
        {
            "name": "software-update-otel",
            "mountPath": "/etc/otel/software-updates",
            "readOnly": True,
        },
    ], "OTel mount authority changed"
    assert probes == {
        "name": "prometheus",
        **{
            name: {
                "exec": {
                    "command": [
                        "/bin/promtool",
                        "check",
                        kind,
                        "--url=http://127.0.0.1:9090",
                    ]
                }
            }
            for name, kind in [
                ("livenessProbe", "healthy"),
                ("readinessProbe", "ready"),
                ("startupProbe", "ready"),
            ]
        },
    }
    assert spec.pop("podMetadata") == {
        "annotations": {
            "homelab.alchemmist.xyz/software-update-scrape-version": "2",
            "homelab.alchemmist.xyz/otel-config-sha256": "db9921b7fe480086f1378726a72c2159cababf78c4cc45eb9ad8e2f212698067",
        }
    }
    spec.pop("containers")
    extension = {
        "name": "software-update-otel",
        "configMap": {"name": "software-update-otel"},
    }
    assert spec["volumes"].count(extension) == 1
    spec["volumes"].remove(extension)
    return cast("dict[str, object]", result)


def test_disjoint_complete_payload_identical_handoff() -> None:
    """Test behavior for test_disjoint_complete_payload_identical_handoff."""
    fixture = json.loads(
        (ROOT / "tests/fixtures/prometheus-service-handoff.json").read_text()
    )
    actual = {}
    all_owners = {}
    for name in COMPONENTS:
        for d in render(name):
            k = key(d)
            assert k not in all_owners, "Duplicate owner: " + k
            all_owners[k] = name
            if (
                k
                == "PrometheusRule/cattle-monitoring-system/kube-prometheus-stack-node-saturation"
            ):
                assert name == "node-exporter"
                (group,) = d["spec"]["groups"]
                (rule,) = group["rules"]
                assert rule["alert"] == "NodeSystemSaturation" and rule["for"] == "15m"
                special, normal = rule["expr"].split("\nor\n")
                assert 'node="socrat-4"' in special and special.endswith("> 6)")
                assert 'node!="socrat-4"' in normal and normal.endswith("> 2)")
                continue
            if k == "ConfigMap/cattle-monitoring-system/software-update-otel":
                assert name == "prometheus"
                software_update_extension(d)
                continue
            if (
                k
                == "PrometheusRule/cattle-monitoring-system/kube-prometheus-stack-homelab-job-failures"
            ):
                assert name == "prometheus"
                (group,) = d["spec"]["groups"]
                assert [r["alert"] for r in group["rules"]] == [
                    "KubeJobFailed",
                    "SocratPrAgentWebhookRedeliveryFailed",
                ]
                # Pin the reviewed additive rule without refreshing the historical fixture.
                payload = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
                assert (
                    hashlib.sha256(payload).hexdigest()
                    == "71e5746199c421a83062d81345ec0c79982c53afb68f68b56e1b22d94db1e1c5"
                )
                continue
            actual[k] = {
                "owner": name,
                "sha256": hashlib.sha256(
                    json.dumps(
                        migration_payload(d), sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
            }
    assert set(all_owners) == set(fixture) | {
        "PrometheusRule/cattle-monitoring-system/kube-prometheus-stack-node-saturation",
        "ConfigMap/cattle-monitoring-system/software-update-otel",
        "PrometheusRule/cattle-monitoring-system/kube-prometheus-stack-homelab-job-failures",
    }
    assert len(actual) == 77
    assert actual == fixture


def test_kube_state_metrics_does_not_collect_or_watch_secrets() -> None:
    """Secret objects are outside KSM's metrics contract and RBAC authority."""
    documents = render("kube-state-metrics")
    (role,) = [d for d in documents if d["kind"] == "ClusterRole"]
    assert all("secrets" not in rule.get("resources", []) for rule in role["rules"])
    (deployment,) = [d for d in documents if d["kind"] == "Deployment"]
    (container,) = deployment["spec"]["template"]["spec"]["containers"]
    (resources,) = [
        arg.removeprefix("--resources=")
        for arg in container["args"]
        if arg.startswith("--resources=")
    ]
    assert "secrets" not in resources.split(",")


def test_each_application_has_only_its_own_runtime() -> None:
    """Test behavior for test_each_application_has_only_its_own_runtime."""
    runtime = {
        "Prometheus": "prometheus",
        "Alertmanager": "alertmanager",
        "DaemonSet": "node-exporter",
    }
    for name in COMPONENTS:
        docs = render(name)
        kinds = {d["kind"] for d in docs}
        for kind, owner in runtime.items():
            assert (kind in kinds) == (name == owner)
        deps = [d for d in docs if d["kind"] == "Deployment"]
        assert len(deps) == int(name in ("prometheus-operator", "kube-state-metrics"))
        assert ("CustomResourceDefinition" in kinds) == (name == "prometheus-operator")
        if name != "prometheus-operator":
            assert not kinds & {
                "MutatingWebhookConfiguration",
                "ValidatingWebhookConfiguration",
            }


def test_offline_source_is_immutable_shared_code_not_shared_ownership() -> None:
    """Test behavior for test_offline_source_is_immutable_shared_code_not_shared_ownership."""
    archive = ROOT / "charts/_vendor/kube-prometheus-stack-92.10.0.tgz"
    expected = (archive.with_suffix(".sha256")).read_text().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    for name in COMPONENTS:
        chart = ROOT / "charts" / name
        dep = yaml.safe_load((chart / "Chart.yaml").read_text())["dependencies"]
        assert dep == [
            {
                "name": "kube-prometheus-stack",
                "version": "92.10.0",
                "repository": "https://prometheus-community.github.io/helm-charts",
            }
        ]
        link = chart / "charts/kube-prometheus-stack-92.10.0.tgz"
        assert link.is_symlink() and link.resolve() == archive.resolve()
        app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{name}.yaml").read_text())
        assert app["spec"]["project"] == "default"
        assert app["spec"]["source"]["path"] == "charts/" + name
        assert app["spec"]["source"]["helm"] == {
            "releaseName": "kube-prometheus-stack",
            "parameters": [],
            "valueFiles": ["alert-graphs.values.yaml"]
            + (
                ["../../deploy/storage/alertmanager-nfs/cutover.values.yaml"]
                if name == "alertmanager"
                else []
            ),
        }
        assert app["spec"]["syncPolicy"]["automated"] == {
            "prune": False,
            "selfHeal": True,
        }


def test_aggregate_application_and_values_are_gone() -> None:
    """Test behavior for test_aggregate_application_and_values_are_gone."""
    assert not (ROOT / "deploy/argocd/apps/prometheus-stack.yaml").exists()
    assert not (ROOT / "deploy/platform/prometheus-stack").exists()


@pytest.mark.parametrize(
    "violation",
    ["scrape-target", "second-owner", "otel-image", "otel-mount", "probe", "service"],
)
def test_current_extension_projection_rejects_mutations(violation: str) -> None:
    """The historical comparison stays strict after validating each new input."""
    test_disjoint_complete_payload_identical_handoff()
    graphs = {name: copy.deepcopy(render(name)) for name in COMPONENTS}
    docs = graphs["prometheus"]
    config = next(
        d
        for d in docs
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "software-update-otel"
    )
    prom = next(d for d in docs if d["kind"] == "Prometheus")
    if violation == "scrape-target":
        config["data"]["collector.yaml"] = config["data"]["collector.yaml"].replace(
            "monitoring-update-watch.cattle-monitoring-system.svc.cluster.local:8080",
            "unreviewed:8080",
        )
    elif violation == "second-owner":
        graphs["alertmanager"].append(copy.deepcopy(config))
    elif violation == "otel-image":
        prom["spec"]["containers"][0]["image"] = "unreviewed:latest"
    elif violation == "otel-mount":
        prom["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] = False
    elif violation == "probe":
        prom["spec"]["containers"][1]["readinessProbe"]["exec"]["command"][-1] = (
            "--url=http://unreviewed:9090"
        )
    else:
        next(d for d in docs if d["kind"] == "Service")["spec"]["type"] = "NodePort"
    with patch(
        "tests.test_prometheus_component_ownership.render",
        side_effect=lambda name: graphs[name],
    ):
        with pytest.raises(AssertionError):
            test_disjoint_complete_payload_identical_handoff()
