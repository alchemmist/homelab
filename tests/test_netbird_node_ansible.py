"""Offline source contracts for NetBird node onboarding in Ansible."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class NodeAnsibleTest(unittest.TestCase):
    """Read committed Ansible source and keep NetBird onboarding explicit."""

    def test_baseline_and_membership_playbooks_include_onboarding(self) -> None:
        """Require the node role in every baseline and membership playbook."""
        for name in [
            "base.yml",
            "site.yml",
            "k3s-worker.yml",
            "k3s-ha.yml",
            "netbird-nodes.yml",
        ]:
            plays = yaml.safe_load((ROOT / "ansible/playbooks" / name).read_text())
            assert any("netbird_node" in p.get("roles", []) for p in plays), name

    def test_controller_connection_is_strict_and_outside_node_group(self) -> None:
        """Keep the controller host strict, ungrouped, and token-free by default."""
        v = yaml.safe_load((ROOT / "ansible/inventory/netbird-controller.yml").read_text())
        assert "children" not in v["all"]
        connection = v["all"]["hosts"]["netbird-controller"]
        assert connection["ansible_host"] == "109.173.40.247"
        assert "StrictHostKeyChecking=yes" in connection["ansible_ssh_common_args"]
        assert "HostKeyAlias=" in connection["ansible_ssh_common_args"]
        defaults = yaml.safe_load(
            (ROOT / "ansible/roles/netbird_node/defaults/main.yml").read_text()
        )
        assert defaults["netbird_node_enabled"]
        assert defaults["netbird_node_controller"] == "netbird-controller"
        assert defaults["netbird_node_bootstrap_token_file"] == ""
        assert defaults["netbird_node_adopt_state"] == ""

    def test_inventory_scope_not_limited_to_one_requested_host(self) -> None:
        """Keep the node inventory template on the full Socrat group."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/netbird_node/tasks/main.yml").read_text())[0][
            "block"
        ]
        template = next(
            t["ansible.builtin.copy"]["content"]
            for t in tasks
            if t.get("ansible.builtin.copy", {}).get("dest", "").endswith("/inventory.json")
        )
        assert "groups['Socrat']" in template
        assert "ansible_play_hosts" not in template
        assert "reserved_addresses" in template
        assert "wg_socrat_admin_clients" in template
        cfg = (ROOT / "ansible/ansible.cfg").read_text()
        assert "inventory/hosts.yml" in cfg
        assert "inventory/netbird-controller.yml" in cfg

    def test_token_timer_is_not_permission_replay(self) -> None:
        """Bind the credential timer to the credential unit and keep it secret."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/netbird_node/tasks/main.yml").read_text())[0][
            "block"
        ]
        service = next(
            t["ansible.builtin.copy"]["content"]
            for t in tasks
            if t.get("ansible.builtin.copy", {}).get("dest", "").endswith("credential.service")
        )
        assert "netbird-node-credential.py" in service
        assert "netbird-node-reconcile.py" not in service
        assert "ProtectSystem=strict" in service
        credential = next(t for t in tasks if t.get("no_log"))
        assert credential["no_log"]
