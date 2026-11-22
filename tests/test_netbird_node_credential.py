"""Tests for the NetBird node credential helper script."""

import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "credential", ROOT / "scripts/netbird-node-credential.py"
)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CredentialTest(unittest.TestCase):
    """Exercise NetBird node credential renewal against a fake runtime."""

    def setup_runtime(
        self, folder, days
    ) -> tuple[type, list[tuple[str, str]], list[dict[str, object]]]:
        """Install a fixture credential and build a patched API runtime."""
        old = {
            "user_id": "service-id",
            "token_id": "old-id",
            "token": "fixture-old",
            "expiration_date": (dt.datetime.now(dt.UTC) + dt.timedelta(days=days)).isoformat(),
        }
        c.mod.atomic(folder / "credential.json", old)
        calls: list[tuple[str, str]] = []
        users: list[dict[str, object]] = [
            {
                "id": "service-id",
                "name": c.mod.SERVICE,
                "role": "admin",
                "is_service_user": True,
                "is_blocked": False,
            }
        ]

        class Runtime:
            def __init__(self, root, config) -> None:
                self.auth = dict(old)

            def api(self, method, path, _body=None):
                calls.append((method, path))
                if method == "GET":
                    return users
                if method == "POST":
                    return {
                        "plain_token": "fixture-new",
                        "personal_access_token": {
                            "id": "new-id",
                            "expiration_date": (
                                dt.datetime.now(dt.UTC) + dt.timedelta(days=365)
                            ).isoformat(),
                        },
                    }
                if method == "DELETE":
                    # On-disk new credential is verified and committed before old revocation.
                    assert (
                        json.loads((folder / "credential.json").read_text())["token_id"] == "new-id"
                    )

        return Runtime, calls, users

    def test_valid_long_lived_token_does_not_rotate_each_run(self) -> None:
        """A valid long-lived token is not rotated on every run."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            runtime, calls, users = self.setup_runtime(folder, 300)
            with patch.object(c.mod, "Runtime", runtime):
                assert not c.renew(folder, {})
            assert calls == [("GET", "users")]

    def test_renew_verify_atomic_switch_then_revoke_old(self) -> None:
        """Renewal verifies, switches atomically, then revokes the old token."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            runtime, calls, users = self.setup_runtime(folder, 10)
            with patch.object(c.mod, "Runtime", runtime):
                assert c.renew(folder, {})
            assert [method for method, path in calls] == [
                "GET",
                "POST",
                "GET",
                "DELETE",
            ]
            assert not (folder / "credential-intent.json").exists()
            owner_only_mode = 0o600
            assert (folder / "credential.json").stat().st_mode & 511 == owner_only_mode

    def test_human_blocked_or_lowered_account_not_repaired(self) -> None:
        """Human, blocked or lowered accounts are never repaired."""
        for field, value in [
            ("is_service_user", False),
            ("is_blocked", True),
            ("role", "user"),
        ]:
            with tempfile.TemporaryDirectory() as t:
                folder = Path(t)
                runtime, calls, users = self.setup_runtime(folder, 10)
                users[0][field] = value
                with (
                    patch.object(c.mod, "Runtime", runtime),
                    self.assertRaises(ValueError),
                ):
                    c.renew(folder, {})
                assert calls == [("GET", "users")]

    def test_uncertain_issuance_never_retries(self) -> None:
        """An uncertain issuance never retries."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            (folder / "credential-intent.json").write_text("{}")
            with self.assertRaises(ValueError):
                c.renew(folder, {})

    def test_missing_credential_needs_explicit_bootstrap(self) -> None:
        """A missing credential requires explicit bootstrap."""
        with tempfile.TemporaryDirectory() as t, self.assertRaises(ValueError):
            c.renew(Path(t), {})
