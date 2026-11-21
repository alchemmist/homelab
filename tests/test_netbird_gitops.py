"""Tests for the NetBird gitops node sync script."""

import copy
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gitops_nodes", ROOT / "scripts/netbird-gitops-nodes.py"
)
gitops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gitops)


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed YAML value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-documents view of a parsed YAML value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _mapping_path(document: dict[str, object], *keys: str) -> dict[str, object]:
    """Walk nested mappings of a parsed document and return the final mapping."""
    value: object = document
    for key in keys:
        value = _mapping(value)[key]
    return _mapping(value)


def _text(value: object) -> str:
    """Return the assert-verified string view of a parsed YAML value."""
    assert isinstance(value, str)
    return value


class GitOpsTests(unittest.TestCase):
    """Validate the NetBird GitOps values and rendered manifests."""

    def values(self) -> dict[str, object]:
        """Load the netbird deployment values document."""
        result: dict[str, object] = yaml.safe_load(
            (ROOT / "deploy/netbird/values.yaml").read_text()
        )
        return result

    def test_root_discovers_default_project_application_without_new_bootstrap(self) -> None:
        """The Argo CD root discovers the default-project app without new bootstrap."""
        root = yaml.safe_load((ROOT / "deploy/argocd/root.yaml").read_text())
        app = yaml.safe_load((ROOT / "deploy/argocd/apps/netbird.yaml").read_text())
        assert root["spec"]["source"]["path"] == "deploy/argocd/apps"
        assert app["spec"]["project"] == "default"
        assert app["spec"]["source"]["targetRevision"] == "main"
        assert app["spec"]["source"]["path"] == "charts/netbird"
        assert app["spec"]["source"]["helm"]["parameters"] == []
        assert app["spec"]["source"]["helm"]["valueFiles"] == ["../../deploy/netbird/values.yaml"]
        assert app["spec"]["syncPolicy"]["automated"] == {"prune": False, "selfHeal": True}

    def test_real_helm_render_includes_complete_stack_without_secret_values(self) -> None:
        """A real Helm render includes the full stack without secret values."""
        docs = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    [
                        "helm",
                        "template",
                        "netbird",
                        str(ROOT / "charts/netbird"),
                        "-f",
                        str(ROOT / "deploy/netbird/values.yaml"),
                    ],
                    text=True,
                )
            )
        )
        assert len(docs) == len(_documents(self.values()["resources"]))
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        assert len(deployments) == 6 + len(_mapping(self.values()["nodes"]))
        names = {d["metadata"]["name"] for d in deployments}
        assert {"dashboard", "server", "stun", "netbird-edge-forwarder", "netbird-relay-home", "netbird-relay-vps"} <= names
        assert not any(d["kind"] in ["Secret", "Job", "ApplicationSet", "AppProject"] for d in docs)
        for d in docs:
            if d["kind"] in ["Namespace", "PersistentVolumeClaim"]:
                assert d["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"
            if d["kind"] != "Deployment":
                continue
            for c in d["spec"]["template"]["spec"]["containers"]:
                assert "@sha256:" in c["image"]
                for env in c.get("env", []):
                    assert env["name"] != "NB_SETUP_KEY"
                    if any(v in env["name"] for v in ["SECRET", "TOKEN", "PASSWORD"]):
                        assert "value" not in env
        dashboard = next(d for d in deployments if d["metadata"]["name"] == "dashboard")
        image = _mapping(self.values()["image"])
        assert dashboard["spec"]["template"]["spec"]["containers"][0]["image"] == _text(image["repository"]) + "@" + _text(image["digest"])

    def test_home_relay_admits_exact_vps_flannel_source_without_weakening_health(self) -> None:
        """The home relay admits exactly the VPS flannel source with health intact."""
        resources = _documents(self.values()["resources"])
        policy = next(
            r
            for r in resources
            if r["kind"] == "NetworkPolicy"
            and _mapping(r["metadata"])["name"] == "netbird-relay-home"
        )
        rule = _documents(_mapping(policy["spec"])["ingress"])[0]
        cidrs = {
            _text(_mapping(_mapping(source)["ipBlock"])["cidr"])
            for source in _documents(_mapping(rule)["from"])
            if "ipBlock" in _mapping(source)
        }
        assert "10.42.0.0/32" in cidrs
        assert all(cidr.endswith("/32") for cidr in cidrs)
        assert _mapping(rule)["ports"] == [{"port": 33080, "protocol": "TCP"}]
        deployment = next(
            r
            for r in resources
            if r["kind"] == "Deployment" and _mapping(r["metadata"])["name"] == "netbird-relay-home"
        )
        container = _documents(
            _mapping_path(deployment, "spec", "template", "spec")["containers"]
        )[0]
        assert _text(_mapping(_mapping(_mapping(container)["readinessProbe"])["httpGet"])["path"]) == "/health"
        assert _mapping(_mapping(_mapping(container)["readinessProbe"])["httpGet"])["port"] == 9000
        env = {
            _text(_mapping(e)["name"]): e
            for e in _documents(_mapping(container)["env"])
        }
        assert "secretKeyRef" in _mapping(_mapping(env["NB_AUTH_SECRET"])["valueFrom"])
        assert _mapping(env["NB_EXPOSED_ADDRESS"])["value"] == "rels://netbird.socrat.alchemmist.xyz:443"

    def inventory(self, address="10.250.0.9") -> dict[str, object]:
        """Build the inventory payload used by the offline gitops node tests."""
        return {
            "Socrat": {"hosts": ["socrat-4"]},
            "_meta": {
                "hostvars": {
                    "socrat-4": {
                        "wg_socrat_admin_clients": {"owner": {"address": "10.250.0.4"}},
                        "wg_socrat_nodes": {"socrat-4": {"address": address}},
                    }
                }
            },
        }

    def test_inventory_addition_only_generates_offline_git_resources(self) -> None:
        """Inventory additions generate only offline git resources."""
        values = self.values()
        original = copy.deepcopy(_documents(values["resources"]))
        image = "netbirdio/netbird:0.82.0@sha256:" + "a" * 64
        assert gitops.desired(values, self.inventory(), image) == ["socrat-4"]
        assert _documents(values["resources"])[:len(original)] == original
        assert _mapping(values["nodes"])["socrat-4"] == "10.250.0.9"
        assert len(_documents(values["resources"])) == len(original) + 2
        assert gitops.desired(values, self.inventory(), image) == []
        assert gitops.desired(values, {"Socrat": {"hosts": ["socrat-4"]}, "_meta": _mapping(self.inventory())["_meta"]}, image) == []
        with self.assertRaises(ValueError):
            gitops.desired(values, self.inventory("10.250.0.10"), image)
        _documents(values["resources"]).pop()
        with self.assertRaises(ValueError):
            gitops.desired(values, self.inventory(), image)

    def test_controller_has_no_imperative_deployment_escape(self) -> None:
        """The controller has no imperative deployment escape hatch."""
        runtime = object.__new__(gitops.node.Runtime)
        runtime.k = []
        with patch.object(gitops.node.subprocess, "run") as run:
            for operation in ["create", "apply", "replace", "patch", "scale", "run"]:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    runtime.kub([operation, "-f", "-"], {"kind": "Deployment"})
            with self.assertRaises(ValueError):
                runtime.kub(["-n", gitops.node.NS, "rollout", "restart", "deployment/a"])
            with self.assertRaises(ValueError):
                runtime.kub(["delete", "pvc", "anything"])
            run.assert_not_called()

    def test_old_control_plane_cli_cannot_apply(self) -> None:
        """The old control-plane CLI cannot apply."""
        p = subprocess.run(
            ["python3", str(ROOT / "scripts/netbird-deploy.py"), "apply"],
            capture_output=True,
            text=True,
        )
        assert p.returncode != 0
        assert "exclusively managed by root -> netbird" in p.stderr
