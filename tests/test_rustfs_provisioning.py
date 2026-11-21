import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import email.message
import urllib.parse
import urllib.request
import urllib.error
from typing import Self, cast

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/rustfs" / f"{name}.py")
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def put(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)


class FakeMc:
    """In-memory stand-in for the reviewed mc double bootstrap shells out to."""

    def __init__(self) -> None:
        """Allocate the in-memory users, policies, buckets, and call log."""
        self.users: dict[str, dict[str, object]] = {}
        self.policies: dict[str, object] = {}
        self.buckets: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(
        self, _mc: object, _config: object, args: "list[str]", stdin: "bytes | None" = None
    ) -> object:
        """Record one reviewed mc invocation and route it read or mutate."""
        self.calls.append(args)
        response = self._read(args)
        if response is None:
            return self._mutate(args, stdin)
        return response

    def _read(self, args: "list[str]") -> "object | None":
        if args[:3] == ["admin", "user", "list"]:
            return [{"accessKey": k} for k in self.users]
        if args[:3] == ["admin", "policy", "list"]:
            return [{"policy": k} for k in self.policies]
        if args[0] == "ls":
            return [{"key": x + "/"} for x in self.buckets]
        if args[:3] == ["admin", "policy", "info"]:
            Path(args[-1]).write_text(json.dumps(self.policies[args[4]]))
            return []
        if args[:3] == ["admin", "user", "info"]:
            return [self.users[args[-1]]]
        if args[:2] == ["anonymous", "get"]:
            return [{"permission": "private"}]
        return None

    def _mutate(self, args: "list[str]", stdin: "bytes | None") -> object:
        if args[0] == "mb":
            self.buckets.append("spi-evidence")
            return []
        if args[:3] == ["admin", "policy", "create"]:
            self.policies[args[4]] = json.loads(Path(args[5]).read_text())
            return []
        if args[:3] == ["admin", "user", "add"]:
            access, secret = cast("bytes", stdin).decode().splitlines()
            if secret in " ".join(args):
                leak = "secret leaked to argv"
                raise AssertionError(leak)
            self.users[access] = {"userStatus": "enabled", "policyName": ""}
            return []
        if args[:3] == ["admin", "policy", "attach"]:
            self.users[args[-1]]["policyName"] = args[4]
            return []
        raise AssertionError(args)


class FakeResponse:
    """Context-manager response wrapper around one canned JSON payload."""

    def __init__(self, data: object) -> None:
        """Store the payload served by read()."""
        self.data = data

    def __enter__(self) -> Self:
        """Return self as the context-managed response object."""
        return self

    def __exit__(self, *args: object) -> None:
        """Accept any exception info without side effects."""

    def read(self, *args: object) -> bytes:
        """Serialize the stored payload the way urllib responses do."""
        return json.dumps(self.data).encode()


class FakeAuthentikHTTP:
    """In-memory opener covering the identity provisioner's API surface."""

    def __init__(
        self,
        test: unittest.TestCase,
        tables: "dict[str, list[dict[str, object]]]",
        writes: "list[tuple[str, str, dict[str, object]]]",
        detail_error: "list[int]",
    ) -> None:
        """Bind the asserting test plus the in-memory API tables and logs."""
        self.test = test
        self.tables = tables
        self.writes = writes
        self.detail_error = detail_error

    def open(self, request: urllib.request.Request, **opts: object) -> "FakeResponse":
        """Dispatch one opener request against the in-memory tables."""
        path = urllib.parse.urlsplit(request.full_url).path.removeprefix("/api/v3/")
        method = request.get_method()
        if method == "GET":
            return self._get(request, path)
        return self._write(request, method, path)

    def _get(self, request: urllib.request.Request, path: str) -> "FakeResponse":
        if path.startswith("core/applications/") and path != "core/applications/":
            return self._application_detail(request, path)
        # Simulate policy-filtered launcher list hiding all dedicated apps.
        return FakeResponse(
            {
                "results": [] if path == "core/applications/" else self.tables[path],
                "pagination": {"next": None},
            }
        )

    def _application_detail(self, request: urllib.request.Request, path: str) -> "FakeResponse":
        slug = path.split("/")[-2]
        if self.detail_error[0]:
            raise urllib.error.HTTPError(
                request.full_url,
                self.detail_error[0],
                "refused",
                email.message.Message(),
                io.BytesIO(),
            )
        matches = [x for x in self.tables["core/applications/"] if x["slug"] == slug]
        if matches:
            return FakeResponse(matches[0])
        raise urllib.error.HTTPError(
            request.full_url, 404, "not found", email.message.Message(), io.BytesIO()
        )

    def _write(self, request: urllib.request.Request, method: str, path: str) -> "FakeResponse":
        data = cast("dict[str, object]", json.loads(cast("bytes | str", request.data)))
        self.writes.append((method, path, data))
        if method == "PATCH":
            self.test.assertEqual(path, "outposts/instances/outpost/")
            self.tables["outposts/instances/"][0].update(data)
            return FakeResponse(self.tables["outposts/instances/"][0])
        self.test.assertNotIn(path, ("core/users/", "core/groups/"))
        data["pk"] = (
            100 + len(self.writes)
            if path.startswith("providers/")
            else "new-" + str(len(self.writes))
        )
        self.tables[path].append(data)
        return FakeResponse(data)


