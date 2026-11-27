"""Tests for the NetBird node reconcile script."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "nodes", ROOT / "ansible/scripts/netbird-node-reconcile.py"
)
if spec is None or spec.loader is None:
    msg = "Reconcile module under test is not loadable"
    raise RuntimeError(msg)
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)
IMAGE = "netbirdio/netbird:0.82.0@sha256:" + "a" * 64

GET_MISS = object()


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of an untyped fixture value."""
    assert isinstance(value, dict)
    mapping: dict[str, object] = value
    return mapping


def node(host: str) -> dict[str, object]:
    """Build the canonical cluster node object for the given host."""
    result: dict[str, object] = {
        "metadata": {"uid": "node-" + host, "name": host},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    return result


class _ManifestSpecSpec(TypedDict, total=False):
    """Inner pod-spec slice the drift fixtures read from a rendered manifest."""

    containers: list[dict[str, object]]
    volumes: list[dict[str, object]]
    nodeSelector: dict[str, str]
    automountServiceAccountToken: object
    securityContext: dict[str, object]


class _ManifestTemplate(TypedDict, total=False):
    """Pod template slice of a rendered manifest."""

    spec: _ManifestSpecSpec


class _ManifestSpec(TypedDict, total=False):
    """Top spec slice of a rendered manifest."""

    template: _ManifestTemplate


class _Manifest(TypedDict, total=False):
    """Manifest shape the runtime fake stores and mutates in place."""

    metadata: dict[str, object]
    spec: _ManifestSpec


class _FakeBody(Protocol):
    """Attribute contract shared by the typed Fake override functions."""

    apply: bool
    config: dict[str, object]
    state: dict[str, object]
    changed: bool
    writes: list[tuple[str, str, object]]
    cluster_node: object
    peer: dict[str, object]
    group: dict[str, object]
    admin: dict[str, object]
    resources: list[dict[str, object]]
    policies: list[dict[str, object]]
    pvc: _Manifest
    dep: _Manifest
    existing: bool
    enrolled: bool
    fail_restart: bool


def _policy_rules(policy: dict[str, object]) -> list[dict[str, object]]:
    """Return the assert-verified rule rows of one policy fixture row."""
    rules = policy["rules"]
    assert isinstance(rules, list)
    result: list[dict[str, object]] = []
    for rule in rules:
        assert isinstance(rule, dict)
        result.append(rule)
    return result


def _rule_sources(rule: dict[str, object]) -> list[object]:
    """Return the assert-verified source rows of one policy rule."""
    sources = rule["sources"]
    assert isinstance(sources, list)
    return sources


def _first_container(manifest: object) -> dict[str, object]:
    """Return the assert-verified sole container mapping of a manifest."""
    spec = _mapping(_mapping(_mapping(_mapping(manifest)["spec"])["template"])["spec"])
    containers = spec["containers"]
    assert isinstance(containers, list)
    assert len(containers) == 1
    first = containers[0]
    assert isinstance(first, dict)
    return first


def _container_env(manifest: object) -> list[dict[str, object]]:
    """Return the assert-verified env rows of a manifest's sole container."""
    env = _first_container(manifest)["env"]
    assert isinstance(env, list)
    rows: list[dict[str, object]] = []
    for entry in env:
        assert isinstance(entry, dict)
        rows.append(entry)
    return rows


def _fake_init(self: _FakeBody, *, apply: bool = True, existing: bool = True) -> None:
    self.apply = apply
    self.config = n.validate_config(
        {
            "image": IMAGE,
            "reserved_addresses": [
                "10.250.0.4",
                "10.250.0.6",
                "10.250.0.7",
                "10.250.0.8",
            ],
            "nodes": {"socrat-4": "10.250.0.9"},
        }
    )
    self.state = {"nodes": {}}
    self.changed = False
    self.writes = []
    self.cluster_node = node("socrat-4")
    self.peer = {
        "id": "peer4",
        "ip": "100.100.1.4",
        "hostname": "socrat-4",
        "name": "machine-socrat-4",
        "user_id": "",
        "connected": True,
        "approval_required": False,
        "login_expired": False,
    }
    self.group = {"id": "nodes", "issued": "api", "name": n.DEST, "peers": []}
    self.admin = {"id": "jwt", "issued": "jwt", "name": n.ADMIN}
    self.resources = []
    self.policies = [
        {
            "enabled": True,
            "name": "admin-input",
            "rules": [
                {
                    "enabled": True,
                    "action": "accept",
                    "protocol": "all",
                    "bidirectional": False,
                    "sources": [{"id": "jwt"}],
                    "destinations": [{"id": "nodes"}],
                }
            ],
        }
    ]
    self.pvc, self.dep = n.manifests("socrat-4", IMAGE)
    self.pvc["metadata"]["uid"] = "pvc4"
    self.dep["metadata"]["uid"] = "dep4"
    for obj in [self.dep, self.pvc]:
        obj["metadata"]["labels"] = {"app.kubernetes.io/instance": "netbird"}
    self.existing = existing
    self.enrolled = existing
    self.fail_restart = False


def _fake_save(self: _FakeBody) -> None:
    """Accept the runtime state save without writing anything."""


def _fake_get(self: _FakeBody, path: str) -> object:
    """Answer the reconciler's read-only API calls from in-memory fixtures."""
    literal: dict[str, Callable[[], object]] = {
        "groups": lambda: ([self.admin, self.group, {"name": "All", "id": "all", "issued": "api"}]),
        "networks": lambda: [{"id": "net", "name": n.NETWORK}],
        "policies": lambda: copy.deepcopy(self.policies),
        "peers": lambda: [self.peer] if self.enrolled else [],
        "groups/nodes": lambda: copy.deepcopy(self.group),
    }
    handler = literal.get(path)
    if handler is not None:
        return handler()
    if path.endswith("/routers"):
        return [
            {
                "id": "router",
                "peer_groups": ["nodes"],
                "enabled": True,
                "masquerade": True,
                "metric": 80,
            }
        ]
    if path.endswith("/resources"):
        return self.resources
    return GET_MISS


def _fake_api(
    self: _FakeBody, method: str, path: str, body: dict[str, object] | None = None
) -> object:
    """Serve the reconciler's API calls from in-memory fixtures."""
    if method == "GET":
        miss = _fake_get(self, path)
        if miss is not GET_MISS:
            return miss
    self.writes.append((method, path, copy.deepcopy(body)))
    if path == "setup-keys":
        return {"id": "one-use", "key": "fixture-not-a-real-secret"}
    if path == "setup-keys/one-use":
        return {"revoked": True}
    if path == "groups/nodes":
        assert body is not None
        peers = body["peers"]
        assert isinstance(peers, list)
        self.group["peers"] = [{"id": p} for p in peers]
        return self.group
    if path.endswith("/resources"):
        assert body is not None
        result: dict[str, object] = dict(body, id="res", type="host")
        self.resources.append(result)
        return result
    if path == "policies":
        assert body is not None
        payload: dict[str, object] = dict(copy.deepcopy(body), id="policy4")
        _policy_rules(payload)[0]["sources"] = [
            {"id": p} for p in _rule_sources(_policy_rules(body)[0])
        ]
        self.policies.append(payload)
        return payload
    raise AssertionError(path)


def _fake_get_obj(
    self: _FakeBody, kind: str, name: str, ns: str = n.NS, *, optional: bool = False
) -> object:
    """Serve the reconciler's object lookups from in-memory fixtures."""
    del ns, optional  # fixed namespace lookups only; optional secrets always exist
    if kind == "application":
        return {
            "metadata": {"labels": {"app.kubernetes.io/instance": "root"}},
            "spec": {
                "project": "default",
                "source": {
                    "path": "charts/netbird",
                    "targetRevision": "main",
                    "repoURL": "https://github.com/alchemmist/homelab.git",
                },
            },
        }
    if kind == "namespace":
        return {"metadata": {"uid": name}}
    if kind == "node":
        return self.cluster_node
    if kind == "deployment":
        return copy.deepcopy(self.dep) if self.existing else None
    if kind == "pvc":
        return copy.deepcopy(self.pvc) if self.existing else None
    if kind == "secret":
        return {"metadata": {"name": name, "uid": "secret4", "resourceVersion": "1"}}
    raise AssertionError(kind)


def _fake_status(self: _FakeBody, host: str) -> dict[str, object]:
    """Return the fixture daemon status for the given host."""
    del host
    result: dict[str, object] = {"ip": self.peer["ip"], "key": "fixture-public-key"}
    return result


def _fake_restart_without_key(self: _FakeBody, host: str, deployment: object) -> None:
    """Simulate a restart failure when the fixture flag is set."""
    del host, deployment
    if self.fail_restart:
        msg = "simulated restart failure"
        raise ValueError(msg)


def _fake_kub(
    self: _FakeBody,
    args: list[str],
    obj: object = None,
    *,
    optional: bool = False,
    stdin: bytes | None = None,
) -> bytes:
    """Serve the reconciler's kubectl calls from in-memory fixtures."""
    del obj, optional
    if stdin is not None:
        assert args[-4:] == ["netbird", "up", "--setup-key-file", "/dev/stdin"]
        self.enrolled = True
    if args[-3:] == ["netbird", "status", "--json"]:
        return json.dumps(
            {
                "daemonStatus": "Connected" if self.enrolled else "NeedsLogin",
                "netbirdIp": "100.100.1.4" if self.enrolled else "",
            }
        ).encode()
    assert not any(a in args for a in ["create", "apply", "replace", "patch"]), (
        "controller must not deploy workloads"
    )
    if "address" in args:
        return json.dumps([{"addr_info": [{"local": "10.250.0.9"}]}]).encode()
    if args[:2] == ["get", "nodes"]:
        return json.dumps({"items": [self.cluster_node]}).encode()
    return b"{}"


_FAKE_METHODS: dict[str, object] = {
    "__init__": _fake_init,
    "save": _fake_save,
    "api": _fake_api,
    "get": _fake_get_obj,
    "status": _fake_status,
    "restart_without_key": _fake_restart_without_key,
    "kub": _fake_kub,
}

Fake = type("Fake", (n.Runtime,), _FAKE_METHODS)


class ReconcileTest(unittest.TestCase):
    """Check the reconciler's fail-closed and idempotent behaviors."""

    def seed(self) -> dict[str, object]:
        """Build the reviewed node seed state used by the reconcile tests."""
        result: dict[str, object] = {"nodes": {"socrat-4": {"id": "peer4"}}}
        return result

    def test_kernel_only_daemon_has_no_tun_or_interactive_sso(self) -> None:
        """The kernel-only daemon has no TUN or interactive SSO."""
        _pvc, deployment = n.manifests("socrat-5", IMAGE, kernel_only=True)
        spec = deployment["spec"]["template"]["spec"]
        assert spec["containers"][0]["command"] == ["netbird"]
        assert spec["containers"][0]["args"] == ["service", "run"]
        assert [v["name"] for v in spec["volumes"]] == ["state"]
        assert [v["name"] for v in spec["containers"][0]["volumeMounts"]] == ["state"]
        assert "privileged" not in spec["containers"][0]["securityContext"]

    def test_inventory_is_generic_but_not_arbitrary_network_access(self) -> None:
        """The inventory is generic but not arbitrary network access."""
        for values, refusal in [
            ({"socrat-4": "10.250.0.4"}, "node address collides with a human/device WG client"),
            ({"other": "10.250.0.9"}, "invalid inventory node name"),
            ({"socrat-4": "0.0.0.0/0"}, "an IPv4 or IPv6 address"),
            ({"socrat-4": "10.250.0.9/32"}, "an IPv4 or IPv6 address"),
            ({"socrat-4": "10.250.0.255"}, "explicit WG host address required"),
            ({"socrat-4": "10.250.0.9", "socrat-5": "10.250.0.9"}, "duplicate WG addresses"),
        ]:
            with pytest.raises(ValueError, match=refusal):
                n.validate_config(
                    {
                        "image": IMAGE,
                        "reserved_addresses": [
                            "10.250.0.4",
                            "10.250.0.6",
                            "10.250.0.7",
                            "10.250.0.8",
                        ],
                        "nodes": values,
                    }
                )
        with pytest.raises(ValueError, match="pinned client required"):
            n.validate_config({"image": "latest", "nodes": {"socrat-4": "10.250.0.9"}})

    def test_render_has_persistent_identity_and_no_human_or_dns_permissions(
        self,
    ) -> None:
        """Rendered manifests keep identity persistent without human or DNS permissions."""
        _pvc, deploy = n.manifests("socrat-28", IMAGE)
        pod = deploy["spec"]["template"]["spec"]
        env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
        assert "NB_SETUP_KEY" not in env
        assert env["NB_DISABLE_DNS"] == "true"
        assert env["NB_DISABLE_CLIENT_ROUTES"] == "true"
        assert env["NB_DISABLE_SERVER_ROUTES"] == "false"
        assert env["NB_ALLOW_SERVER_SSH"] == "false"
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-28"}
        assert not pod["automountServiceAccountToken"]

    def test_adopt_requires_trusted_exact_peer_not_name(self) -> None:
        """Adoption requires the trusted exact peer, not a name."""
        for seed, refusal in [
            (None, "orphan existing peer"),
            ({"nodes": {"socrat-4": {"id": "wrong"}}}, "trusted migration binding mismatch"),
        ]:
            f = Fake()
            with pytest.raises(ValueError, match=refusal):
                f.reconcile("socrat-4", seed)
            assert f.writes == []

    def test_adopt_and_second_run_are_idempotent(self) -> None:
        """Adoption and the second run are idempotent."""
        f = Fake()
        assert f.reconcile("socrat-4", self.seed())["changed"]
        assert len(f.resources) == 1
        writes = len(f.writes)
        f.changed = False
        assert not f.reconcile("socrat-4")["changed"]
        assert len(f.writes) == writes

    def test_plan_never_enrolls_or_writes(self) -> None:
        """Plan never enrolls or writes."""
        f = Fake(apply=False, existing=False)
        assert f.reconcile("socrat-4")["status"] == "awaiting-argocd-workloads"
        assert f.writes == []

    def test_missing_git_workloads_are_deferred_without_kubernetes_or_api_writes(
        self,
    ) -> None:
        """Missing git workloads defer without Kubernetes or API writes."""
        f = Fake(existing=False)
        assert f.reconcile("socrat-4")["status"] == "awaiting-argocd-workloads"
        assert f.writes == []

    def test_fresh_argocd_agent_plan_has_no_setup_key(self) -> None:
        """A fresh Argo CD agent plan contains no setup key."""
        f = Fake(apply=False)
        f.enrolled = False
        assert f.reconcile("socrat-4")["status"] == "would-enroll-and-authorize"
        assert f.writes == []

    def test_unmanaged_workloads_cannot_be_adopted_by_controller(self) -> None:
        """Unmanaged workloads cannot be adopted by the controller."""
        f = Fake()
        f.dep["metadata"].pop("labels")
        with pytest.raises(ValueError, match="owned by the root-managed netbird Argo"):
            f.reconcile("socrat-4", self.seed())
        assert f.writes == []

    def test_missing_not_ready_node_is_deferred(self) -> None:
        """A missing or unready node is deferred."""
        f = Fake()
        f.cluster_node = None
        assert f.reconcile("socrat-4")["status"] == "deferred-node-not-ready"
        assert f.writes == []

    def test_simulated_new_node_flow_retires_key_and_second_run_no_writes(self) -> None:
        """The new-node flow retires the key and the second run writes nothing."""
        f = Fake()
        f.enrolled = False
        assert f.reconcile("socrat-4")["changed"]
        assert _mapping(f.state["cleanup"])["revoked"] is True
        node_state = _mapping(_mapping(f.state["nodes"])["socrat-4"])
        assert node_state["phase"] == "ready"
        assert not any(e["name"] == "NB_SETUP_KEY" for e in _container_env(f.dep))
        writes = len(f.writes)
        f.changed = False
        assert not f.reconcile("socrat-4")["changed"]
        assert len(f.writes) == writes

    def test_failed_enrollment_revokes_known_key_and_never_auto_reissues(self) -> None:
        """A failed enrollment revokes the known key and never reissues automatically."""
        f = Fake()
        f.enrolled = False
        f.fail_restart = True
        with pytest.raises(ValueError, match="simulated restart failure"):
            f.reconcile("socrat-4")
        assert _mapping(f.state["cleanup"])["revoked"]
        node_state = _mapping(_mapping(f.state["nodes"])["socrat-4"])
        assert node_state["phase"] != "ready"
        writes = len(f.writes)
        with pytest.raises(ValueError, match="never reissue automatically"):
            f.reconcile("socrat-4")
        assert len(f.writes) == writes

    def test_node_uid_pvc_peer_address_and_image_drift_are_not_repaired(self) -> None:
        """Identity drift on node, PVC, peer, address or image is never repaired."""
        for kind, refusal in [
            ("node", "node reinstallation/address change requires explicit retirement"),
            ("pvc", "persistent node/peer identity drift"),
            ("peer", "persistent node/peer identity drift"),
            ("address", "node reinstallation/address change requires explicit retirement"),
            ("image", "agent image/env/security drift"),
            ("key", "persistent node/peer identity drift"),
            ("deleted-volume", "lost identity storage: no re-enrollment"),
        ]:
            f = Fake()
            f.reconcile("socrat-4", self.seed())
            before = len(f.writes)
            if kind in ("node", "pvc", "peer", "address", "key"):
                if kind == "node":
                    _mapping(_mapping(f.cluster_node)["metadata"])["uid"] = "replacement"
                if kind == "pvc":
                    f.pvc["metadata"]["uid"] = "replacement"
                if kind == "peer":
                    f.peer["id"] = "replacement"
                if kind == "address":
                    _mapping(_mapping(f.config)["nodes"])["socrat-4"] = "10.250.0.10"
                if kind == "key":
                    node_state = _mapping(_mapping(f.state["nodes"])["socrat-4"])
                    node_state["public_key"] = "different"
            elif kind == "image":
                _first_container(f.dep)["image"] = "latest"
            else:
                f.existing = False
                f.enrolled = False
            with self.subTest(kind=kind), pytest.raises(ValueError, match=refusal):
                f.reconcile("socrat-4")
            assert len(f.writes) == before

    def test_fake_jwt_broad_acl_or_wrong_router_fail_before_writes(self) -> None:
        """Fake JWTs, broad ACLs or wrong routers fail before writes."""
        for kind, refusal in [
            ("jwt", "real JWT admin source required"),
            ("input", "admin own-node INPUT policy missing or broadened"),
            ("member", "unbound machine-group member"),
        ]:
            f = Fake()
            if kind == "jwt":
                f.admin["issued"] = "api"
            if kind == "input":
                _policy_rules(_mapping(f.policies[0]))[0]["sources"] = [{"id": "All"}]
            if kind == "member":
                f.group["peers"] = [{"id": "human-device"}]
            with pytest.raises(ValueError, match=refusal):
                f.reconcile("socrat-4", self.seed())
            assert f.writes == []

    def test_removed_or_broadened_grants_are_not_resurrected(self) -> None:
        """Removed or broadened grants are never resurrected."""
        for kind, refusal in [
            ("resource", "managed grant removed/replaced"),
            ("policy", "managed grant removed/replaced"),
            ("disabled", "admin resource policy drift"),
            ("broadened", "admin resource policy drift"),
            ("membership", "bound node removed from destination group"),
        ]:
            f = Fake()
            f.reconcile("socrat-4", self.seed())
            before = len(f.writes)
            if kind == "membership":
                f.group["peers"] = []
            if kind == "resource":
                f.resources = []
            if kind == "policy":
                f.policies = f.policies[:1]
            if kind == "disabled":
                _mapping(f.policies[-1])["enabled"] = False
            if kind == "broadened":
                _policy_rules(_mapping(f.policies[-1]))[0]["sources"] = [{"id": "All"}]
            with self.subTest(kind=kind), pytest.raises(ValueError, match=refusal):
                f.reconcile("socrat-4")
            assert len(f.writes) == before

    def test_uncertain_write_remains_blocking(self) -> None:
        """An uncertain write remains blocking."""
        f = Fake()
        f.state["pending"] = {"method": "POST", "path": "policies"}
        with pytest.raises(ValueError, match="uncertain previous write"):
            f.write("POST", "policies", {})
        assert f.writes == []
