"""Tests for the wiki runtime bootstrap module."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location(
    "bootstrap",
    Path(__file__).resolve().parents[1] / "scripts/bootstrap-wiki-runtime.py",
)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


class BootstrapTests(unittest.TestCase):
    """Tests for BootstrapTests."""

    def setUp(self) -> None:
        self.resources = {
            ("secret", "wiki-editor-git", "wiki"): {
                "data": {"id_ed25519": BOOTSTRAP.encoded("private fixture")}
            },
            ("configmap", "wiki-editor-hosts", "wiki"): {
                "data": {"known_hosts": "github.com fixture"}
            },
        }
        self.kube = Mock()
        self.kube.get.side_effect = lambda *key: self.resources.get(key)

    def test_creates_only_isolated_resources_without_registry_credentials(self) -> None:
        messages = BOOTSTRAP.bootstrap(self.kube)
        all_created = [call.args[0] for call in self.kube.create.call_args_list]
        assert [item["kind"] for item in all_created] == [
            "Namespace",
            "PersistentVolumeClaim",
            "Secret",
            "Secret",
        ]
        assert [item["metadata"]["name"] for item in all_created] == [
            "wiki",
            "wiki-runtime-data",
            "wiki-runtime-bootstrap",
            "wiki-runtime-git",
        ]
        assert all_created[1]["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
        assert BOOTSTRAP.decoded(all_created[3]["data"]["known_hosts"]) == "github.com fixture"
        assert not any(
            item["kind"] in {"ServiceAccount", "Role", "RoleBinding"} for item in all_created
        )
        assert not any(
            "clusters.fleet.cattle.io" in call.args
            or "ghcr-pull" in call.args
            or "wiki-runtime-registry" in call.args
            for call in self.kube.get.call_args_list
        )
        assert "token:with:colons" not in str(messages)

    def test_repeated_run_never_rotates_bootstrap_or_existing_resources(self) -> None:
        BOOTSTRAP.bootstrap(self.kube)
        for call in self.kube.create.call_args_list:
            item = call.args[0]
            kind = item["kind"].lower()
            self.resources[
                kind,
                item["metadata"]["name"],
                item["metadata"].get("namespace", "wiki"),
            ] = item
        original = self.resources["secret", "wiki-runtime-bootstrap", "wiki"]["data"]["token"]
        self.kube.create.reset_mock()
        BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()
        assert (
            self.resources["secret", "wiki-runtime-bootstrap", "wiki"]["data"]["token"] == original
        )

    def test_clean_install_can_skip_legacy_git(self) -> None:
        del self.resources["secret", "wiki-editor-git", "wiki"]
        del self.resources["configmap", "wiki-editor-hosts", "wiki"]
        messages = BOOTSTRAP.bootstrap(self.kube, skip_legacy_git=True)
        assert "wiki/wiki-runtime-git: skipped" in messages
        names = [call.args[0]["metadata"]["name"] for call in self.kube.create.call_args_list]
        assert "wiki-runtime-git" not in names

    def test_missing_sources_fail_before_any_creation(self) -> None:
        del self.resources["configmap", "wiki-editor-hosts", "wiki"]
        with self.assertRaises(BOOTSTRAP.BootstrapError):
            BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()

    def test_invalid_existing_bootstrap_is_not_overwritten(self) -> None:
        self.resources["secret", "wiki-runtime-bootstrap", "wiki"] = {
            "data": {"token": BOOTSTRAP.encoded("short")}
        }
        with self.assertRaises(BOOTSTRAP.BootstrapError):
            BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
