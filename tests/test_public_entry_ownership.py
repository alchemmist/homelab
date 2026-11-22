"""Migration contracts: exact payload preservation and one owner per resource."""

import copy
import hashlib
import json
import subprocess
import unittest
from typing import NotRequired, TypedDict
from unittest.mock import patch

import pytest
import yaml

from tests.public_entry_contract import CHARTS, ROOT, assert_status_upstream, render

PUBLIC_HANDOFF = "c6121e1975eb6218804a9be43d7c2a8e99584838"


# Functional syntax keeps the dotted YAML annotation key as a valid identifier.
_Annotations = TypedDict("_Annotations", {"checksum/config": str})


class _PodMetadata(TypedDict):
    """Deployment pod template metadata carrying the checksum annotation."""

    annotations: NotRequired[_Annotations]


class _PodTemplate(TypedDict):
    """Pod template block of a Grafana proxy Deployment."""

    metadata: _PodMetadata


class _DeploymentSpec(TypedDict):
    """Deployment spec holding the pod template."""

    template: _PodTemplate


class _ResourceMetadata(TypedDict):
    """Identity and annotations on the transferred resource itself."""

    name: str
    namespace: str
    annotations: NotRequired[dict[str, str]]


class _HandoffResource(TypedDict):
    """Migrated resource shape surfaced by the application render."""

    kind: str
    metadata: _ResourceMetadata
    data: NotRequired[dict[str, str]]
    spec: NotRequired[_DeploymentSpec]


def _blob_id(data: bytes) -> str:
    """Calculate the local historical blob identity; do not write or fetch Git objects."""
    return subprocess.check_output(["git", "hash-object", "--stdin"], input=data).decode().strip()


def _project_field(
    document: object, path: tuple[str | int, ...], current: str, original: str
) -> None:
    """Only project the approved value at its exact location; all neighbors stay hashed."""
    for key in path[:-1]:
        if isinstance(key, int):
            assert isinstance(document, list)
            document = document[key]
        else:
            assert isinstance(document, dict)
            document = document[key]
    assert isinstance(document, dict)
    assert document[path[-1]] == current, "Live status proxy boundary differs from its owner"
    document[path[-1]] = original


def _status_handoff(resource: _HandoffResource) -> _HandoffResource:
    """Project only the Gatus compatibility fields that changed in the Kuma retirement."""
    result = copy.deepcopy(resource)
    identity = (resource["kind"], resource["metadata"]["name"])
    if identity == ("Ingress", "kuma-admin-browser"):
        _project_field(
            result,
            ("spec", "rules", 0, "http", "paths", 0, "backend", "service", "name"),
            "public-web-kuma-proxy",
            "uptime-kuma",
        )
    elif identity in {
        ("ConfigMap", "public-web-kuma-policy"),
        ("Deployment", "public-web-kuma-proxy"),
    }:
        current = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_bytes()
        assert_status_upstream(current.decode())
        original = (
            ROOT / "tests/fixtures/public-entry-handoff-inputs/kuma-policy.conf.txt"
        ).read_bytes()
        assert _blob_id(original) == "40a9cac2fe30cf52ad89785f940c73cc49f5655c"
        if resource["kind"] == "ConfigMap":
            _project_field(result, ("data", "nginx.conf"), current.decode(), original.decode())
        else:
            _project_field(
                result,
                ("spec", "template", "metadata", "annotations", "checksum/config"),
                hashlib.sha256(current).hexdigest(),
                hashlib.sha256(original).hexdigest(),
            )
            _project_field(
                result,
                (
                    "spec",
                    "template",
                    "spec",
                    "containers",
                    0,
                    "readinessProbe",
                    "httpGet",
                    "path",
                ),
                "/api/v1/config",
                "/api/status-page/socrat",
            )
    return result


def migration_payload(resource: _HandoffResource) -> _HandoffResource:
    """Keep immutable handoff hashes; supply later source payloads independently.

    Validate the Rancher recovery wave, Gatus transition and Grafana inputs before
    projecting those fields back to the original reviewed handoff. All other
    fields still participate unchanged in the immutable fixture comparison.
    """
    name = resource["metadata"]["name"]
    if resource["metadata"]["namespace"] == "uptime-kuma":
        return _status_handoff(resource)
    if (resource["kind"], resource["metadata"]["namespace"], name) == (
        "Deployment",
        "cattle-system",
        "public-web-rancher-proxy",
    ):
        # d43c0634: readiness depends on the backend, so both deploy in wave 0.
        wave = "argocd.argoproj.io/sync-wave"
        assert resource["metadata"].get("annotations", {}).get(wave) == "0", (
            "Rancher proxy must reconcile with its backend"
        )
        result = copy.deepcopy(resource)
        result["metadata"]["annotations"][wave] = "-1"
        return result
    if name not in {"public-web-grafana-policy", "public-web-grafana-proxy"}:
        return resource
    base = "deploy/platform/grafana/public-entry/files/"
    current = {
        key: (ROOT / base / key).read_bytes()
        for key in ("grafana-policy.conf", "traffic-light-inset.js")
    }
    # Materialize existing reviewed inputs, not a new current-state baseline.
    # CI must not depend on historical path availability in its checkout.
    original = {
        key: (ROOT / "tests/fixtures/public-entry-handoff-inputs" / (key + ".txt")).read_bytes()
        for key in current
    }
    pins = {
        "grafana-policy.conf": "843f21304c914bf70378b71e8c05172d83bd1f75",
        "traffic-light-inset.js": "27ec9fe426ee10f74d35bc7be55556a53e72e762",
    }
    for key, data in original.items():
        assert _blob_id(data) == pins[key]
    result = copy.deepcopy(resource)
    if resource["kind"] == "ConfigMap":
        native = {
            "nginx.conf": "grafana-policy.conf",
            "traffic-light-inset.js": "traffic-light-inset.js",
        }
        assert resource["data"] == {
            key: current[source].decode().rstrip("\n") + "\n" for key, source in native.items()
        }, "Live Grafana policy payload differs from owner inputs"
        result["data"] = {
            key: original[source].decode().rstrip("\n") + "\n" for key, source in native.items()
        }
    elif resource["kind"] == "Deployment":
        annotations = resource["spec"]["template"]["metadata"]["annotations"]
        assert annotations == {
            "checksum/config": hashlib.sha256(b"".join(current.values())).hexdigest()
        }, "Live Grafana checksum differs from owner inputs"
        result["spec"]["template"]["metadata"]["annotations"] = {
            "checksum/config": hashlib.sha256(b"".join(original.values())).hexdigest()
        }
    return result


