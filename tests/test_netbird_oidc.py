"""Offline contracts for the NetBird Authentik provider. No live IdP writes."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ansible/roles/identity_integrations/files/netbird_oidc.py"
SPEC = importlib.util.spec_from_file_location("netbird_oidc", SOURCE)
oidc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oidc)

TOKEN = "fixture-machine-token"
ISSUER = "https://netbird.socrat.alchemmist.xyz/oauth2"
CALLBACK = ISSUER + "/callback"
OWNER_GROUPS = [
    "03c0ba14-277d-4332-81bc-655d0f1cbbe9",
    "204674ab-2b47-410f-ac1f-57e17705f813",
    "3f2907f6-bb0b-4984-abf0-13f1f8aafbe8",
]
TIM_GROUPS = ["b7af46a6-6208-4a32-bfb1-4e61fd3c88ec"]


def write_json(path, value) -> None:
    """Write the given value as a 0600 permissions JSON document."""
    path.write_text(json.dumps(value, indent=2) + "\n")
    os.chmod(path, 0o600)


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of an untyped runtime value."""
    assert isinstance(value, dict)
    mapping: dict[str, object] = value
    return mapping


def _sequence(value: object) -> list[object]:
    """Return the assert-verified sequence view of an untyped runtime value."""
    assert isinstance(value, list)
    sequence: list[object] = value
    return sequence


def _string(value: object) -> str:
    """Return the assert-verified string view of an untyped runtime value."""
    assert isinstance(value, str)
    return value


