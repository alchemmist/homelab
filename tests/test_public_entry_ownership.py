"""Migration contracts: exact payload preservation and one owner per resource."""

import copy
import subprocess
from typing import NotRequired, TypedDict
from unittest.mock import patch

import pytest

import hashlib
import json
from pathlib import Path
import unittest
import yaml
from tests.public_entry_contract import CHARTS, ROOT, render


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


class _HandoffResource(TypedDict):
    """Migrated resource shape surfaced by the application render."""

    kind: str
    metadata: dict[str, str]
    data: NotRequired[dict[str, str]]
    spec: NotRequired[_DeploymentSpec]


def migration_payload(resource: _HandoffResource) -> _HandoffResource:
    """Keep immutable handoff hashes; supply later source payloads independently.

    Only the two source-owned Grafana text inputs/checksum may differ. Validate
    their entire live rendering before projecting the original reviewed inputs.
    No fixture hashes or resource/ownership/security fields are refreshed.
    """
    name = resource["metadata"]["name"]
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
        # hash-object without -w is local identity calculation, not a write/fetch.
        assert (
            subprocess.check_output(["git", "hash-object", "--stdin"], input=data).decode().strip()
            == pins[key]
        )
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
                        migration_payload(resource), sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                actual[key] = {"owner": owner, "sha256": digest}
        assert actual == fixture

    def test_platform_extensions_belong_to_the_existing_application(self) -> None:
        for owner, chart in CHARTS.items():
            app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{owner}.yaml").read_text())
            assert app["spec"]["project"] == "default"
            sources = app["spec"].get("sources", [app["spec"].get("source", {})])
            assert len([s for s in sources if s.get("path") == chart]) == 1
            assert not app["spec"]["syncPolicy"]["automated"]["prune"]
            assert app["spec"]["syncPolicy"]["automated"]["selfHeal"]

    def test_aggregate_chart_and_application_are_gone(self) -> None:
        assert not (ROOT / "charts/public-web-entry").exists()
        assert not (ROOT / "deploy/argocd/apps/public-web-entry.yaml").exists()
        for path in (ROOT / "deploy/argocd/apps").glob("*.yaml"):
            app = yaml.safe_load(path.read_text())
            assert app["metadata"]["name"] != "public-web-entry"
            sources = app["spec"].get("sources", [app["spec"].get("source", {})])
            assert not any(s.get("path") == "charts/public-web-entry" for s in sources)
        litellm = yaml.safe_load((ROOT / "deploy/argocd/apps/litellm.yaml").read_text())
        assert litellm["spec"]["syncPolicy"]["automated"].get("enabled") is not False


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
