"""Offline compiler tests, NOT live routing/failure/revocation acceptance."""

import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import ClassVar, TypedDict, override
from unittest.mock import patch

import pytest
import yaml

# Synthetic TEST constants, not discovered or proposed production values.
CLI_BLOCKED_EXIT = 2
STUN_UDP_PORT = 3478
METRICS_FORBIDDEN_PORT = 9090
LOGIN_EXPIRY_SECONDS = 3600
CONFIG_MODE_OWNER_ONLY = 0o600
MISSING_INPUT_KEYS = "unexpected/missing input keys"

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("netbird_pilot", ROOT / "scripts/netbird-pilot.py")
if spec is None or spec.loader is None:
    msg = "Pilot module under test is not loadable"
    raise RuntimeError(msg)
nb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb)

JSONSCHEMA_MODULE = "jsonschema"


def _jsonschema_module() -> ModuleType:
    """Load jsonschema dynamically; the library has no reviewed Python stubs."""
    return importlib.import_module(JSONSCHEMA_MODULE)


class Inputs(TypedDict):
    """Synthetic passing pilot input document shape."""

    schema_version: int
    management_fqdn: str
    management_node: str
    tls_secret_name: str
    ingress_class: str
    stun_node_port: int
    storage_class: str
    overlay_cidr: str
    authentik_issuer: str
    oidc_client_id: str
    login_group: str
    routing_peers: list[dict[str, object]]
    resources: list[dict[str, object]]
    review: dict[str, bool]


def inputs() -> Inputs:
    # Synthetic TEST fixtures only, not discovered or proposed production addresses.
    return {
        "schema_version": 1,
        "management_fqdn": "vpn.test.invalid.test",
        "management_node": "test-node",
        "tls_secret_name": "test-tls",
        "ingress_class": "test-netbird",
        "stun_node_port": 31478,
        "storage_class": "test-storage",
        "overlay_cidr": "100.100.0.0/24",
        "authentik_issuer": "https://auth.test.invalid.test/application/o/pilot/",
        "oidc_client_id": "test-client",
        "login_group": "pilot-login",
        "routing_peers": [
            {
                "name": "router-a",
                "host": "router-a.test.invalid.test",
                "failure_domain": "test-host-a",
                "metric": 100,
            }
        ],
        "resources": [
            {
                "name": "web",
                "kind": "web",
                "address": "192.168.88.10/32",
                "ports": [443],
                "source_group": "pilot-web",
                "dns_name": "web.test.invalid.test",
            },
            {
                "name": "ssh",
                "kind": "ssh",
                "address": "10.251.0.1/32",
                "ports": [2222],
                "source_group": "pilot-ssh",
                "dns_name": None,
            },
        ],
        "review": dict.fromkeys(nb.REVIEWS, True),
    }


class Bindings(TypedDict):
    """Identifier bindings that the pilot compiler already covers upstream."""

    network_id: str
    source_groups: dict[str, str]
    resource_groups: dict[str, str]
    peer_ids: dict[str, str]


def bindings() -> Bindings:
    return {
        "network_id": "network00001",
        "source_groups": {"pilot-web": "source000001", "pilot-ssh": "source000002"},
        "resource_groups": {"web": "resource0001", "ssh": "resource0002"},
        "peer_ids": {"router-a": "peer00000001"},
    }


def snapshot() -> dict[str, list[dict[str, object]]]:
    b = bindings()
    groups: list[dict[str, object]] = []
    for name, value in b["source_groups"].items():
        groups.append({"id": value, "name": name, "issued": "jwt", "peers": [], "resources": []})
    for name, value in b["resource_groups"].items():
        groups.append(
            {
                "id": value,
                "name": "pilot-resource-" + name,
                "issued": "api",
                "peers": [],
                "resources": [],
            }
        )
    return {
        "policies": [],
        "routes": [],
        "networks": [
            {
                "id": b["network_id"],
                "name": "netbird-pilot",
                "routers": [],
                "resources": [],
                "policies": [],
                "routing_peers_count": 0,
            }
        ],
        "groups": groups,
        "peers": [{"id": value, "name": name} for name, value in b["peer_ids"].items()],
    }


