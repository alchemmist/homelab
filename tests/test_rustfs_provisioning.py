"""Tests for RustFS provisioning logic."""

import contextlib
import email.message
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import CodeType, FunctionType, ModuleType, SimpleNamespace
from typing import Protocol, Self, cast
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

SECRET_FILE_COUNT = 4
SECRET_FILE_MODE = 0o600
POLICY_BINDING_COUNT = 2
LAUNCHER_PROVIDER_PK = 17


def module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/rustfs" / f"{name}.py")
    if spec is None or spec.loader is None:
        msg = "Script module under test is not loadable: " + name
        raise RuntimeError(msg)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def put(path: Path, data: object) -> None:
    path.write_text(json.dumps(data))
    path.chmod(0o600)


class PolicyRule(Protocol):
    """Callable shape of the reviewed authentik policy expression under test."""

    def __call__(self, request: object, ak_is_group_member: object) -> dict[str, object]:
        """Evaluate the policy once and return its payload."""
        ...


class McState:
    """In-memory stand-in for the reviewed mc invocation surface."""

    def __init__(self) -> None:
        """Start with empty in-memory mc state and no recorded calls."""
        self.users: dict[str, dict[str, object]] = {}
        self.policies: dict[str, object] = {}
        self.buckets: list[str] = []
        self.calls: list[list[str]] = []

    def policy_op(self, args: list[str]) -> object:
        """Answer one admin policy verb from in-memory policy state."""
        if args[:3] == ["admin", "policy", "list"]:
            return [{"policy": k} for k in self.policies]
        if args[:3] == ["admin", "policy", "info"]:
            Path(args[-1]).write_text(json.dumps(self.policies[args[4]]))
            return []
        if args[:3] == ["admin", "policy", "create"]:
            self.policies[args[4]] = json.loads(Path(args[5]).read_text())
            return []
        raise AssertionError(args)

    def user_op(self, args: list[str], stdin: bytes | None) -> object:
        """Answer one admin user verb from in-memory user state."""
        if args[:3] == ["admin", "user", "list"]:
            return [{"accessKey": k} for k in self.users]
        if args[:3] == ["admin", "user", "info"]:
            return [self.users[args[-1]]]
        if args[:3] == ["admin", "user", "add"]:
            assert stdin is not None
            access, secret = stdin.decode().splitlines()
            assert secret not in " ".join(args)
            self.users[access] = {"userStatus": "enabled", "policyName": ""}
            return []
        if args[:3] == ["admin", "policy", "attach"]:
            self.users[args[-1]]["policyName"] = args[4]
            return []
        raise AssertionError(args)

    def __call__(
        self, _mc: object, _config: object, args: list[str], stdin: bytes | None = None
    ) -> object:
        """Record one reviewed mc invocation and answer it from in-memory state."""
        self.calls.append(args)
        if args[0] == "ls":
            return [{"key": x + "/"} for x in self.buckets]
        if args[0] == "mb":
            self.buckets.append("spi-evidence")
            return []
        if args[:2] == ["anonymous", "get"]:
            return [{"permission": "private"}]
        if args[:3] == ["admin", "policy", "attach"]:
            return self.user_op(args, stdin)
        if args[:2] == ["admin", "policy"]:
            return self.policy_op(args)
        if args[:2] == ["admin", "user"]:
            return self.user_op(args, stdin)
        raise AssertionError(args)