class FakeAuthentik(threading.Thread):
    """Threaded fake Authentik server recording OIDC requests."""
    def __init__(self) -> None:
        """Serve the reviewed offline contract fixtures over localhost HTTP."""
        super().__init__(daemon=True)
        self.calls: list[tuple[str, str, str, object]] = []
        self.fail_provider = False
        self.drop_legacy_on_add = False
        self.attach_outpost = False
        self.users = [
            {
                "pk": 5,
                "uuid": "9e33877a-3eaa-4541-98eb-8cdc10088ef6",
                "username": "alchemmist",
                "name": "alchemmist",
                "email": "anton.ingrish@gmail.com",
                "is_active": True,
                "is_superuser": True,
                "type": "internal",
                "groups": list(OWNER_GROUPS),
            },
            {
                "pk": 6,
                "uuid": "6015c85b-82e9-49ce-a4e3-0270c676e26d",
                "username": "antropophag",
                "name": "Tim",
                "email": "antropophag@gmail.com",
                "is_active": True,
                "is_superuser": False,
                "type": "internal",
                "groups": list(TIM_GROUPS),
            },
        ]
        self.groups = [
            {
                "pk": OWNER_GROUPS[0],
                "num_pk": 1,
                "name": "homelab-owner",
                "is_superuser": True,
                "parents": [],
                "children": [],
                "roles": [],
                "users": [5],
                "attributes": {},
            },
            {
                "pk": OWNER_GROUPS[1],
                "num_pk": 2,
                "name": "lms-students",
                "is_superuser": False,
                "parents": [],
                "children": [],
                "roles": [],
                "users": [5],
                "attributes": {},
            },
            {
                "pk": OWNER_GROUPS[2],
                "num_pk": 3,
                "name": "lms-teachers",
                "is_superuser": False,
                "parents": [],
                "children": [],
                "roles": [],
                "users": [5],
                "attributes": {},
            },
            {
                "pk": TIM_GROUPS[0],
                "num_pk": 4,
                "name": "homelab-observer",
                "is_superuser": False,
                "parents": [],
                "children": [],
                "roles": [],
                "users": [6],
                "attributes": {},
            },
        ]
        self.scopes = [
            {
                "pk": "openid-pk",
                "name": "authentik default OAuth Mapping: OpenID 'openid'",
                "scope_name": "openid",
                "managed": oidc.OPENID_MANAGED,
                "expression": "return {}",
            },
            {
                "pk": "email-pk",
                "name": "authentik default OAuth Mapping: OpenID 'email'",
                "scope_name": "email",
                "managed": oidc.EMAIL_MANAGED,
                "expression": 'return {"email": request.user.email, "email_verified": False}',
            },
            {
                "pk": "profile-pk",
                "name": "authentik default OAuth Mapping: OpenID 'profile'",
                "scope_name": "profile",
                "managed": oidc.PROFILE_MANAGED,
                "expression": 'return {"groups": [group.name for group in request.user.groups.all()]}',
            },
            {
                "pk": "groups-pk",
                "name": "homelab-groups",
                "scope_name": "groups",
                "managed": None,
                "expression": 'return {"groups": [group.name for group in request.user.ak_groups.all()]}',
            },
        ]
        self.providers = [
            {
                "pk": 1,
                "name": "homelab-grafana",
                "client_id": "socrat-grafana",
                "sub_mode": "hashed_user_id",
                "property_mappings": ["profile-pk", "email-pk", "openid-pk"],
            },
        ]
        self.applications: list[dict[str, object]] = []
        self.bindings: list[dict[str, object]] = []
        self.outposts = [
            {
                "pk": "outpost-pk",
                "name": "authentik Embedded Outpost",
                "managed": oidc.OUTPOST_MANAGED,
                "providers": [5, 9],
                "type": "proxy",
            },
        ]
        self.flows = [
            {"pk": "auth-flow", "slug": "default-authentication-flow"},
            {"pk": "consent-flow", "slug": "default-provider-authorization-explicit-consent"},
            {"pk": "invalidation-flow", "slug": "default-provider-invalidation-flow"},
        ]
        self.certificates = [{"pk": "cert-pk", "name": oidc.CERT_NAME}]
        self.provider_secrets: dict[int, object] = {}
        self._seq = 20
        server = self

        class Handler(BaseHTTPRequestHandler):
            @override
            def log_message(self, fmt, *args) -> None:
                """Stay quiet while the offline contract server runs."""

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_PATCH(self) -> None:
                self._handle("PATCH")

            def _handle(self, method):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                payload = json.loads(raw) if raw else None
                parsed = urllib.parse.urlsplit(self.path)
                server.calls.append((method, parsed.path, parsed.query, payload))
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._send(401, {"detail": "unauthorized"})
                try:
                    code, body = server.route(method, parsed.path, parsed.query, payload)
                except (
                    AttributeError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                    StopIteration,
                ) as error:
                    return self._send(500, {"detail": str(error)})
                self._send(code, body)

            def _send(self, code, body):
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:" + str(self.httpd.server_address[1])

    @override
    def start(self) -> None:
        """Start the offline contract server thread."""
        super().start()

    @override
    def run(self) -> None:
        """Serve contract requests until the server shuts down."""
        self.httpd.serve_forever()

    def close(self) -> None:
        """Stop the offline contract server and release its socket."""
        self.httpd.shutdown()
        self.httpd.server_close()

    def page(self, rows) -> dict[str, object]:
        """Wrap fixture rows in the API pagination envelope."""
        result: dict[str, object] = {
            "pagination": {"next": None, "count": len(rows)},
            "results": rows,
        }
        return result

    def route(self, method, path, query, payload) -> tuple[int, object]:
        """Route an offline contract API request to the fake backend."""
        if method == "GET" and path == "/api/v3/admin/version/":
            return 200, {"version_current": oidc.AUTHENTIK_VERSION}
        collections = {
            "/api/v3/core/users/": self.users,
            "/api/v3/core/groups/": self.groups,
            "/api/v3/propertymappings/provider/scope/": self.scopes,
            "/api/v3/providers/oauth2/": self.providers,
            "/api/v3/outposts/instances/": self.outposts,
            "/api/v3/flows/instances/": self.flows,
            "/api/v3/crypto/certificatekeypairs/": self.certificates,
            "/api/v3/policies/bindings/": self.bindings,
        }
        if method == "GET" and path in collections:
            return 200, self.page(collections[path])
        if method == "GET" and path == "/api/v3/core/applications/":
            rows = self.applications if "superuser_full_list=true" in query else []
            return 200, self.page(rows)
        if method == "POST" and path == "/api/v3/core/groups/":
            self._seq += 1
            created = dict(payload)
            created["pk"] = "group-" + str(self._seq)
            created["num_pk"] = self._seq
            self.groups.append(created)
            return 201, created
        if method == "POST" and path == "/api/v3/propertymappings/provider/scope/":
            self._seq += 1
            created = dict(payload)
            # Match Authentik's trim_whitespace serializer behavior.
            created["expression"] = created["expression"].strip()
            created["pk"] = "map-" + str(self._seq)
            created["managed"] = None
            self.scopes.append(created)
            return 201, created
        if method == "PATCH" and path.startswith("/api/v3/propertymappings/provider/scope/"):
            pk = path.rstrip("/").split("/")[-1]
            row = next(item for item in self.scopes if item["pk"] == pk)
            row.update(payload)
            return 200, row
        if method == "POST" and path == "/api/v3/providers/oauth2/":
            if self.fail_provider:
                self.fail_provider = False
                return 500, {"detail": "unavailable"}
            if self.attach_outpost:
                self.outposts[0]["providers"] = list(self.outposts[0]["providers"]) + [101]
            self._seq += 1
            created = dict(payload)
            self.provider_secrets[self._seq] = created.pop("client_secret", None)
            created["pk"] = self._seq
            self.providers.append(created)
            return 201, created
        if method == "PATCH" and path.startswith("/api/v3/providers/oauth2/"):
            pk = int(path.rstrip("/").split("/")[-1])
            row = next(item for item in self.providers if item["pk"] == pk)
            updated = dict(payload)
            if "client_secret" in updated:
                self.provider_secrets[pk] = updated.pop("client_secret")
            row.update(updated)
            return 200, row
        if method == "POST" and path == "/api/v3/core/applications/":
            self._seq += 1
            created = dict(payload)
            created["pk"] = "app-" + str(self._seq)
            self.applications.append(created)
            return 201, created
        if method == "PATCH" and path.startswith("/api/v3/core/applications/"):
            slug = path.rstrip("/").split("/")[-1]
            row = next(item for item in self.applications if item["slug"] == slug)
            row.update(payload)
            return 200, row
        if method == "POST" and path == "/api/v3/policies/bindings/":
            self._seq += 1
            created = dict(payload)
            created["pk"] = self._seq
            self.bindings.append(created)
            return 201, created
        if (
            method == "POST"
            and path.startswith("/api/v3/core/groups/")
            and path.endswith("/add_user/")
        ):
            pk = path.split("/")[-3]
            group = next(item for item in self.groups if item["pk"] == pk)
            user_pk = payload["pk"]
            user = next(item for item in self.users if item["pk"] == user_pk)
            if user_pk not in _sequence(group["users"]):
                _sequence(group["users"]).append(user_pk)
            if group["pk"] not in _sequence(user["groups"]):
                _sequence(user["groups"]).append(group["pk"])
            if self.drop_legacy_on_add:
                user["groups"] = [item for item in user["groups"] if item == group["pk"]]
            return 200, {"pk": user_pk}
        return 404, {"detail": "missing"}

    def writes(self) -> list[tuple[str, str, str, object]]:
        """Return only the non-GET calls recorded by the offline server."""
        return [call for call in self.calls if call[0] != "GET"]


