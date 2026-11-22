"""Source contracts for the WireGuard admin client role."""

import unittest
from pathlib import Path

import yaml

ROLE = Path(__file__).resolve().parents[1] / "ansible/roles/wireguard_admin_client"
TASKS = (ROLE / "tasks/main.yml").read_text()
DEFAULTS = (ROLE / "defaults/main.yml").read_text()

MIN_PRIVILEGED_TASKS = 4
MIN_DNS_TAGGED_TASKS = 4
TEMPLATE = (ROLE / "templates/wg-socrat-admin.conf.j2").read_text()
ROLLBACK = (ROLE / "ROLLBACK.md").read_text()


class WireGuardAdminClientTests(unittest.TestCase):
    """Pinned profile, key, peer, and DNS contracts for the admin client."""

    def test_profile_has_three_direct_peers_and_exact_endpoints(self) -> None:
        """Require one peer block, keepalive, and the three direct endpoints."""
        assert TEMPLATE.count("[Peer]") == 1
        assert "{% for peer in wireguard_admin_peers %}" in TEMPLATE
        assert (
            'AllowedIPs = {{ peer.allowed_ips | default([peer.address + "/32"]) | join(", ") }}'
            in TEMPLATE
        )
        assert "PersistentKeepalive = {{ wireguard_admin_keepalive }}" in TEMPLATE
        for endpoint in ("109.173.40.247:51830", "109.173.40.247:51831", "109.120.141.60:51830"):
            assert endpoint in DEFAULTS

    def test_profile_does_not_capture_dns(self) -> None:
        """Keep DNS and full-tunnel routes out of the admin profile."""
        assert "DNS" not in TEMPLATE
        assert "0.0.0.0/0" not in TEMPLATE

    def test_private_key_is_generated_and_managed_without_logging(self) -> None:
        """Require local key generation, mode 0600, and no_log on key tasks."""
        tasks = {task["name"]: task for task in yaml.safe_load(TASKS)}
        assert tasks["Generate Mac private key"]["ansible.builtin.command"] == "wg genkey"
        derive = tasks["Derive Mac public key"]
        assert derive["ansible.builtin.command"] == "wg pubkey"
        assert derive["args"]["stdin"] == "{{ wireguard_admin_private_key }}\n"
        assert "ansible.builtin.shell:" not in TASKS
        for name, module in (
            ("Save generated Mac private key", "ansible.builtin.copy"),
            ("Enforce Mac private key permissions", "ansible.builtin.file"),
            ("Render WireGuard Mac profile", "ansible.builtin.template"),
        ):
            assert tasks[name][module]["mode"] == "0600"
        for name in (
            "Generate Mac private key",
            "Save generated Mac private key",
            "Enforce Mac private key permissions",
            "Read Mac private key",
            "Normalize Mac private key fact",
            "Derive Mac public key",
            "Render WireGuard Mac profile",
        ):
            assert tasks[name]["no_log"] is True
        assert "wg_socrat_nodes" in DEFAULTS

    def test_peer_defaults_are_distinct_bare_addresses_and_keys_come_from_inventory(self) -> None:
        """Require bare peer addresses and inventory-sourced public keys."""
        assert "item.address is match" in TASKS
        assert "item.address is not search('/')" in TASKS
        assert "public_key is match" in TASKS
        assert "public_key | length > 0" in TASKS
        for name in ("socrat-0", "socrat-1", "socrat-2"):
            assert f"get('{name}', {{}}).get('public_key', '')" in DEFAULTS

    def test_dns_is_privileged_and_scoped_to_dns_tag(self) -> None:
        """Keep resolver edits privileged, dns-tagged, and covered by rollback."""
        assert TASKS.count("become: true") >= MIN_PRIVILEGED_TASKS
        assert TASKS.count("tags: dns") >= MIN_DNS_TAGGED_TASKS
        for resolver in (
            "0.socrat.alchemmist.xyz",
            "1.socrat.alchemmist.xyz",
            "2.socrat.alchemmist.xyz",
        ):
            assert resolver in TASKS
        assert "/etc/resolv.conf" in ROLLBACK
        assert "unrelated files" in ROLLBACK


if __name__ == "__main__":
    unittest.main()
