"""Tests for the Authentik automation role."""

import ast
import contextlib
import importlib.util
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch
from urllib.parse import parse_qs

import pytest

# Dummy fixture values used by the offline contract checks; not real secrets.
BOOTSTRAP_CREDENTIAL = "unit-machine-token"
PREVIOUS_CREDENTIAL = "unit-old-token"
SIGNING_KEY = "unit-signing-key"

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "ansible/roles/authentik/files"
spec = importlib.util.spec_from_file_location("automation", FILES / "automation.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class Fake:
    """Fake application state driven by the automation module's API."""

    def __init__(self) -> None:
        self.users = [
            {
                "pk": 5,
                "uuid": a.OWNER_UUID,
                "username": "alchemmist",
                "is_superuser": True,
                "is_active": True,
            }
        ]
        self.groups: list[dict[str, object]] = []
        self.tokens: list[dict[str, object]] = []
        self.writes: list[tuple[str, str, object]] = []

    def __call__(self, token, method, path, data=None) -> object:
        """Serve a fake Authentik API call from the in-memory fixtures."""
        endpoint, _, query = path.partition("?")
        parts = endpoint.strip("/").split("/")
        # Paths like "tokens/<pk>/view_key/" have more than two segments.
        id_path_depth = 2
        if method != "GET":
            self.writes.append((method, path, data))
        if endpoint in [
            "providers/all/",
            "core/applications/",
            "flows/instances/",
            "outposts/instances/",
        ]:
            return {"results": []}
        rows = {"users": self.users, "groups": self.groups, "tokens": self.tokens}[parts[1]]
        if method == "DELETE":
            row = next(r for r in rows if str(r.get("pk")) == parts[2])
            rows.remove(row)
            self.tokens[:] = [t for t in self.tokens if t["user"] != row["pk"]]
            return None
        if method == "POST":
            if parts[1] == "groups":
                r = dict(pk="group-machine", users=[], **data)
            elif parts[1] == "users":
                r = dict(pk=7, uuid="machine-uuid", is_superuser=True, **data)
                # The fake group rows always carry their member-list under "users".
                cast("list[object]", self.groups[0]["users"]).append(r["pk"])
            else:
                r = dict(data)
            rows.append(r)
            return r
        if len(parts) > id_path_depth:
            if parts[-1] == "view_key":
                return {"key": BOOTSTRAP_CREDENTIAL}
            return next(
                r
                for r in rows
                if str(r.get("pk", r.get("identifier"))) == parts[2]
                or r.get("identifier") == parts[2]
            )
        for key, values in parse_qs(query).items():
            if key != "page_size":
                rows = [r for r in rows if r.get(key) == values[0]]
        return {"results": rows}


class BootstrapManifest(TypedDict):
    """Manifest captured by bootstrap.py via stdin."""

    stringData: dict[str, str]


class AutomationTests(unittest.TestCase):
    """Validate the Authentik automation playbook behaviour on fake state."""

    def root(self, d) -> Path:
        """Create a 0700 root with fixture bootstrap credentials."""
        p = Path(d)
        p.chmod(0o700)
        a.save(
            p / "credentials.json",
            {
                "AUTHENTIK_BOOTSTRAP_TOKEN": "unit-old-token",
                "AUTHENTIK_BOOTSTRAP_PASSWORD": "unit-old-password",
                "AUTHENTIK_SECRET_KEY": "unit-signing-key",
            },
        )
        return p

    def test_apply_and_repeat_do_not_delete_or_change_humans(self) -> None:
        """Repeated applies converge without deleting humans or leaking tokens."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            output = io.StringIO()
            with patch.object(a, "api", fake), contextlib.redirect_stdout(output):
                a.migrate(p, "apply")
                writes = len(fake.writes)
                a.migrate(p, "check")
                a.migrate(p, "apply")
            assert writes == len(fake.writes)
            assert "unit-machine-token" not in output.getvalue()
            assert "unit-old-token" not in output.getvalue()
            assert fake.users[0]["uuid"] == a.OWNER_UUID
            assert not any(m == "DELETE" for m, _, _ in fake.writes)
            assert (
                json.loads((p / "credentials.json").read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
                == BOOTSTRAP_CREDENTIAL
            )
            assert (p / "automation-api.json").stat().st_mode & 63 == 0
            before = list(p.glob("credentials-before-automation-*.json"))
            assert len(before) == 1
            assert (
                json.loads(before[0].read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
                == PREVIOUS_CREDENTIAL
            )

    def test_check_without_migration_does_not_write(self) -> None:
        """A check-only migration performs no API calls or file writes."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            with (
                patch.object(a, "api") as api,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                a.migrate(p, "check")
            api.assert_not_called()
            assert not (p / "automation-api.json").exists()

    def test_foreign_account_refused(self) -> None:
        """A foreign account with the automation name is refused."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            fake.users.append({"username": a.NAME})
            with patch.object(a, "api", fake), pytest.raises(RuntimeError):
                a.migrate(p, "apply")
            assert fake.writes == []

    def test_wrong_owner_uuid_refused(self) -> None:
        """Owner accounts with an unreviewed UUID are refused."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            fake.users[0]["uuid"] = "different-owner"
            with patch.object(a, "api", fake), pytest.raises(RuntimeError):
                a.migrate(p, "apply")
            assert fake.writes == []

    def test_alias_drift_refused(self) -> None:
        """Drifted bootstrap alias credentials abort on the next check."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            with (
                patch.object(a, "api", fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                a.migrate(p, "apply")
            a.save(p / "credentials.json", {"AUTHENTIK_BOOTSTRAP_TOKEN": "other"})
            with patch.object(a, "api", fake), pytest.raises(RuntimeError):
                a.migrate(p, "check")

    def bootstrap(self, p) -> BootstrapManifest:
        """Run bootstrap.py against a patched kubectl and return its manifest."""
        with (
            patch("sys.argv", ["bootstrap.py", str(p)]),
            patch("subprocess.run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runpy.run_path(str(FILES / "bootstrap.py"), run_name="__main__")
        return cast("BootstrapManifest", json.loads(run.call_args.kwargs["input"]))

    def test_runtime_excludes_admin_secrets_after_migration(self) -> None:
        """Post-migration manifests exclude bootstrap token and password."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            a.save(
                p / "automation-api.json",
                {"status": "active", "token": "unit-old-token"},
            )
            manifest = self.bootstrap(p)["stringData"]
            assert "AUTHENTIK_BOOTSTRAP_TOKEN" not in manifest
            assert "AUTHENTIK_BOOTSTRAP_PASSWORD" not in manifest
            assert manifest["AUTHENTIK_SECRET_KEY"] == SIGNING_KEY

    def test_fresh_install_still_has_initial_bootstrap(self) -> None:
        """Fresh installs still seed the initial bootstrap token."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            assert "AUTHENTIK_BOOTSTRAP_TOKEN" in self.bootstrap(p)["stringData"]

    def test_incomplete_journal_refuses_secret_apply(self) -> None:
        """A preparing journal blocks secret application entirely."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            a.save(p / "automation-api.json", {"status": "preparing"})
            with pytest.raises(SystemExit):
                self.bootstrap(p)

    def ready_retirement(self, p, fake) -> None:
        """Complete migration and record recovery evidence for retirement."""
        with patch.object(a, "api", fake), contextlib.redirect_stdout(io.StringIO()):
            a.migrate(p, "apply")
        j = json.loads((p / "automation-api.json").read_text())
        j["recovery_evidence"] = {
            "fixture_admin_session_verified": True,
            "fixture_cleanup_verified": True,
            "owner_uuid": a.OWNER_UUID,
        }
        j["encrypted_backup_sha256"] = "unit-digest"
        a.save(p / "automation-api.json", j)
        (p / "bootstrap.py").write_text((FILES / "bootstrap.py").read_text())

    def kube_read(self, args, **_kwargs):
        """Fake kubectl reads returning an empty secret or deployment."""
        if "secret" in args:
            return json.dumps({"data": {}, "metadata": {"annotations": {}}}).encode()
        return json.dumps({"spec": {"template": {"spec": {"containers": [{"env": []}]}}}}).encode()

    def test_retirement_requires_recovery_and_backup(self) -> None:
        """Retirement without recovery evidence deletes nothing."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            with (
                patch.object(a, "api", fake),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                a.migrate(p, "apply")
            with (
                patch.object(a, "api", fake),
                contextlib.redirect_stdout(io.StringIO()),
                pytest.raises(RuntimeError),
            ):
                a.retire_default_admin(p)
            assert not any(m == "DELETE" for m, _, _ in fake.writes)

    def test_retirement_refuses_different_default_admin_uuid(self) -> None:
        """An unreviewed default-admin UUID blocks retirement."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            self.ready_retirement(p, fake)
            fake.users.append({"pk": 4, "username": "akadmin", "uuid": "not-reviewed"})
            with (
                patch.object(a, "api", fake),
                patch("subprocess.check_output", self.kube_read),
                contextlib.redirect_stdout(io.StringIO()),
                pytest.raises(RuntimeError),
            ):
                a.retire_default_admin(p)
            assert not any(m == "DELETE" for m, _, _ in fake.writes)

    def test_retirement_refuses_runtime_bootstrap_secret(self) -> None:
        """A live runtime bootstrap secret blocks retirement."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            self.ready_retirement(p, fake)
            secret = json.dumps(
                {"data": {"AUTHENTIK_BOOTSTRAP_TOKEN": "unit-old"}, "metadata": {}}
            ).encode()
            with (
                patch.object(a, "api", fake),
                patch("subprocess.check_output", return_value=secret),
                contextlib.redirect_stdout(io.StringIO()),
                pytest.raises(RuntimeError),
            ):
                a.retire_default_admin(p)
            assert not any(m == "DELETE" for m, _, _ in fake.writes)

    def test_retirement_exact_identity_and_idempotence(self) -> None:
        """Verified retirement removes exactly the default admin, idempotently."""
        with tempfile.TemporaryDirectory() as d:
            p = self.root(d)
            fake = Fake()
            self.ready_retirement(p, fake)
            fake.users.append(
                {
                    "pk": 4,
                    "username": "akadmin",
                    "uuid": "fc86d87d-3a72-4cfb-8ba1-aa6bf6b017e7",
                }
            )
            fake.tokens.append({"identifier": "authentik-bootstrap-token", "user": 4})
            with (
                patch.object(a, "api", fake),
                patch("subprocess.check_output", self.kube_read),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                a.retire_default_admin(p)
                a.retire_default_admin(p)
            assert [(m, path) for m, path, _ in fake.writes if m == "DELETE"] == [
                ("DELETE", "core/users/4/")
            ]
            assert any(t["identifier"] == a.NAME for t in fake.tokens)
            assert "AUTHENTIK_BOOTSTRAP_PASSWORD" not in json.loads(
                (p / "credentials.json").read_text()
            )


if __name__ == "__main__":
    unittest.main()


def test_bootstrap_source_guard_accepts_formatting_not_decoy_text() -> None:
    """Accept the real recipe independently of layout; reject comments/strings."""
    source = (FILES / "bootstrap.py").read_text()
    assert a.bootstrap_is_migration_aware(source)
    assert a.bootstrap_is_migration_aware(ast.unparse(ast.parse(source)))
    assert not a.bootstrap_is_migration_aware("# " + repr(source))
    assert not a.bootstrap_is_migration_aware("example = " + repr(source))
    assert not a.bootstrap_is_migration_aware("def invalid(:")
    assert not a.bootstrap_is_migration_aware(" " * 1_048_577)


def test_bootstrap_refusal_cannot_execute_an_extra_call() -> None:
    """Keep the abort path free of effects before it exits."""
    source = (FILES / "bootstrap.py").read_text()
    assert a.bootstrap_is_migration_aware(source)
    refusal = "        raise SystemExit(msg)\n    for key in"
    assert source.count(refusal) == 1
    changed = source.replace(refusal, "        unexpected_call()\n" + refusal)
    assert not a.bootstrap_is_migration_aware(changed)


@pytest.mark.parametrize(
    "mutation",
    ["password-key", "removal", "guard", "refusal", "journal", "manifest", "order"],
)
def test_bootstrap_source_guard_rejects_real_boundary_mutations(mutation: str) -> None:
    """Reject changes that would reintroduce administrative runtime credentials."""
    source = (FILES / "bootstrap.py").read_text()
    assert a.bootstrap_is_migration_aware(source)
    tree = ast.parse(source)
    conditional = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "automation_path.exists()"
    )
    load, guard, removal = conditional.body
    if mutation == "password-key":
        removal.iter.elts.pop()
    elif mutation == "removal":
        removal.body = [ast.Pass()]
    elif mutation == "guard":
        guard.test = ast.Constant(False)
    elif mutation == "refusal":
        guard.body = [ast.Pass()]
    elif mutation == "journal":
        load.value = ast.Constant(None)
    elif mutation == "manifest":
        manifest = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "manifest" for target in node.targets
            )
        )
        for index, key in enumerate(manifest.value.keys):
            if isinstance(key, ast.Constant) and key.value == "stringData":
                manifest.value.values[index] = ast.Name(id="values", ctx=ast.Load())
    elif mutation == "order":
        tree.body.remove(conditional)
        tree.body.append(conditional)
    changed = ast.unparse(ast.fix_missing_locations(tree))
    assert ast.dump(ast.parse(source)) != ast.dump(ast.parse(changed))
    assert not a.bootstrap_is_migration_aware(changed)