class Provisioning(unittest.TestCase):
    def test_policies_exact(self):
        b = module("bootstrap")
        self.assertEqual(b.POLICIES["spi-reader"]["Statement"][0]["Action"], ["s3:GetObject"])
        for p in b.POLICIES.values():
            self.assertEqual(p["Statement"][0]["Resource"], ["arn:aws:s3:::spi-evidence/spi/v1/*"])
            self.assertNotIn("s3:DeleteObject", p["Statement"][0]["Action"])
            self.assertNotIn("*", p["Statement"][0]["Action"])

    def test_policy_normalization_is_not_scope_widening(self):
        b = module("bootstrap")
        p = b.POLICIES["spi-reader"]
        equivalent = {
            "Version": "2012-10-17",
            "Statement": {
                "Sid": "label",
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::spi-evidence/spi/v1/*",
            },
        }
        self.assertEqual(b.canonical_policy(p), b.canonical_policy(equivalent))
        equivalent["Statement"]["Action"] = "s3:*"
        self.assertNotEqual(b.canonical_policy(p), b.canonical_policy(equivalent))
        equivalent["Statement"]["Principal"] = "*"
        with self.assertRaises(ValueError):
            b.canonical_policy(equivalent)

    def test_private_credentials(self):
        b = module("bootstrap")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c"
            put(path, {})
            b.private(path)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                b.private(path)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                b.private(link)

    def test_bootstrap_resumes_and_is_idempotent(self):
        b = module("bootstrap")
        mc_fake = FakeMc()
        users = mc_fake.users
        calls = mc_fake.calls

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            mc = d / "mc"
            mc.write_bytes(b"fake-reviewed-binary")
            creds = {
                "endpoint": "http://127.0.0.1:19000",
                **{
                    role: {"access": role + "A" * 20, "secret": role + "S" * 30}
                    for role in ("root", "reader", "writer")
                },
            }
            path = d / "storage.json"
            put(path, creds)
            argv = [
                "bootstrap",
                "--credentials",
                str(path),
                "--mc",
                str(mc),
                "--mc-sha256",
                hashlib.sha256(mc.read_bytes()).hexdigest(),
            ]
            with (
                patch("sys.argv", argv),
                patch.object(b, "run", mc_fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                b.main()
            self.assertEqual(calls, [])
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(b, "run", mc_fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                b.main()
            calls.clear()
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(b, "run", mc_fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                b.main()
            self.assertTrue(
                all(a[0] in ("ls", "anonymous") or a[2] in ("list", "info") for a in calls)
            )
            self.assertEqual(set(users), {creds[x]["access"] for x in ("reader", "writer")})
            users[creds["reader"]["access"]]["policyName"] = "consoleAdmin"
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(b, "run", mc_fake),
                self.assertRaises(ValueError),
            ):
                b.main()

    def test_secret_outputs_private_idempotent_and_isolated(self):
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
            self.assertEqual(len(outputs), 4)
            for path in outputs:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                doc = json.loads(path.read_text())
                self.assertEqual(doc["metadata"]["namespace"], "rustfs")
                self.assertEqual(doc["metadata"]["name"], path.name.removesuffix(".secret.json"))
            self.assertNotEqual(
                json.loads((d / "rustfs-reader.secret.json").read_text())["data"],
                json.loads((d / "rustfs-root.secret.json").read_text())["data"],
            )

    def test_identity_additive_idempotent(self):
        m = module("provision_identity")
        tables = {x: [] for x in m.COLLECTIONS}
        writes = []
        detail_error: list[int | None] = [None]
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
            {"pk": n, "scope_name": n, "managed": "goauthentik.io/providers/oauth2/scope-" + n}
            for n in ("openid", "profile", "email")
        ]
        tables["propertymappings/provider/scope/"].append(
            {"pk": "unrelated-netbird", "scope_name": "profile", "managed": None}
        )
        tables["outposts/instances/"] = [
            {"pk": "outpost", "managed": "goauthentik.io/outposts/embedded", "providers": [17]}
        ]

        http = FakeAuthentikHTTP(self, tables, writes, detail_error)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            put(d / "credentials.json", {"AUTHENTIK_API_TOKEN": "private-token"})
            argv = ["provision_identity", "--private-dir", str(d)]
            with (
                patch("sys.argv", argv),
                patch.object(m.urllib.request, "build_opener", return_value=http),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                m.main()
            self.assertEqual(writes, [])
            self.assertFalse((d / "rustfs-client.json").exists())
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(m.urllib.request, "build_opener", return_value=http),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                m.main()
            self.assertEqual(len(tables["policies/bindings/"]), 2)
            self.assertEqual(len(tables["providers/oauth2/"]), 1)
            self.assertEqual(tables["providers/proxy/"], [])
            self.assertEqual(len(tables["core/applications/"]), 1)
            self.assertIn(17, tables["outposts/instances/"][0]["providers"])
            writes.clear()
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(m.urllib.request, "build_opener", return_value=http),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                m.main()
            self.assertEqual(writes, [])
            for code in (401, 403, 500):
                detail_error[0] = code
                with (
                    patch("sys.argv", argv + ["--apply"]),
                    patch.object(m.urllib.request, "build_opener", return_value=http),
                    self.assertRaises(ValueError),
                ):
                    m.main()
                self.assertEqual(writes, [])
            detail_error[0] = None
            callback = tables["providers/oauth2/"][0]["redirect_uris"][0]
            self.assertEqual(callback["redirect_uri_type"], "authorization")
            for key, value in [
                ("redirect_uri_type", "logout"),
                ("matching_mode", "regex"),
                ("url", "https://attacker.invalid/"),
            ]:
                previous = callback[key]
                callback[key] = value
                with (
                    patch("sys.argv", argv + ["--apply"]),
                    patch.object(m.urllib.request, "build_opener", return_value=http),
                    self.assertRaises(ValueError),
                ):
                    m.main()
                callback[key] = previous
            tables["core/applications/"][0]["policy_engine_mode"] = "all"
            with (
                patch("sys.argv", argv + ["--apply"]),
                patch.object(m.urllib.request, "build_opener", return_value=http),
                self.assertRaises(ValueError),
            ):
                m.main()

    def test_human_admin_claim_is_exact_identity_only(self):
        from types import SimpleNamespace

        expression = module("provision_identity").EXPRESSION

        def claim(
            pk=5, uuid="9e33877a-3eaa-4541-98eb-8cdc10088ef6", username="alchemmist", member=False
        ):
            user = SimpleNamespace(pk=pk, uuid=uuid, username=username)
            return eval(
                expression.removeprefix("return "),
                {
                    "request": SimpleNamespace(user=user),
                    "ak_is_group_member": lambda user, name: member,
                },
            )["rustfs_policy"]

        self.assertEqual(claim(), ["consoleAdmin"])
        for changed in ({"pk": 6}, {"uuid": "other"}, {"username": "robot"}):
            self.assertEqual(claim(**changed), [])
            self.assertEqual(claim(**changed, member=True), ["spi-console-reader"])
        self.assertEqual(claim(pk=99, username="spi-writer", member=True), ["spi-console-reader"])

    def test_builtin_scope_exact_managed_identity(self):
        m = module("provision_identity")
        official = {
            "pk": "official",
            "scope_name": "profile",
            "managed": "goauthentik.io/providers/oauth2/scope-profile",
        }
        custom = {"pk": "netbird", "scope_name": "profile", "managed": None}
        self.assertEqual(m.builtin_scope([official, custom], "profile"), "official")
        for rows in ([custom], [official, dict(official)], [dict(official, scope_name="groups")]):
            with self.assertRaises(ValueError):
                m.builtin_scope(rows, "profile")