class PilotTests(unittest.TestCase):
    """Check pilot inputs fail closed without leaking rendered output."""

    def test_checked_in_inputs_fail_closed_without_output(self) -> None:
        """Checked-in inputs fail closed without output."""
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "rendered"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/netbird-pilot.py"),
                    "render",
                    "--out",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == CLI_BLOCKED_EXIT
            assert "BLOCKED" in result.stderr
            assert not target.exists()

    def test_cli_refuses_render_into_git_worktree(self) -> None:
        """The CLI refuses to render into the git worktree."""
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "inputs.json"
            source.write_text(json.dumps(inputs()))
            target = ROOT / "deploy/argocd/netbird-forbidden-output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/netbird-pilot.py"),
                    "render",
                    "--inputs",
                    str(source),
                    "--out",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == CLI_BLOCKED_EXIT
            assert "outside the Git worktree" in result.stderr
            assert not target.exists()

    def test_required_inputs_and_reviews_fail_closed(self) -> None:
        """Required inputs and reviews fail closed."""
        nb.validate(inputs())
        for key in inputs():
            c = {k: v for k, v in inputs().items() if k != key}
            with (
                self.subTest(key=key),
                pytest.raises(ValueError, match=MISSING_INPUT_KEYS),
            ):
                nb.validate(c)
        for key in nb.REVIEWS:
            document = inputs()
            document["review"][key] = False
            if key == "existing_node_router_mode_reviewed":
                nb.validate(document)
                document["routing_peers"][0]["host"] = "socrat-2"
                with (
                    self.subTest(review=key),
                    pytest.raises(ValueError, match="existing-node router mode"),
                ):
                    nb.validate(document)
                continue
            with (
                self.subTest(review=key),
                pytest.raises(ValueError, match="review gate must explicitly be true"),
            ):
                nb.validate(document)

    def test_no_broad_networks_ports_or_all_to_all(self) -> None:
        """Broad networks, ports or all-to-all rules are rejected."""
        for address, refusal in [
            ("0.0.0.0/0", "RFC1918 IPv4 /32 hosts"),
            ("192.168.0.0/24", "RFC1918 IPv4 /32 hosts"),
            ("10.250.0.0/24", "RFC1918 IPv4 /32 hosts"),
            ("10.42.1.1/32", "pod/service CIDRs are not pilot endpoints"),
            ("10.43.0.1/32", "pod/service CIDRs are not pilot endpoints"),
            ("::/0", "RFC1918 IPv4 /32 hosts"),
        ]:
            c = inputs()
            c["resources"][0]["address"] = address
            with self.subTest(address=address), pytest.raises(ValueError, match=refusal):
                nb.validate(c)
        for field, value, refusal in [
            ("ports", [80, 443], "web pilot permits TLS TCP 443 only"),
            ("source_group", "All", "dedicated source_group required"),
            ("kind", "exit", "only web/ssh resources allowed"),
        ]:
            c = inputs()
            c["resources"][0][field] = value
            with self.subTest(field=field), pytest.raises(ValueError, match=refusal):
                nb.validate(c)
        c = inputs()
        c["resources"][1]["ports"] = [22]
        with pytest.raises(ValueError, match="existing SSH must stay TCP 2222"):
            nb.validate(c)

    def test_mesh_k3s_transport_never_selected_as_overlay(self) -> None:
        """Mesh or k3s transports are never selected as the overlay."""
        for network in [
            "10.250.0.0/24",
            "10.42.0.0/16",
            "10.43.0.0/16",
            "192.168.0.0/24",
            "172.17.0.0/16",
        ]:
            c = inputs()
            c["overlay_cidr"] = network
            with (
                self.subTest(network=network),
                pytest.raises(ValueError, match="overlay overlaps existing transport"),
            ):
                nb.validate(c)

    def test_one_ssh_router_is_not_a_second_ha_peer(self) -> None:
        """A single SSH router is not a second HA peer."""
        empty = inputs()
        empty["routing_peers"] = []
        with pytest.raises(ValueError, match="exactly one SSH routing peer"):
            nb.validate(empty)
        doubled = inputs()
        doubled["routing_peers"].append(
            {
                "name": "router-b",
                "host": "router-b.test.invalid.test",
                "failure_domain": "test-host-b",
                "metric": 200,
            }
        )
        with pytest.raises(ValueError, match="exactly one SSH routing peer"):
            nb.validate(doubled)
        blocked = inputs()
        blocked["review"]["existing_node_router_mode_reviewed"] = False
        blocked["routing_peers"][0]["host"] = "socrat-2"
        with pytest.raises(ValueError, match="existing-node router mode"):
            nb.validate(blocked)
        allowed = inputs()
        allowed["routing_peers"][0]["host"] = "socrat-0"
        allowed["review"]["existing_node_router_mode_reviewed"] = True
        nb.validate(allowed)
        with (
            tempfile.TemporaryDirectory() as directory,
            pytest.raises(ValueError, match="existing-node router artifacts"),
        ):
            nb.render(allowed, Path(directory) / "routers")
        compose = nb.router_compose(allowed, allowed["routing_peers"][0])
        assert set(compose["services"]) == {"routing-peer"}

    def test_internal_manifest_has_no_service_and_isolates_signup(self) -> None:
        """The internal manifest has no Service and isolates signup."""
        cidrs = ["203.0.113.10/32", "10.42.0.1/32"]
        docs = nb.manifests(inputs(), "internal", cidrs)
        assert [doc["kind"] for doc in docs] == [
            "Namespace",
            "PersistentVolumeClaim",
            "Deployment",
            "Deployment",
            "NetworkPolicy",
        ]
        assert {doc["metadata"]["namespace"] for doc in docs if doc["kind"] != "Namespace"} == {
            "netbird-pilot"
        }
        text = yaml.safe_dump_all(docs)
        assert "kind: Service" not in text
        assert "kind: Ingress" not in text
        assert "NodePort" not in text
        assert "nodePort" not in text
        server = next(doc for doc in docs if doc["metadata"]["name"] == "server")
        container = server["spec"]["template"]["spec"]["containers"][0]
        assert container["readinessProbe"]["httpGet"] == {
            "path": "/oauth2/.well-known/openid-configuration",
            "port": 80,
        }
        assert container["livenessProbe"]["tcpSocket"] == {"port": 9000}
        assert "httpGet" not in container["livenessProbe"]
        secret = server["spec"]["template"]["spec"]["volumes"][0]["secret"]
        assert secret["items"] == [{"key": "config.yaml", "path": "config.yaml"}]
        policy = docs[-1]
        assert nb.ingress_allowed(policy, "203.0.113.10", 80)
        assert nb.ingress_allowed(policy, "10.42.0.1", 80)
        assert not nb.ingress_allowed(policy, "10.42.0.20", 80)
        assert not nb.ingress_allowed(policy, "10.43.0.10", 80)
        assert nb.ingress_allowed(policy, "10.42.0.20", 9000)
        assert not nb.ingress_allowed(policy, "10.42.0.20", METRICS_FORBIDDEN_PORT)
        assert not nb.ingress_allowed(policy, "203.0.113.10", STUN_UDP_PORT, "UDP")
        with pytest.raises(ValueError, match="service CIDR is not a port-forward source"):
            nb.manifests(inputs(), "internal", ["10.43.0.1/32"])
        with pytest.raises(ValueError, match="port-forward sources required"):
            nb.manifests(inputs(), "internal", None)

    def test_manifest_pins_runtime_secret_singleton_no_argo(self) -> None:
        """The manifest pins a runtime-secret singleton without Argo CD."""
        docs = nb.manifests(inputs(), "edge")
        assert not any(
            x["kind"] in ["Secret", "Application", "DaemonSet", "IngressRoute"] for x in docs
        )
        deployments = [x for x in docs if x["kind"] == "Deployment"]
        assert sorted(x["metadata"]["name"] for x in deployments) == [
            "dashboard",
            "edge-forwarder",
            "server",
        ]
        for doc in deployments:
            assert doc["spec"]["replicas"] == 1
            assert doc["spec"]["strategy"]["type"] == "Recreate"
            pod = doc["spec"]["template"]["spec"]
            assert not pod["automountServiceAccountToken"]
            assert "hostNetwork" not in pod
            assert re.search(r"@sha256:[a-f0-9]{64}$", pod["containers"][0]["image"])
        text = yaml.safe_dump_all(docs)
        assert "netbird-runtime" in text
        assert "wg-socrat" not in text
        assert "syncPolicy" not in text
        assert "NB_SETUP_PAT" not in text
        assert "client_secret" not in text
        grpc = next(x for x in docs if x["metadata"].get("name") == "netbird-grpc")
        scheme_key = "traefik.ingress.kubernetes.io/service.serversscheme"
        assert scheme_key not in grpc["metadata"]["annotations"]
        grpc_service = next(
            x
            for x in docs
            if x["kind"] == "Service" and x["metadata"]["name"] == "edge-forwarder-grpc"
        )
        assert grpc_service["metadata"]["annotations"][scheme_key] == "h2c"
        assert grpc_service["spec"]["ports"] == [{"name": "h2c", "port": 8082, "targetPort": "h2c"}]
        assert all(
            p["backend"]["service"]["name"] == "edge-forwarder-grpc"
            for p in grpc["spec"]["rules"][0]["http"]["paths"]
        )
        web_service = next(
            x for x in docs if x["kind"] == "Service" and x["metadata"]["name"] == "edge-forwarder"
        )
        assert scheme_key not in web_service["metadata"].get("annotations", {})
        assert [p["path"] for p in grpc["spec"]["rules"][0]["http"]["paths"]] == [
            "/management.ManagementService/",
            "/signalexchange.SignalExchange/",
        ]
        http = next(x for x in docs if x["metadata"].get("name") == "netbird-http")
        assert "serversscheme" not in http["metadata"]["annotations"]
        config = yaml.safe_load(
            next(x for x in docs if x["kind"] == "ConfigMap")["data"]["dynamic.yaml"]
        )
        routers = config["http"]["routers"]
        assert routers["grpc-management"]["entryPoints"] == ["h2c"]
        assert routers["websocket-management"]["entryPoints"] == ["web"]
        assert routers["relay"]["entryPoints"] == ["web"]
        assert "/api/setup" in routers["deny-setup"]["rule"]
        assert "/oauth2/" in text
        stun = next(x for x in docs if x["metadata"]["name"] == "stun")
        assert stun["spec"]["ports"][0]["protocol"] == "UDP"
        assert stun["spec"]["ports"][0]["port"] == STUN_UDP_PORT
        assert all(
            port.get("port") != METRICS_FORBIDDEN_PORT
            for doc in docs
            if doc["kind"] == "Service"
            for port in doc["spec"]["ports"]
        )
        assert [
            doc["metadata"].get("namespace")
            for doc in docs
            if "netbird-runtime" in yaml.safe_dump(doc)
        ] == ["netbird-pilot"]

    def test_router_runtime_key_file_and_separate_interface(self) -> None:
        """The router uses a runtime key file and a separate interface."""
        c = inputs()
        compose = nb.router_compose(c, c["routing_peers"][0])
        peer = compose["services"]["routing-peer"]
        assert re.search(r"@sha256:[a-f0-9]{64}$", peer["image"])
        assert peer["environment"]["NB_SETUP_KEY_FILE"] == "/run/secrets/setup_key"
        assert "NB_SETUP_KEY" not in peer["environment"]
        assert peer["environment"]["NB_ALLOW_SERVER_SSH"] == "false"
        assert peer["environment"]["NB_INTERFACE_NAME"] == "nb-pilot0"
        assert peer["environment"]["NB_HOSTNAME"] == "router-a"
        assert "hostname" not in peer  # host network cannot request a new container hostname
        assert "privileged" not in peer

    def test_policy_compiler_defaults_deny_specific_tcp_only(self) -> None:
        """The policy compiler defaults to deny with specific TCP-only ports."""
        requests = nb.access_requests(inputs(), bindings(), snapshot())
        routers = [x for x in requests if x["path"].endswith("/routers")]
        assert len(routers) == 1
        assert [x["body"]["metric"] for x in routers] == [100]
        assert all(x["body"]["masquerade"] for x in routers)
        policies = [x["body"] for x in requests if x["path"] == "/api/policies"]
        for policy in policies:
            rule = policy["rules"][0]
            assert rule["protocol"] == "tcp"
            assert not rule["bidirectional"]
            assert len(rule["sources"]) == 1
            assert len(rule["destinations"]) == 1
            assert rule["ports"] in [["443"], ["2222"]]
        assert not any("/routes" in x["path"] for x in requests)

    def test_default_policy_legacy_route_shared_groups_abort_compilation(self) -> None:
        """Default policies, legacy routes or shared groups abort compilation."""
        for key in ["policies", "routes"]:
            s = snapshot()
            s[key] = [{"id": "default"}]
            with (
                self.subTest(key=key),
                pytest.raises(ValueError, match="remove DEFAULT/other policies"),
            ):
                nb.access_requests(inputs(), bindings(), s)
        for field, value, refusal in [
            ("name", "All", "group ID/name mismatch"),
            ("peers", ["peer123"], "destination groups must be complete"),
            ("resources", ["other-resource"], "destination groups must be complete"),
        ]:
            s = snapshot()
            s["groups"][2][field] = value
            with self.subTest(field=field), pytest.raises(ValueError, match=refusal):
                nb.access_requests(inputs(), bindings(), s)
        s = snapshot()
        s["groups"][0]["issued"] = "api"
        with pytest.raises(ValueError, match="source groups must originate from JWT"):
            nb.access_requests(inputs(), bindings(), s)
        b = bindings()
        b["peer_ids"]["router-b"] = b["peer_ids"]["router-a"]
        with pytest.raises(ValueError, match="exact one SSH routing peer ID binding"):
            nb.access_requests(inputs(), b, snapshot())

    def test_network_current_schema_empty_required_no_partial_replay(self) -> None:
        """A network missing required current fields allows no partial replay."""
        broken_values: list[object] = [None, "missing", False, {}, "", ["existing-id"], 1]
        for field in ["routers", "resources", "policies", "routing_peers_count"]:
            for value in broken_values:
                s = snapshot()
                if value == "missing":
                    s["networks"][0].pop(field)
                else:
                    s["networks"][0][field] = value
                with (
                    self.subTest(field=field, value=value),
                    pytest.raises(ValueError, match="complete current API"),
                ):
                    nb.access_requests(inputs(), bindings(), s)

    def test_destination_group_propagation_and_incomplete_responses_refused(
        self,
    ) -> None:
        """Destination group propagation and incomplete responses are refused."""
        assert nb.account_settings(inputs())["groups_propagation_enabled"]
        malformed_cases: list[tuple[str, list[object]]] = [
            ("issued", ["missing", None, "jwt", "integration", ""]),
            ("peers", ["missing", None, {}, ["propagated-user-peer"]]),
            ("resources", ["missing", None, {}, ["previous-resource"]]),
        ]
        for field, values in malformed_cases:
            for value in values:
                s = snapshot()
                if value == "missing":
                    s["groups"][2].pop(field)
                else:
                    s["groups"][2][field] = value
                with (
                    self.subTest(field=field, value=value),
                    pytest.raises(ValueError, match="destination groups must be complete"),
                ):
                    nb.access_requests(inputs(), bindings(), s)
        # A second JWT group with the destination name is unsafe even if the bound ID is API-issued.
        s = snapshot()
        s["groups"].append({**s["groups"][2], "id": "duplicate0001", "issued": "jwt"})
        with pytest.raises(ValueError, match="group ID/name mismatch"):
            nb.access_requests(inputs(), bindings(), s)

    def test_settings_group_propagation_expiry_expose_and_ipv6(self) -> None:
        """Settings cover propagation, expiry, exposure and IPv6."""
        s = nb.account_settings(inputs())
        assert s["jwt_groups_enabled"]
        assert s["groups_propagation_enabled"]
        assert s["jwt_allow_groups"] == ["pilot-login"]
        assert s["peer_login_expiration"] == LOGIN_EXPIRY_SECONDS
        assert not s["peer_expose_enabled"]
        assert s["ipv6_enabled_groups"] == []

    def test_render_reproducible_and_never_overwrites(self) -> None:
        """Rendering is reproducible and never overwrites."""
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            nb.render(inputs(), a)
            nb.render(inputs(), b)
            assert {p.name: p.read_bytes() for p in a.iterdir()} == {
                p.name: p.read_bytes() for p in b.iterdir()
            }
            with pytest.raises(FileExistsError):
                nb.render(inputs(), a)

    def test_runtime_config_secrets_not_printed_and_mode_0600(self) -> None:
        """Runtime config never prints secrets and is mode 0600."""
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "inputs.json", Path(d) / "config.yaml"
            source.write_text(json.dumps(inputs()))
            env = {
                **os.environ,
                "NB_RELAY_SECRET": "test-secret-" * 4,
                "NB_COOKIE_KEY": base64.b64encode(b"a" * 32).decode(),
                "NB_STORE_KEY": base64.b64encode(b"b" * 32).decode(),
            }
            command = [
                sys.executable,
                str(ROOT / "scripts/netbird-pilot.py"),
                "runtime-config",
                "--inputs",
                str(source),
                "--out",
                str(target),
            ]
            missing = subprocess.run(
                command,
                env={k: v for k, v in env.items() if not k.startswith("NB_")},
                capture_output=True,
                text=True,
                check=False,
            )
            assert missing.returncode == CLI_BLOCKED_EXIT
            assert not target.exists()
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            assert result.returncode == 0, result.stderr
            assert target.stat().st_mode & 0o777 == CONFIG_MODE_OWNER_ONLY
            for key in ["NB_RELAY_SECRET", "NB_COOKIE_KEY", "NB_STORE_KEY"]:
                assert env[key] not in result.stdout + result.stderr
            assert yaml.safe_load(target.read_text())["server"]["store"]["engine"] == "sqlite"
            target.unlink()
            target.symlink_to(source)
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            assert result.returncode == CLI_BLOCKED_EXIT
            assert json.loads(source.read_text()) == inputs()