def run_bootstrap(b: ModuleType, argv: list[str], fake: object) -> None:
    """Run one real bootstrap CLI invocation against the recorded fake."""
    with (
        patch("sys.argv", argv),
        patch.object(b, "run", fake),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        b.main()


class Response:
    """Fake API response body fed straight from in-memory state."""

    def __init__(self, data: object) -> None:
        """Store the payload this fake body will return."""
        self.data = data

    def __enter__(self) -> Self:
        """Return self as the opened context body."""
        return self

    def __exit__(self, *a: object) -> object:
        """Close the fake context without cleanup work."""
        return None

    def read(self, *_: object) -> bytes:
        return json.dumps(self.data).encode()


class HTTP:
    """Fake authentik API surface answering entirely from in-memory tables."""

    def __init__(self) -> None:
        """Start with empty API tables and no recorded writes."""
        self.tables: dict[str, list[dict[str, object]]] = {}
        self.writes: list[tuple[str, str, dict[str, object]]] = []
        self.detail_error: int | None = None

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> Response:
        del timeout  # fake keeps the urlopen-style signature
        path = urllib.parse.urlsplit(request.full_url).path.removeprefix("/api/v3/")
        method = request.get_method()
        if method == "GET":
            return self._get(request, path)
        payload = request.data
        assert isinstance(payload, (str, bytes, bytearray))
        data: dict[str, object] = json.loads(payload)
        self.writes.append((method, path, data))
        if method == "PATCH":
            assert path == "outposts/instances/outpost/"
            self.tables["outposts/instances/"][0].update(data)
            return Response(self.tables["outposts/instances/"][0])
        assert path not in ("core/users/", "core/groups/")
        data["pk"] = (
            100 + len(self.writes)
            if path.startswith("providers/")
            else "new-" + str(len(self.writes))
        )
        self.tables[path].append(data)
        return Response(data)

    def _get(self, request: urllib.request.Request, path: str) -> Response:
        if not (path.startswith("core/applications/") and path != "core/applications/"):
            # Simulate policy-filtered launcher list hiding all dedicated apps.
            return Response(
                {
                    "results": [] if path == "core/applications/" else self.tables[path],
                    "pagination": {"next": None},
                }
            )
        slug = path.split("/")[-2]
        if self.detail_error:
            raise urllib.error.HTTPError(
                request.full_url,
                self.detail_error,
                "refused",
                email.message.Message(),
                io.BytesIO(),
            )
        matches = [x for x in self.tables["core/applications/"] if x["slug"] == slug]
        if matches:
            return Response(matches[0])
        raise urllib.error.HTTPError(
            request.full_url, 404, "not found", email.message.Message(), io.BytesIO()
        )


def run_identity(m: ModuleType, http: object, argv: list[str]) -> None:
    """Run one real provision_identity CLI invocation against the fake opener."""
    with (
        patch("sys.argv", argv),
        patch.object(m.urllib.request, "build_opener", return_value=http),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        m.main()


class Provisioning(unittest.TestCase):
    """Check RustFS provisioning policies match exactly."""

    def test_policies_exact(self) -> None:
        b = module("bootstrap")
        assert b.POLICIES["spi-reader"]["Statement"][0]["Action"] == ["s3:GetObject"]
        for p in b.POLICIES.values():
            assert p["Statement"][0]["Resource"] == ["arn:aws:s3:::spi-evidence/spi/v1/*"]
            assert "s3:DeleteObject" not in p["Statement"][0]["Action"]
            assert "*" not in p["Statement"][0]["Action"]

    def test_policy_normalization_is_not_scope_widening(self) -> None:
        b = module("bootstrap")
        p = b.POLICIES["spi-reader"]
        equivalent: dict[str, object] = {
            "Version": "2012-10-17",
            "Statement": {
                "Sid": "label",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::spi-evidence/spi/v1/*",
            },
        }
        assert b.canonical_policy(p) == b.canonical_policy(equivalent)
        statement = equivalent["Statement"]
        assert isinstance(statement, dict)
        statement["Action"] = "s3:*"
        assert b.canonical_policy(p) != b.canonical_policy(equivalent)
        statement["Principal"] = "*"
        with pytest.raises(ValueError, match="unexpected policy grants"):
            b.canonical_policy(equivalent)

    def test_private_credentials(self) -> None:
        b = module("bootstrap")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c"
            put(path, {})
            b.private(path)
            path.chmod(0o644)
            with pytest.raises(ValueError, match="private owned regular credentials file"):
                b.private(path)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with pytest.raises(ValueError, match="private owned regular credentials file"):
                b.private(link)

    def test_bootstrap_resumes_and_is_idempotent(self) -> None:
        b = module("bootstrap")
        fake = McState()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            mc = d / "mc"
            mc.write_bytes(b"fake-reviewed-binary")
            creds = {
                role: {"access": role + "A" * 20, "secret": role + "S" * 30}
                for role in ("root", "reader", "writer")
            }
            path = d / "storage.json"
            put(path, {"endpoint": "http://127.0.0.1:19000", **creds})
            argv = [
                "bootstrap",
                "--credentials",
                str(path),
                "--mc",
                str(mc),
                "--mc-sha256",
                hashlib.sha256(mc.read_bytes()).hexdigest(),
            ]
            run_bootstrap(b, argv, fake)
            assert fake.calls == []
            run_bootstrap(b, [*argv, "--apply"], fake)
            fake.calls.clear()
            run_bootstrap(b, [*argv, "--apply"], fake)
            assert all(a[0] in ("ls", "anonymous") or a[2] in ("list", "info") for a in fake.calls)
            assert set(fake.users) == {creds[x]["access"] for x in ("reader", "writer")}
            fake.users[creds["reader"]["access"]]["policyName"] = "consoleAdmin"
            with pytest.raises(ValueError, match="existing user mismatch"):
                run_bootstrap(b, [*argv, "--apply"], fake)

    def test_secret_outputs_private_idempotent_and_isolated(self) -> None:
        m = module("secrets")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            put(
                d / "storage.json",
                {
                    role: {"access": role + "A" * 20, "secret": role + "S" * 30}
                    for role in ("root", "reader", "writer")
                },
            )
            put(
                d / "rustfs-client.json",
                {"client_id": "spi-rustfs-console", "client_secret": "private-oidc"},
            )
            argv = ["secrets", "--private-dir", str(d)]
            for _ in range(2):
                with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    m.main()
            outputs = list(d.glob("*.secret.json"))
            assert len(outputs) == SECRET_FILE_COUNT
            for path in outputs:
                assert path.stat().st_mode & 0o777 == SECRET_FILE_MODE
                doc = json.loads(path.read_text())
                assert doc["metadata"]["namespace"] == "rustfs"
                assert doc["metadata"]["name"] == path.name.removesuffix(".secret.json")
            assert (
                json.loads((d / "rustfs-reader.secret.json").read_text())["data"]
                != json.loads((d / "rustfs-root.secret.json").read_text())["data"]
            )

    def test_identity_additive_idempotent(self) -> None:
        m = module("provision_identity")
        collections: list[str] = list(m.COLLECTIONS)
        tables: dict[str, list[dict[str, object]]] = {x: [] for x in collections}
        http = HTTP()
        http.tables = tables
        writes = http.writes
        tables["core/groups/"] = [
            {"pk": "owner", "name": "homelab-owner"},
            {"pk": "platform", "name": "homelab-platform-operator"},
        ]
        tables["flows/instances/"] = [
            {"pk": s, "slug": s}
            for s in (
                "default-authentication-flow",
                "default-provider-authorization-explicit-consent",
                "default-provider-authorization-implicit-consent",
                "default-provider-invalidation-flow",
            )
        ]
        tables["crypto/certificatekeypairs/"] = [
            {"pk": "cert", "name": "authentik Self-signed Certificate"}
        ]
        tables["propertymappings/provider/scope/"] = [
            {
                "pk": n,
                "scope_name": n,
                "managed": "goauthentik.io/providers/oauth2/scope-" + n,
            }
            for n in ("openid", "profile", "email")
        ]
        tables["propertymappings/provider/scope/"].append(
            {"pk": "unrelated-netbird", "scope_name": "profile", "managed": None}
        )
        tables["outposts/instances/"] = [
            {
                "pk": "outpost",
                "managed": "goauthentik.io/outposts/embedded",
                "providers": [LAUNCHER_PROVIDER_PK],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            put(d / "credentials.json", {"AUTHENTIK_API_TOKEN": "private-token"})
            argv = ["provision_identity", "--private-dir", str(d)]
            run_identity(m, http, argv)
            assert writes == []
            assert not (d / "rustfs-client.json").exists()
            run_identity(m, http, [*argv, "--apply"])
            assert len(tables["policies/bindings/"]) == POLICY_BINDING_COUNT
            assert len(tables["providers/oauth2/"]) == 1
            assert tables["providers/proxy/"] == []
            assert len(tables["core/applications/"]) == 1
            providers = tables["outposts/instances/"][0]["providers"]
            assert isinstance(providers, list)
            assert LAUNCHER_PROVIDER_PK in providers
            writes.clear()
            run_identity(m, http, [*argv, "--apply"])
            assert writes == []
            for code in (401, 403, 500):
                http.detail_error = code
                with pytest.raises(ValueError, match="identity request failed"):
                    run_identity(m, http, [*argv, "--apply"])
                assert writes == []
            http.detail_error = None
            redirect_uris = tables["providers/oauth2/"][0]["redirect_uris"]
            assert isinstance(redirect_uris, list)
            callback: dict[str, object] = redirect_uris[0]
            assert callback["redirect_uri_type"] == "authorization"
            for key, value in [
                ("redirect_uri_type", "logout"),
                ("matching_mode", "regex"),
                ("url", "https://attacker.invalid/"),
            ]:
                previous = callback[key]
                callback[key] = value
                with pytest.raises(ValueError, match="existing object drift"):
                    run_identity(m, http, [*argv, "--apply"])
                callback[key] = previous
            tables["core/applications/"][0]["policy_engine_mode"] = "all"
            with pytest.raises(ValueError, match="existing object drift"):
                run_identity(m, http, [*argv, "--apply"])

    def test_human_admin_claim_is_exact_identity_only(self) -> None:
        expression = module("provision_identity").EXPRESSION
        source = expression.removeprefix("return ").strip()
        module_code = compile(
            "lambda request, ak_is_group_member: (" + source + ")",
            "<rustfs-policy-expression>",
            "exec",
        )
        # The only constant of the wrapper is the compiled policy lambda.
        lambda_code: CodeType = module_code.co_consts[0]
        expected_args = ("request", "ak_is_group_member")
        assert lambda_code.co_varnames[: len(expected_args)] == expected_args
        rule = cast("PolicyRule", FunctionType(lambda_code, {}))

        def claim(
            pk: int = 5,
            uuid: str = "9e33877a-3eaa-4541-98eb-8cdc10088ef6",
            username: str = "alchemmist",
            *,
            member: bool = False,
        ) -> object:
            def group_member(user: object, name: str) -> bool:
                del user, name  # policy expression calls the helper with both
                return member

            user = SimpleNamespace(pk=pk, uuid=uuid, username=username)
            return rule(SimpleNamespace(user=user), group_member)["rustfs_policy"]

        assert claim() == ["consoleAdmin"]
        for changed in ({"pk": 6}, {"uuid": "other"}, {"username": "robot"}):
            assert claim(**changed) == []
            assert claim(**changed, member=True) == ["spi-console-reader"]
        assert claim(pk=99, username="spi-writer", member=True) == ["spi-console-reader"]

    def test_builtin_scope_exact_managed_identity(self) -> None:
        m = module("provision_identity")
        official = {
            "pk": "official",
            "scope_name": "profile",
            "managed": "goauthentik.io/providers/oauth2/scope-profile",
        }
        custom = {"pk": "netbird", "scope_name": "profile", "managed": None}
        assert m.builtin_scope([official, custom], "profile") == "official"
        for rows in (
            [custom],
            [official, dict(official)],
            [dict(official, scope_name="groups")],
        ):
            with pytest.raises(ValueError, match="missing/duplicate/mismatched builtin scope"):
                m.builtin_scope(rows, "profile")
