"""Tests for the k3s role rebalance configuration script."""

import argparse
import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from typing import cast, override

import pytest
import yaml

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "ansible/roles/k3s_role_rebalance/files/configure_role.py"
)
SPEC = importlib.util.spec_from_file_location("configure_role", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RoleConfigTests(unittest.TestCase):
    """Contracts for the k3s role rebalance configurator."""

    @override
    def setUp(self) -> None:
        """Build the standard server-role argument namespace per test."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.yaml"
        self.args = argparse.Namespace(
            config=str(self.path),
            role="server",
            node_name="socrat-3",
            node_ip="10.250.0.5",
            advertise_ip="10.250.0.5",
            server="https://10.250.0.1:6443",
            token_file="/etc/rancher/k3s/token",
            check=False,
        )

    def write(self, value: object) -> None:
        """Dump one YAML document to the config path with private permissions."""
        self.path.write_text(yaml.safe_dump(value))
        self.path.chmod(0o600)

    def read(self) -> dict[str, object]:
        """Load the config path as a plain mapping."""
        return cast("dict[str, object]", yaml.safe_load(self.path.read_text()))

    def test_promote_preserves_worker_settings(self) -> None:
        """Promote to server while preserving worker tuning and existing SANs."""
        preserved = {
            "prefer-bundled-bin": True,
            "node-label": ["workload=llm"],
            "kubelet-arg": ["eviction-hard=memory.available<100Mi"],
            "node-taint": ["dedicated=llm:NoSchedule"],
            "disable": ["servicelb"],
        }
        self.write(
            dict(
                preserved,
                **{
                    "disable-etcd": True,
                    "cluster-init": True,
                    "tls-san": ["existing.example"],
                },
            )
        )
        result = MODULE.configure(self.args)
        assert result["changed"]
        actual = self.read()
        for key, value in preserved.items():
            assert actual[key] == value
        assert "disable-etcd" not in actual
        assert "cluster-init" not in actual
        assert actual["tls-san"] == ["existing.example", "10.250.0.5", "127.0.0.1"]
        assert actual["token-file"] == self.args.token_file
        assert actual["flannel-iface"] == "wg-socrat"

    def test_explicit_token_file_replaces_inline_token_only(self) -> None:
        """Replace an inline token with the explicit token file only."""
        self.write(
            {
                "token": "old-agent-token",
                "token-file": "/old/token",
                "disable-agent": False,
                "node-label": ["a=b"],
            }
        )
        MODULE.configure(self.args)
        actual = self.read()
        assert "token" not in actual
        assert actual["token-file"] == self.args.token_file
        assert not actual["disable-agent"]
        assert actual["node-label"] == ["a=b"]

    def test_control_plane_removes_conflicting_flags(self) -> None:
        """Strip server-role flags that conflict with control-plane membership."""
        self.write(
            dict.fromkeys(
                (
                    "cluster-init",
                    "disable-apiserver",
                    "disable-controller-manager",
                    "disable-scheduler",
                ),
                True,
            )
        )
        self.args.role = "control-plane"
        MODULE.configure(self.args)
        actual = self.read()
        assert actual["disable-etcd"]
        for key in (
            "cluster-init",
            "disable-apiserver",
            "disable-controller-manager",
            "disable-scheduler",
        ):
            assert key not in actual

    def test_idempotence_private_backup_and_atomic_permissions(self) -> None:
        """Apply once atomically with a private backup, then no-op."""
        self.write({"node-label": ["a=b"]})
        self.path.chmod(0o644)
        original = self.path.read_bytes()
        first = MODULE.configure(self.args)
        backup = self.path.parent / first["backup"]
        assert backup.read_bytes() == original
        assert stat.S_IMODE(backup.stat().st_mode) == 384
        assert stat.S_IMODE(self.path.stat().st_mode) == 384
        inode = self.path.stat().st_ino
        assert MODULE.configure(self.args) == {"changed": False, "backup": None}
        assert self.path.stat().st_ino == inode
        assert len(list(self.path.parent.glob("*.backup-*"))) == 1
        self.args.node_name = "socrat-1"
        second = MODULE.configure(self.args)
        assert first["backup"] != second["backup"]
        assert backup.read_bytes() == original

    def test_check_does_not_write(self) -> None:
        """Keep check mode free of any config or directory side effects."""
        self.write({"token-file": "/existing/token"})
        self.args.token_file = None
        self.args.check = True
        original = self.path.read_bytes()
        assert MODULE.configure(self.args)["changed"]
        assert self.path.read_bytes() == original
        assert list(self.path.parent.iterdir()) == [self.path]
        self.args.check = False
        MODULE.configure(self.args)
        assert self.read()["token-file"] == "/existing/token"

    def test_rejects_symlink_and_non_mapping(self) -> None:
        """Refuse non-mapping documents and symlinked config paths."""
        self.write(["invalid"])
        with pytest.raises(ValueError):
            MODULE.configure(self.args)
        target = self.path.with_name("target.yaml")
        self.path.rename(target)
        self.path.symlink_to(target)
        with pytest.raises(ValueError):
            MODULE.configure(self.args)


if __name__ == "__main__":
    unittest.main()
