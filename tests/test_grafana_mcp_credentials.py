import base64
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "ansible/roles/grafana_mcp/files/bootstrap_credentials.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_credentials", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def secret(**values):
    return {"data": {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}}


class CredentialsTests(unittest.TestCase):
    def test_existing_valid_secret_is_preserved(self):
        grafana = Mock()
        grafana.request.side_effect = [{"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]}, {"id": 1}]
        persist = Mock()
        result = MODULE.bootstrap(grafana, secret(**{"grafana-token": "existing", "client-token": "client", "service-account-id": "12"}), persist)
        self.assertEqual(result, {"changed": False})
        persist.assert_not_called()
        self.assertEqual(grafana.request.call_args.kwargs["token"], "existing")

    def test_existing_secret_does_not_require_admin(self):
        grafana = Mock()
        persist = Mock()
        result = MODULE.bootstrap(grafana, secret(**{"grafana-token": "existing", "client-token": "client", "service-account-id": "12"}), persist, has_admin=False)
        self.assertFalse(result["changed"])
        grafana.request.assert_called_once_with("GET", "/api/org", token="existing")
        persist.assert_not_called()

    def test_creation_uses_viewer_and_distinct_credentials(self):
        grafana = Mock()
        grafana.request.side_effect = [{"serviceAccounts": []}, {"id": 12}, {"id": 7, "key": "grafana-secret"}, {"id": 1}]
        persist = Mock()
        self.assertTrue(MODULE.bootstrap(grafana, None, persist)["changed"])
        self.assertEqual(grafana.request.call_args_list[1].args[2]["role"], "Viewer")
        data = persist.call_args.args[0]["stringData"]
        self.assertEqual(data["grafana-token"], "grafana-secret")
        self.assertNotEqual(data["client-token"], data["grafana-token"])
        self.assertGreaterEqual(len(data["client-token"]), 64)

    def test_failed_persistence_revokes_only_new_token(self):
        grafana = Mock()
        grafana.request.side_effect = [{"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]}, {"id": 7, "key": "secret"}, {}, {}]
        with self.assertRaisesRegex(MODULE.BootstrapError, "newly created token revoked"):
            MODULE.bootstrap(grafana, None, Mock(side_effect=RuntimeError("secret")))
        grafana.request.assert_called_with("DELETE", "/api/serviceaccounts/12/tokens/7")

    def test_token_replacement_preserves_client_token(self):
        grafana = Mock()
        grafana.request.side_effect = [{"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer"}]}, MODULE.BootstrapError("expired"), {"id": 8, "key": "replacement"}, {}]
        persist = Mock()
        MODULE.bootstrap(grafana, secret(**{"grafana-token": "old", "client-token": "stable", "service-account-id": "12"}), persist)
        self.assertEqual(persist.call_args.args[0]["stringData"]["client-token"], "stable")

    def test_disabled_account_is_not_reenabled(self):
        grafana = Mock()
        grafana.request.return_value = {"serviceAccounts": [{"id": 12, "name": "socrat-mcp", "role": "Viewer", "isDisabled": True}]}
        persist = Mock()
        with self.assertRaisesRegex(MODULE.BootstrapError, "disabled"):
            MODULE.bootstrap(grafana, None, persist)
        persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
