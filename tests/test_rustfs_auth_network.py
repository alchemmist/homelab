"""Actual ingress DNAT contract; offline Helm only, no production authentication."""

import pathlib
import subprocess
import unittest
from typing import NotRequired, TypedDict

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Peer(TypedDict):
    """Egress peer by pod or namespace selector."""

    podSelector: NotRequired[dict[str, dict[str, str]]]
    namespaceSelector: NotRequired[dict[str, dict[str, str]]]


class _EgressRule(TypedDict):
    """One egress rule with optional port and peer lists."""

    ports: NotRequired[list[dict[str, object]]]
    to: NotRequired[list[_Peer]]


class _PolicySpec(TypedDict):
    """NetworkPolicy spec fields the DNAT contract reads."""

    egress: list[_EgressRule]


class _NetworkPolicy(TypedDict):
    """Rendered manifest document narrowed for ingress policy checks."""

    kind: str
    metadata: dict[str, object]
    spec: _PolicySpec


def render(enabled) -> dict[tuple[str, str, str], _NetworkPolicy]:
    raw = subprocess.check_output(
        [
            "helm",
            "template",
            "rustfs",
            str(ROOT / "charts/rustfs"),
            "--namespace",
            "rustfs",
            "-f",
            str(ROOT / "charts/rustfs/values-foundation-live.yaml"),
            "--set",
            "authViaTraefik=" + str(enabled).lower(),
        ],
        text=True,
    )
    return {
        (r["kind"], r["metadata"].get("namespace", "rustfs"), r["metadata"]["name"]): r
        for r in yaml.safe_load_all(raw)
        if r
    }


class AuthNetworkTests(unittest.TestCase):
    def test_only_two_policies_change_no_pod_or_stateful_resource(self) -> None:
        before, after = render(False), render(True)
        assert set(before) == set(after)
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {
            ("NetworkPolicy", "rustfs", "rustfs-isolation"),
            ("NetworkPolicy", "identity", "rustfs-gateway-isolation"),
        }

    def test_both_real_https_dnat_hops_are_narrowly_selected(self) -> None:
        for key, obj in render(True).items():
            if key[0] != "NetworkPolicy" or key[2] not in (
                "rustfs-isolation",
                "rustfs-gateway-isolation",
            ):
                continue
            rows = obj["spec"]["egress"]
            peers = [
                r
                for r in rows
                if any(
                    "podSelector" in p
                    and p["podSelector"]["matchLabels"].get("app.kubernetes.io/name") == "traefik"
                    for p in r.get("to", [])
                )
            ]
            assert len(peers) == 1
            assert peers[0]["ports"] == [{"port": 8443, "protocol": "TCP"}]
            lbs = [
                r
                for r in rows
                if any(
                    p.get("podSelector", {})
                    .get("matchLabels", {})
                    .get("svccontroller.k3s.cattle.io/svcname")
                    == "traefik"
                    for p in r.get("to", [])
                )
            ]
            assert len(lbs) == 1
            assert lbs[0]["ports"] == [{"port": 443, "protocol": "TCP"}]
            for row in peers + lbs:
                assert row["to"][0]["namespaceSelector"]["matchLabels"] == {
                    "kubernetes.io/metadata.name": "kube-system"
                }
            assert "0.0.0.0/0" not in str(rows)
