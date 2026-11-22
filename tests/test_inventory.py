"""Local inventory contracts; these tests never connect to managed hosts."""

import configparser
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import TypedDict, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
NODES = {f"socrat-{i}" for i in range(6)}


class SocratGroup(TypedDict):
    """Resolved socrat group with its host map."""

    hosts: dict[str, object]


class InventoryMeta(TypedDict):
    """Per-host resolved variables."""

    hostvars: dict[str, dict[str, object]]


class ResolvedInventory(TypedDict):
    """Shape produced by ansible-inventory --list."""

    Socrat: SocratGroup
    _meta: InventoryMeta


class InventoryStructureTests(unittest.TestCase):
    """Check the main inventory's structure and connection settings."""

    def test_main_inventory_contains_every_node_and_only_connection_settings(
        self,
    ) -> None:
        """Map every node with connection-only settings once."""
        inventory = yaml.safe_load((ANSIBLE / "inventory/hosts.yml").read_text())
        hosts = inventory["all"]["children"]["Socrat"]["hosts"]
        assert set(hosts) == NODES
        for host, settings in hosts.items():
            assert all(key.startswith("ansible_") for key in settings), host
            assert (ANSIBLE / "inventory/host_vars" / f"{host}.yml").is_file()

    def test_default_connections_are_internal_without_bastions(self) -> None:
        """Pin the internal addresses and ports with no bastion jumps."""
        hosts = yaml.safe_load((ANSIBLE / "inventory/hosts.yml").read_text())["all"]["children"][
            "Socrat"
        ]["hosts"]
        addresses = {
            "socrat-0": "10.250.0.1",
            "socrat-1": "10.250.0.3",
            "socrat-2": "10.250.0.2",
            "socrat-3": "10.250.0.5",
        }
        for name, address in addresses.items():
            assert hosts[name]["ansible_host"] == address
            assert hosts[name]["ansible_port"] == 2222
            assert "ProxyJump=none" in hosts[name]["ansible_ssh_common_args"]
            assert "HostKeyAlias=" in hosts[name]["ansible_ssh_common_args"]

    def test_default_sources_are_explicit_not_the_whole_inventory_directory(
        self,
    ) -> None:
        """List both inventory sources explicitly in ansible.cfg."""
        config = configparser.ConfigParser()
        config.read(ANSIBLE / "ansible.cfg")
        assert [s.strip() for s in config["defaults"]["inventory"].split(",")] == [
            "inventory/hosts.yml",
            "inventory/netbird-controller.yml",
        ]
        assert not (ANSIBLE / "inventory/socrat-3.yml").exists()


@unittest.skipUnless(shutil.which("ansible-inventory"), "ansible-inventory is required")
class ResolvedInventoryTests(unittest.TestCase):
    def inventory(self, *sources: str) -> ResolvedInventory:
        """Run ansible-inventory --list over the explicit sources passed in."""
        command = ["ansible-inventory"]
        for source in sources:
            command += ["-i", f"inventory/{source}.yml"]
        result = subprocess.run(
            [*command, "--list"],
            cwd=ANSIBLE,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return cast("ResolvedInventory", json.loads(result.stdout))

    def test_default_and_explicit_main_inventory_include_all_nodes(self) -> None:
        """Resolve every node from either source combination unchanged."""
        for sources in [(), ("hosts",)]:
            with self.subTest(sources=sources):
                data = self.inventory(*sources)
                assert set(data["Socrat"]["hosts"]) == NODES
                host = data["_meta"]["hostvars"]["socrat-3"]
                assert host["ansible_host"] == "10.250.0.5"
                assert host["ansible_port"] == 2222
                assert host["homelab_boot_k3s_service"] == "k3s-agent.service"
                assert host["k3s_worker_swap_enabled"]
        assert "netbird-controller" not in data["Socrat"]["hosts"]
        assert "netbird-controller" in self.inventory()["_meta"]["hostvars"]

    def test_connection_overlays_still_override_main_inventory(self) -> None:
        """Apply the committed overlay connections on top of the main map."""
        for overlay, expected in {
            "direct": {
                "socrat-0": ("192.168.0.23", 22),
                "socrat-1": ("192.168.0.24", 2222),
                "socrat-2": ("109.120.141.60", 22),
            },
            "lan": {
                "socrat-0": ("192.168.0.23", 2222),
                "socrat-1": ("192.168.0.24", 2222),
            },
        }.items():
            with self.subTest(overlay=overlay):
                data = self.inventory("hosts", overlay)
                assert set(data["Socrat"]["hosts"]) == NODES
                for node, connection in expected.items():
                    host = data["_meta"]["hostvars"][node]
                    assert (host["ansible_host"], host["ansible_port"]) == connection
                assert data["_meta"]["hostvars"]["socrat-3"]["ansible_host"] == "10.250.0.5"


if __name__ == "__main__":
    unittest.main()