class UpstreamContractTests(unittest.TestCase):
    """Optional contract checks against the pinned upstream schema."""

    @unittest.skipUnless(
        os.environ.get("NETBIRD_OPENAPI_FILE"),
        "optional pinned upstream schema not supplied",
    )
    def test_generated_requests_against_official_v082_openapi(self) -> None:
        """Generated requests validate against the official v0.82 OpenAPI."""
        jsonschema = _jsonschema_module()

        path = Path(os.environ["NETBIRD_OPENAPI_FILE"])
        lock = json.loads((ROOT / "deploy/netbird/upstream.lock.json").read_text())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == lock["sources"]["openapi"]["sha256"]
        schemas = yaml.safe_load(path.read_text())["components"]["schemas"]

        def check(name: str, body: object) -> None:
            schema = {
                "$ref": "#/components/schemas/" + name,
                "components": {"schemas": schemas},
            }
            jsonschema.Draft4Validator(schema).validate(body)

        for req in nb.access_requests(inputs(), bindings(), snapshot()):
            name = (
                "PolicyCreate"
                if req["path"] == "/api/policies"
                else "NetworkRouterRequest"
                if req["path"].endswith("/routers")
                else "NetworkResourceRequest"
            )
            check(name, req["body"])
        check("AccountSettings", nb.account_settings(inputs()))
        check(
            "IdentityProviderRequest",
            {
                "type": "oidc",
                "name": "Authentik pilot",
                "issuer": inputs()["authentik_issuer"],
                "client_id": inputs()["oidc_client_id"],
                "client_secret": "synthetic-test-secret",
            },
        )


