"""Exactly the same 77 resources, split between five single-service Applications."""

from collections.abc import Iterator
from functools import lru_cache
import copy
from typing import Protocol, TypedDict, cast, override
from unittest.mock import patch

import pytest

import hashlib
import json
from pathlib import Path
import subprocess
import yaml

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


class _Tree(Protocol):
    @override
    def __eq__(self, other: object) -> bool: ...

    @override
    def __hash__(self) -> int: ...

    def __getitem__(self, key: str) -> "_Tree": ...

    def __iter__(self) -> Iterator["_Tree"]: ...

    def count(self, value: object) -> int: ...

    def pop(self, key: str) -> "_Tree": ...

    def remove(self, value: object) -> None: ...


class _ResourceMeta(TypedDict, total=False):
    name: str
    namespace: str


class _ConfigMap(TypedDict):
    apiVersion: str
    kind: str
    metadata: _ResourceMeta
    data: dict[str, str]


class _KeyedResource(TypedDict):
    kind: str
    metadata: _ResourceMeta


@lru_cache(maxsize=None)
def render(name: str):
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


def key(d: _KeyedResource):
    return "/".join(
        [
            d["kind"],
            ""
            if d["kind"] in CLUSTER
            else d["metadata"].get("namespace", "cattle-monitoring-system"),
            d["metadata"]["name"],
        ]
    )


def software_update_extension(document: _ConfigMap):
    """Review the one additive receiver without refreshing any handoff hash."""
    collector_yaml = document["data"]["collector.yaml"]
    assert document == {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "software-update-otel", "namespace": "cattle-monitoring-system"},
        "data": {"collector.yaml": collector_yaml},
    }
    assert yaml.safe_load(collector_yaml) == {
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
                        }
                    ]
                }
            }
        },
        "service": {
            "pipelines": {
                "metrics": {"receivers": ["prometheus", "otlp", "prometheus/software_updates"]}
            }
        },
    }, "Software update receiver scope changed"


def migration_payload(document: _Tree):
    """Check declared runtime overrides before comparing the unchanged handoff payload."""
    if document["kind"] != "Prometheus":
        return document
    result = copy.deepcopy(document)
    spec = result["spec"]
    source = yaml.safe_load((ROOT / "charts/prometheus/values.yaml").read_text())[
        "kube-prometheus-stack"
    ]["prometheus"]["prometheusSpec"]
    assert spec["containers"] == source["containers"], "OTel overrides differ from owning inputs"
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
        {"mountPath": "/etc/otel/source-auth", "name": "otel-source-auth", "readOnly": True},
        {"mountPath": "/etc/prometheus/certs", "name": "otel-source-tls", "readOnly": True},
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
                "exec": {"command": ["/bin/promtool", "check", kind, "--url=http://127.0.0.1:9090"]}
            }
            for name, kind in [
                ("livenessProbe", "healthy"),
                ("readinessProbe", "ready"),
                ("startupProbe", "ready"),
            ]
        },
    }
    assert spec.pop("podMetadata") == {
        "annotations": {"homelab.alchemmist.xyz/software-update-scrape-version": "1"}
    }
    spec.pop("containers")
    extension = {"name": "software-update-otel", "configMap": {"name": "software-update-otel"}}
    assert spec["volumes"].count(extension) == 1
    spec["volumes"].remove(extension)
    return result


def test_disjoint_complete_payload_identical_handoff():
    fixture = json.loads((ROOT / "tests/fixtures/prometheus-service-handoff.json").read_text())
    actual = {}
    all_owners = {}
    for name in COMPONENTS:
        for d in render(name):
            k = key(d)
            assert k not in all_owners, "Duplicate owner: " + k
            all_owners[k] = name
            if k == "ConfigMap/cattle-monitoring-system/software-update-otel":
                assert name == "prometheus"
                software_update_extension(d)
                continue
            actual[k] = {
                "owner": name,
                "sha256": hashlib.sha256(
                    json.dumps(migration_payload(d), sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
    assert set(all_owners) == set(fixture) | {
        "ConfigMap/cattle-monitoring-system/software-update-otel"
    }
    assert len(actual) == 77
    assert actual == fixture


def test_each_application_has_only_its_own_runtime():
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
            assert not kinds & {"MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}


def test_offline_source_is_immutable_shared_code_not_shared_ownership():
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
            "valueFiles": ["alert-graphs.values.yaml"],
        }
        assert app["spec"]["syncPolicy"]["automated"] == {"prune": False, "selfHeal": True}


def test_aggregate_application_and_values_are_gone():
    assert not (ROOT / "deploy/argocd/apps/prometheus-stack.yaml").exists()
    assert not (ROOT / "deploy/platform/prometheus-stack").exists()


@pytest.mark.parametrize(
    "violation", ["scrape-target", "second-owner", "otel-image", "otel-mount", "probe", "service"]
)
def test_current_extension_projection_rejects_mutations(violation: str):
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
        "tests.test_prometheus_component_ownership.render", side_effect=lambda name: graphs[name]
    ):
        with pytest.raises(AssertionError):
            test_disjoint_complete_payload_identical_handoff()
