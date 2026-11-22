"""Tests for the Grafana MCP credential bootstrap."""

import base64
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "ansible/roles/grafana_mcp/files/bootstrap_credentials.py"
)
SPEC = importlib.util.spec_from_file_location("bootstrap_credentials", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def secret(**values: str) -> dict[str, dict[str, str]]:
    """Build a Kubernetes secret shape with base64-encoded data fields."""
    return {
        "data": {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}
    }


class CredentialsTests(unittest.TestCase):
    """Validate Grafana MCP service-account credential handling."""

    def test_existing_valid_secret_is_preserved(self) -> None:
        """Keep a valid committed secret without persisting anything."""
        grafana = Mock()
        grafana.request.side_effect = [
            {"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]},
            {"id": 1},
        ]
        persist = Mock()
        result = MODULE.bootstrap(
            grafana,
            secret(
                **{
                    "grafana-token": "existing",
                    "client-token": "client",
                    "service-account-id": "12",
                }
            ),
            persist,
        )
        self.assertEqual(result, {"changed": False})
        persist.assert_not_called()
        self.assertEqual(grafana.request.call_args.kwargs["token"], "existing")

    def test_existing_secret_does_not_require_admin(self) -> None:
        """Verify an existing secret with a plain, non-admin token probe."""
        grafana = Mock()
        persist = Mock()
        result = MODULE.bootstrap(
            grafana,
            secret(
                **{
                    "grafana-token": "existing",
                    "client-token": "client",
                    "service-account-id": "12",
                }
            ),
            persist,
            has_admin=False,
        )
        self.assertFalse(result["changed"])
        grafana.request.assert_called_once_with("GET", "/api/org", token="existing")
        persist.assert_not_called()

    def test_creation_uses_viewer_and_distinct_credentials(self) -> None:
        """Create a Viewer account with independent client and server tokens."""
        grafana = Mock()
        grafana.request.side_effect = [
            {"serviceAccounts": []},
            {"id": 12},
            {"id": 7, "key": "grafana-secret"},
            {"id": 1},
        ]
        persist = Mock()
        self.assertTrue(MODULE.bootstrap(grafana, None, persist)["changed"])
        self.assertEqual(grafana.request.call_args_list[1].args[2]["role"], "Viewer")
        data = persist.call_args.args[0]["stringData"]
        self.assertEqual(data["grafana-token"], "grafana-secret")
        self.assertNotEqual(data["client-token"], data["grafana-token"])
        self.assertGreaterEqual(len(data["client-token"]), 64)

    def test_failed_persistence_revokes_only_new_token(self) -> None:
        """Revoke the freshly created token when persistence fails."""
        grafana = Mock()
        grafana.request.side_effect = [
            {"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]},
            {"id": 7, "key": "secret"},
            {},
            {},
        ]
        with self.assertRaisesRegex(MODULE.BootstrapError, "newly created token revoked"):
            MODULE.bootstrap(grafana, None, Mock(side_effect=RuntimeError("secret")))
        grafana.request.assert_called_with("DELETE", "/api/serviceaccounts/12/tokens/7")

    def test_token_replacement_preserves_client_token(self) -> None:
        """Rotate only the server token and keep the client token stable."""
        grafana = Mock()
        grafana.request.side_effect = [
            {"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]},
            MODULE.BootstrapError("expired"),
            {"id": 8, "key": "replacement"},
            {},
        ]
        persist = Mock()
        MODULE.bootstrap(
            grafana,
            secret(
                **{
                    "grafana-token": "old",
                    "client-token": "stable",
                    "service-account-id": "12",
                }
            ),
            persist,
        )
        self.assertEqual(persist.call_args.args[0]["stringData"]["client-token"], "stable")

    def test_disabled_account_is_not_reenabled(self) -> None:
        """Refuse to re-enable a disabled service account."""
        grafana = Mock()
        grafana.request.return_value = {
            "serviceAccounts": [
                {"id": 12, "name": "socrat-mcp", "role": "Viewer", "isDisabled": True}
            ]
        }
        persist = Mock()
        with self.assertRaisesRegex(MODULE.BootstrapError, "disabled"):
            MODULE.bootstrap(grafana, None, persist)
        persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