class ProbeTests(unittest.TestCase):
    """Run the NetBird probe module loaded from its pinned location."""

    probes: ClassVar[ModuleType]

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Load the pilot probe module once."""
        spec = importlib.util.spec_from_file_location(
            "netbird_probe", ROOT / "scripts/netbird-pilot-probe.py"
        )
        if spec is None or spec.loader is None:
            msg = "Probe module under test is not loadable"
            raise RuntimeError(msg)
        cls.probes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probes)

    def test_denial_requires_tcp_block_not_merely_tls_failure(self) -> None:
        """Denial requires a TCP block, not merely a TLS failure."""
        with patch.object(
            self.probes,
            "probe",
            return_value={"tcp_connected": True, "tls_verified": False},
        ):
            result = self.probes.run(inputs(), "deny", "revoked")
        assert all(not r["passed"] for r in result)

    def test_allowed_web_requires_tls_and_exact_dns(self) -> None:
        """Allowed web requires TLS and exact DNS resolution."""
        with (
            patch.object(
                self.probes,
                "probe",
                return_value={"tcp_connected": True, "tls_verified": True},
            ),
            patch.object(
                self.probes.socket,
                "getaddrinfo",
                return_value=[(None, None, None, None, ("192.168.88.10", 0))],
            ),
        ):
            result = self.probes.run(inputs(), "allow", "baseline")
        assert all(r["passed"] for r in result)
        with (
            patch.object(
                self.probes,
                "probe",
                return_value={"tcp_connected": True, "tls_verified": True},
            ),
            patch.object(self.probes.socket, "getaddrinfo", side_effect=OSError),
        ):
            result = self.probes.run(inputs(), "allow", "baseline")
        assert not result[0]["passed"]

    def test_negative_uses_direct_ip_even_when_dns_broken(self) -> None:
        """Negative probes use the direct IP even when DNS is broken."""
        with (
            patch.object(
                self.probes,
                "probe",
                return_value={"tcp_connected": False, "tls_verified": False},
            ),
            patch.object(self.probes.socket, "getaddrinfo", side_effect=OSError) as dns,
        ):
            result = self.probes.run(inputs(), "deny", "revoked")
        dns.assert_not_called()
        assert all(r["passed"] for r in result)


if __name__ == "__main__":
    unittest.main()