class OwnershipTests(unittest.TestCase):
    """Verify transferred payloads match the reviewed pre-migration render."""

    def test_every_transferred_payload_is_identical_to_reviewed_pre_migration_render(
        self,
    ) -> None:
        """Every transferred payload is identical to reviewed pre migration render."""
        fixture = json.loads((ROOT / "tests/fixtures/public-entry-handoff.json").read_text())
        actual = {}
        for owner in CHARTS:
            for resource in render(owner):
                key = "/".join(
                    [
                        resource["kind"],
                        resource["metadata"]["namespace"],
                        resource["metadata"]["name"],
                    ]
                )
                assert key not in actual, "Multiple application owners: " + key
                digest = hashlib.sha256(
                    json.dumps(
                        migration_payload(resource),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                actual[key] = {"owner": owner, "sha256": digest}
        assert actual == fixture

    def test_platform_extensions_belong_to_the_existing_application(self) -> None:
        """Platform extensions belong to the existing application."""
        for owner, chart in CHARTS.items():
            app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{owner}.yaml").read_text())
            assert app["spec"]["project"] == "default"
            sources = app["spec"].get("sources", [app["spec"].get("source", {})])
            assert len([s for s in sources if s.get("path") == chart]) == 1
            assert not app["spec"]["syncPolicy"]["automated"]["prune"]
            assert app["spec"]["syncPolicy"]["automated"]["selfHeal"]

    def test_aggregate_chart_and_application_are_gone(self) -> None:
        """Aggregate chart and application are gone."""
        assert not (ROOT / "charts/public-web-entry").exists()
        assert not (ROOT / "deploy/argocd/apps/public-web-entry.yaml").exists()
        for path in (ROOT / "deploy/argocd/apps").glob("*.yaml"):
            app = yaml.safe_load(path.read_text())
            assert app["metadata"]["name"] != "public-web-entry"
            sources = app["spec"].get("sources", [app["spec"].get("source", {})])
            assert not any(s.get("path") == "charts/public-web-entry" for s in sources)
        litellm = yaml.safe_load((ROOT / "deploy/argocd/apps/litellm.yaml").read_text())
        assert litellm["spec"]["syncPolicy"]["automated"].get("enabled") is not False


@pytest.mark.parametrize("wave", ["-1", "1"])
def test_rancher_projection_rejects_incorrect_wave(wave: str) -> None:
    """Earlier and later proxy scheduling must not be normalized away."""
    deployment = next(d for d in render("rancher") if d["kind"] == "Deployment")
    deployment["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] = wave
    with pytest.raises(AssertionError, match="Rancher proxy must reconcile with its backend"):
        migration_payload(deployment)


@pytest.mark.parametrize("violation", ["payload", "checksum", "token", "image"])
def test_live_grafana_input_projection_rejects_mutations(violation) -> None:
    """A passing baseline is required; normalization must not hide other changes."""
    OwnershipTests().test_every_transferred_payload_is_identical_to_reviewed_pre_migration_render()
    resources = copy.deepcopy(render("grafana"))
    config = next(d for d in resources if d["kind"] == "ConfigMap")
    deployment = next(d for d in resources if d["kind"] == "Deployment")
    if violation == "payload":
        config["data"]["nginx.conf"] += "synthetic drift"
    elif violation == "checksum":
        deployment["spec"]["template"]["metadata"]["annotations"]["checksum/config"] = "wrong"
    elif violation == "token":
        deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] = True
    else:
        deployment["spec"]["template"]["spec"]["containers"][0]["image"] = "unverified:latest"
    original_render = render
    with patch(
        "tests.test_public_entry_ownership.render",
        side_effect=lambda owner: resources if owner == "grafana" else original_render(owner),
    ):
        with pytest.raises(AssertionError):
            OwnershipTests().test_every_transferred_payload_is_identical_to_reviewed_pre_migration_render()