class NetBirdOIDCTests(unittest.TestCase):
    """Verify NetBird OIDC flows against a fake Authentik server."""
    @override
    def setUp(self) -> None:
        """Start the offline contract server and write fixture documents."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mappings = self.root / "account-mappings.json"
        write_json(
            self.mappings,
            {
                "alchemmist": {
                    "idpUserUuid": "9e33877a-3eaa-4541-98eb-8cdc10088ef6",
                    "email": "anton.ingrish@gmail.com",
                    "groups": ["homelab-owner"],
                },
                "antropophag": {
                    "idpUserUuid": "6015c85b-82e9-49ce-a4e3-0270c676e26d",
                    "email": "antropophag@gmail.com",
                    "groups": ["homelab-observer"],
                },
            },
        )
        write_json(self.root / "credentials.json", {"AUTHENTIK_BOOTSTRAP_TOKEN": TOKEN})
        self.config = self.root / "netbird.yaml"
        self.config.write_text(
            "server:\n  auth:\n    issuer: "
            + ISSUER
            + "\n  relaySecret: relay-secret-must-not-leak\n"
        )
        self.fake = FakeAuthentik()
        self.fake.start()

    @override
    def tearDown(self) -> None:
        """Stop the offline contract server and remove its directory."""
        self.fake.close()
        self.tmp.cleanup()

    def run_tool(self, *args: object) -> tuple[int, str, str]:
        """Run the offline tool with redirected standard streams."""
        import contextlib
        from io import StringIO

        stdout, stderr = StringIO(), StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = oidc.main(
                [
                    str(self.root),
                    *args,
                    "--base-url",
                    self.fake.base,
                    "--mappings",
                    str(self.mappings),
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def plan(self, config=True) -> dict[str, object]:
        """Run the tool's plan command and parse its JSON report."""
        args = ["plan"]
        if config:
            args += ["--netbird-config", str(self.config)]
        code, out, err = self.run_tool(*args)
        assert err == "", err
        assert code == 0, out
        result: dict[str, object] = json.loads(out)
        return result

    def test_callback_follows_pinned_redirect_algorithm(self) -> None:
        """The callback follows the pinned redirect algorithm."""

        assert oidc.callback_from_issuer(ISSUER) == CALLBACK
        assert oidc.callback_from_issuer(ISSUER + "/") == CALLBACK
        assert oidc.callback_from_issuer("https://netbird.socrat.alchemmist.xyz") == CALLBACK
        assert oidc.callback_from_issuer("https://netbird.socrat.alchemmist.xyz/oauth2//") == "https://netbird.socrat.alchemmist.xyz/oauth2//oauth2/callback"
        with self.assertRaises(RuntimeError):
            oidc.validate_management_issuer("https://example.com/oauth2")
        with self.assertRaises(RuntimeError):
            oidc.validate_management_issuer(
                "https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/"
            )
        with self.assertRaises(RuntimeError):
            oidc.validate_management_issuer("http://netbird.socrat.alchemmist.xyz/oauth2")
        assert "--callback" not in SOURCE.read_text()
        assert "configure" not in SOURCE.read_text()

    def test_profile_expression_is_allowlisted_and_not_a_groups_scope(self) -> None:
        """The profile expression is allowlisted, not a groups scope."""

        expression = oidc.profile_expression()
        assert expression == expression.strip(), "Expression must survive Authentik serializer round-trip"
        assert "request.user.ak_groups.all()" in expression
        assert "request.user.groups.all()" not in expression
        assert "request.user.email" not in expression
        assert '"sub"' not in expression
        for name in oidc.GROUP_NAMES:
            assert repr(name) in expression
        assert "homelab-owner" not in expression
        assert "authentik Admins" not in expression
        assert oidc.UPSTREAM_SCOPES == ("openid", "profile", "email")
        assert "groups" not in oidc.UPSTREAM_SCOPES

    def test_check_and_plan_are_get_only_and_do_not_invent_callback(self) -> None:
        """Check and plan are GET-only and never invent a callback."""

        code, out, err = self.run_tool("check")
        assert code == 1, err
        assert "reconciled=false" in out
        assert self.fake.writes() == []
        assert not (self.root / oidc.JOURNAL_NAME).exists()
        assert not (self.root / oidc.RUNTIME_NAME).exists()
        missing = self.plan(config=False)
        assert missing["callback"] is None
        assert "missing NetBird issuer config" in _string(_sequence(missing["blockers"])[0])
        assert "https://netbird.socrat.alchemmist.xyz/oauth2/callback" not in json.dumps(missing)
        assert "relay-secret-must-not-leak" not in json.dumps(missing)
        assert self.fake.writes() == []
        present = self.plan()
        assert present["callback"] == CALLBACK
        assert present["user_id_claim"] == "sub"
        assert present["display_claim"] == "name"
        assert present["email_claim"] == "email"
        assert not present["get_userinfo"]
        assert not present["dashboard_groups_scope_sufficient"]
        assert present["sub_mode"] == "user_uuid"
        assert present["sha256"] == self.plan()["sha256"]
        assert any(call[1] == "/api/v3/core/applications/" and "superuser_full_list=true" in call[2] for call in self.fake.calls)

    def test_apply_requires_digest_and_keeps_secret_runtime_only(self) -> None:
        """Apply requires a digest and keeps the secret runtime-only."""

        code, out, err = self.run_tool("apply", "--netbird-config", str(self.config))
        assert code == 1
        assert "Plan digest mismatch" in err
        assert self.fake.writes() == []
        assert TOKEN not in out + err
        approved = self.plan()
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", "0" * 64, "--netbird-config", str(self.config)
        )
        assert code == 1
        assert self.fake.writes() == []
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", approved["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 0, err
        assert "relay-secret-must-not-leak" not in out + err
        runtime = json.loads((self.root / oidc.RUNTIME_NAME).read_text())
        secret = runtime["client_secret"]
        assert secret not in out + err
        assert secret not in (self.root / oidc.JOURNAL_NAME).read_text()
        assert (self.root / oidc.RUNTIME_NAME).stat().st_mode & 511 == 384
        assert (self.root / oidc.JOURNAL_NAME).stat().st_mode & 511 == 384
        journal = json.loads((self.root / oidc.JOURNAL_NAME).read_text())
        assert journal["client_secret_sha256"] == hashlib.sha256(secret.encode()).hexdigest()
        assert journal["pilot_users"]["alchemmist"]["uuid"] == "9e33877a-3eaa-4541-98eb-8cdc10088ef6"
        assert journal["pilot_users"]["antropophag"]["pk"] == 6
        assert set(journal["groups"]) == set(oidc.GROUP_NAMES)
        for recorded in journal["groups"].values():
            assert isinstance(recorded["pk"], str)
            assert isinstance(recorded["num_pk"], int)
        assert isinstance(journal["provider_pk"], int)
        assert isinstance(journal["application_pk"], str)
        assert journal["callback"] == CALLBACK
        assert journal["marker"] == _mapping(_mapping(self.fake.groups[-1])["attributes"])[oidc.MARKER_ATTRIBUTE]
        provider = next(item for item in self.fake.providers if item["name"] == oidc.PROVIDER_NAME)
        assert provider["sub_mode"] == "user_uuid"
        assert provider["include_claims_in_id_token"]
        assert provider["redirect_uris"] == [{"matching_mode": "strict", "url": CALLBACK, "redirect_uri_type": "authorization"}]
        assert provider["property_mappings"] == ["openid-pk", "email-pk", journal["mapping_pk"]]
        assert "profile-pk" not in _sequence(provider["property_mappings"])
        assert "groups-pk" not in _sequence(provider["property_mappings"])
        assert "password" not in _sequence(provider["grant_types"])
        mapping = next(item for item in self.fake.scopes if item["pk"] == journal["mapping_pk"])
        assert mapping["scope_name"] == "profile"
        assert mapping["expression"] != self.fake.scopes[2]["expression"]
        for group in self.fake.groups:
            if group["name"] in oidc.GROUP_NAMES:
                assert not group["is_superuser"]
                assert group["parents"] == []
                assert group["roles"] == []
                assert sorted(_sequence(group["users"])) == [5, 6]
        assert self.fake.outposts[0]["providers"] == [5, 9]
        assert self.fake.providers[0]["name"] == "homelab-grafana"
        owner = self.fake.users[0]
        assert owner["is_superuser"] == True
        assert set(OWNER_GROUPS).issubset(_sequence(owner["groups"]))
        assert self.fake.users[1]["is_superuser"] == False
        assert TIM_GROUPS[0] in _sequence(self.fake.users[1]["groups"])
        user_writes = [
            call for call in self.fake.writes() if call[1].startswith("/api/v3/core/users/")
        ]
        assert user_writes == []
        outpost_writes = [call for call in self.fake.writes() if "outposts" in call[1]]
        assert outpost_writes == []
        binding = self.fake.bindings[0]
        assert binding["group"] == journal["groups"][oidc.ADMISSION_GROUP]["pk"]
        assert "user" not in binding
        code, out, err = self.run_tool("check", "--netbird-config", str(self.config))
        assert code == 0, err + out
        assert "reconciled=true" in out
        again = self.plan()
        before = len(self.fake.writes())
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", again["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 0, err
        assert len(self.fake.writes()) == before
        assert json.loads((self.root / oidc.RUNTIME_NAME).read_text())["client_secret"] == secret

    def test_apply_does_not_adopt_or_continue_after_a_foreign_object(self) -> None:
        """Apply neither adopts nor continues after a foreign object."""

        self.fake.providers.append(
            {
                "pk": 77,
                "name": oidc.PROVIDER_NAME,
                "client_id": "other",
                "sub_mode": "hashed_user_id",
                "property_mappings": ["profile-pk"],
                "grant_types": ["authorization_code"],
                "redirect_uris": [],
            }
        )
        code, out, err = self.run_tool("plan", "--netbird-config", str(self.config))
        assert code == 0
        plan = json.loads(out)
        assert any("adopt" in _string(item) for item in _sequence(plan["blockers"]))
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", plan["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1
        assert self.fake.writes() == []

    def test_partial_provider_failure_retries_without_a_second_group(self) -> None:
        """A partial provider failure retries without a second group."""

        self.fake.fail_provider = True
        approved = self.plan()
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", approved["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1, out
        assert sum(1 for call in self.fake.writes() if call[1] == "/api/v3/core/groups/") == 3
        journal = json.loads((self.root / oidc.JOURNAL_NAME).read_text())
        assert len(journal["groups"]) == 3
        assert "provider_pk" not in journal
        retry = self.plan()
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", retry["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 0, err
        assert sum(1 for call in self.fake.writes() if call[1] == "/api/v3/core/groups/") == 3
        assert sum(1 for item in self.fake.providers if item["name"] == oidc.PROVIDER_NAME) == 1

    def test_tim_superuser_group_and_extra_member_block_without_writes(self) -> None:
        """Superuser groups and extra members block without writes."""

        _sequence(self.fake.users[1]["groups"]).append(OWNER_GROUPS[0])
        code, out, err = self.run_tool("plan", "--netbird-config", str(self.config))
        assert code == 1
        assert "superuser group" in err
        assert self.fake.writes() == []
        self.fake.users[1]["groups"] = list(TIM_GROUPS)
        group = {
            "pk": "owned-group",
            "num_pk": 9,
            "name": oidc.ADMISSION_GROUP,
            "is_superuser": False,
            "parents": [],
            "children": [],
            "roles": [],
            "users": [5, 6, 99],
            "attributes": {oidc.MARKER_ATTRIBUTE: "marker-1"},
        }
        self.fake.groups.append(group)
        write_json(
            self.root / oidc.JOURNAL_NAME,
            {
                "version": 1,
                "marker": "marker-1",
                "groups": {oidc.ADMISSION_GROUP: {"pk": "owned-group", "num_pk": 9}},
                "pilot_users": {
                    "alchemmist": {"pk": 5, "uuid": "9e33877a-3eaa-4541-98eb-8cdc10088ef6"},
                    "antropophag": {"pk": 6, "uuid": "6015c85b-82e9-49ce-a4e3-0270c676e26d"},
                },
            },
        )
        code, out, err = self.run_tool("plan", "--netbird-config", str(self.config))
        assert code == 0, err
        plan = json.loads(out)
        assert any("outside the owner and Tim pilot" in item for item in plan["blockers"])
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", plan["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1
        assert self.fake.writes() == []

    def test_legacy_membership_loss_stops_without_a_user_patch(self) -> None:
        """Legacy membership loss stops without a user patch."""

        self.fake.drop_legacy_on_add = True
        approved = self.plan()
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", approved["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1
        assert "Reviewed legacy group membership is missing" in err
        assert not any(call[1].startswith("/api/v3/core/users/") and call[0] != "GET" for call in self.fake.calls)

    def test_journal_symlink_is_not_followed(self) -> None:
        """A journal symlink is never followed."""

        approved = self.plan()
        outside = self.root / "outside.json"
        outside.write_text('{"client_secret": "nope"}\n')
        (self.root / oidc.JOURNAL_NAME).symlink_to(outside)
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", approved["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1
        assert "symlink" in err
        assert self.fake.writes() == []
        assert outside.read_text() == '{"client_secret": "nope"}\n'

    def test_markerless_nonempty_journal_is_not_replaced_or_used_to_mint_a_secret(self) -> None:
        """A markerless journal is never replaced or used to mint a secret."""

        approved = self.plan()
        write_json(
            self.root / oidc.JOURNAL_NAME,
            {
                "provider_pk": 77,
                "groups": {oidc.ADMISSION_GROUP: {"pk": "owned-group", "num_pk": 9}},
            },
        )
        before = (self.root / oidc.JOURNAL_NAME).read_text()
        code, out, err = self.run_tool(
            "apply", "--approve-sha256", approved["sha256"], "--netbird-config", str(self.config)
        )
        assert code == 1
        assert "markerless journal" in err
        assert (self.root / oidc.JOURNAL_NAME).read_text() == before
        assert not (self.root / oidc.RUNTIME_NAME).exists()
        assert self.fake.writes() == []

    def test_pinned_connector_source_matches_when_present(self) -> None:
        """The pinned connector source matches its digest when present."""

        repo = Path(os.environ.get("NETBIRD_V082_SRC", "/tmp/netbird-v082-repo"))
        connector = repo / "idp/dex/connector.go"
        if not connector.is_file():
            self.skipTest("pinned NetBird v0.82.0 source is not present")
        assert hashlib.sha256(connector.read_bytes()).hexdigest() == oidc.CONNECTOR_SHA256
        dex = Path("/tmp/netbird-dex/oidc.go")
        if dex.is_file():
            assert hashlib.sha256(dex.read_bytes()).hexdigest() == oidc.DEX_OIDC_SHA256
        test_path = repo / "idp/dex/homelab_upstream_scopes_test.go"
        test_path.write_text(GO_CONNECTOR_TEST)
        env = dict(os.environ)
        env["GOTOOLCHAIN"] = "go1.26.10"
        completed = subprocess.run(
            ["go", "test", "./idp/dex/", "-count=1", "-timeout", "180s", "-run", "TestHomelab"],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


GO_CONNECTOR_TEST = r"""package dex

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestHomelabUpstreamGenericOIDCScopes(t *testing.T) {
	redirect := "https://netbird.socrat.alchemmist.xyz/oauth2/callback"
	for _, typ := range []string{"oidc", "authentik"} {
		t.Run(typ, func(t *testing.T) {
			data, err := buildOIDCConnectorConfig(&ConnectorConfig{
				Type: typ, Issuer: "https://auth.example/application/o/netbird-pilot/",
				ClientID: "id", ClientSecret: "secret",
			}, redirect)
			require.NoError(t, err)
			var got map[string]any
			require.NoError(t, json.Unmarshal(data, &got))
			assert.Equal(t, []any{"openid", "profile", "email"}, got["scopes"])
			assert.Equal(t, true, got["insecureEnableGroups"])
			assert.Equal(t, true, got["insecureSkipEmailVerified"])
			_, claim := got["claimMapping"]
			_, userID := got["userIDKey"]
			_, userInfo := got["getUserInfo"]
			assert.False(t, claim)
			assert.False(t, userID)
			assert.False(t, userInfo)
			assert.Equal(t, redirect, got["redirectURI"])
		})
	}
	okta, err := buildOIDCConnectorConfig(&ConnectorConfig{Type: "okta"}, redirect)
	require.NoError(t, err)
	var got map[string]any
	require.NoError(t, json.Unmarshal(okta, &got))
	assert.Equal(t, []any{"openid", "profile", "email", "groups"}, got["scopes"])
}

func TestHomelabRedirectFromIssuer(t *testing.T) {
	p := &Provider{config: &Config{Issuer: "https://netbird.socrat.alchemmist.xyz/oauth2"}}
	assert.Equal(t, "https://netbird.socrat.alchemmist.xyz/oauth2/callback", p.GetRedirectURI())
	p.config.Issuer = "https://netbird.socrat.alchemmist.xyz/oauth2/"
	assert.Equal(t, "https://netbird.socrat.alchemmist.xyz/oauth2/callback", p.GetRedirectURI())
	p.config.Issuer = "https://netbird.socrat.alchemmist.xyz"
	assert.Equal(t, "https://netbird.socrat.alchemmist.xyz/oauth2/callback", p.GetRedirectURI())
}
"""


if __name__ == "__main__":
    unittest.main()
