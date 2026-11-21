from pathlib import Path
import unittest
import shlex
import subprocess

from jinja2 import Environment


ROLE = Path(__file__).resolve().parents[1] / "ansible/roles/wireguard_admin_firewall"
TASKS = (ROLE / "tasks/main.yml").read_text()
DEFAULTS = (ROLE / "defaults/main.yml").read_text()
SCRIPT = (ROLE / "templates/wg-socrat-admin-firewall.sh.j2").read_text()
UNIT = (ROLE / "templates/wg-socrat-admin-firewall.service.j2").read_text()
ROLLBACK = (ROLE / "ROLLBACK.md").read_text()


class WireGuardAdminFirewallTests(unittest.TestCase):
    def test_uses_client_registry_and_exact_interface(self):
        assert "wg_socrat_admin_clients" in DEFAULTS
        assert "interface={{ wg_socrat_admin_firewall_interface | quote }}" in SCRIPT
        assert "wg-socrat" in DEFAULTS
        assert "dict2items" in SCRIPT
        assert "item.value.address" in TASKS

    def test_only_allows_ssh_and_private_dns_to_the_node(self):
        assert "--dport {{ wg_socrat_admin_firewall_ssh_port }}" in SCRIPT
        assert "--dport {{ wg_socrat_admin_firewall_dns_port }}" in SCRIPT
        assert "-p tcp" in SCRIPT
        assert "-p udp" in SCRIPT
        assert "NEW,ESTABLISHED" in SCRIPT
        assert "--ctstate RELATED" in SCRIPT
        assert "--ctorigdstport" in SCRIPT
        assert "REJECT --reject-with icmp-port-unreachable" in SCRIPT

    def test_private_web_access_is_explicitly_disabled_by_default(self):
        assert "wireguard_private_web_enabled: false" in DEFAULTS
        assert "{% if wireguard_private_web_enabled | bool %}" in SCRIPT
        assert "--dport {{ wireguard_private_web_proxy_port }}" in SCRIPT
        assert "--ctorigdstport {{ wireguard_private_web_public_port }}" in SCRIPT

    def test_forwarding_from_admin_clients_is_rejected(self):
        assert "FORWARD" in SCRIPT
        assert "REJECT --reject-with icmp-admin-prohibited" in SCRIPT
        assert 'INPUT 1 -i "$interface"' in SCRIPT
        assert 'FORWARD 1 -i "$interface"' in SCRIPT

    def test_preserves_unrelated_firewall_chains(self):
        assert "input_chain_a={{ wg_socrat_admin_firewall_chain_prefix }}_INPUT_A" in SCRIPT
        assert "input_chain_b={{ wg_socrat_admin_firewall_chain_prefix }}_INPUT_B" in SCRIPT
        assert "forward_chain_a={{ wg_socrat_admin_firewall_chain_prefix }}_FORWARD_A" in SCRIPT
        assert "forward_chain_b={{ wg_socrat_admin_firewall_chain_prefix }}_FORWARD_B" in SCRIPT
        assert "ipt -F INPUT" not in SCRIPT
        assert "ipt -F FORWARD" not in SCRIPT
        assert "remove_rules" in SCRIPT
        assert "delete_all" in SCRIPT

    def test_replaces_owned_policy_only_after_new_chain_is_built(self):
        assert '"$iptables" -w 5' in SCRIPT
        assert "new_input_chain" in SCRIPT
        assert "new_forward_chain" in SCRIPT
        assert SCRIPT.index("ipt -I INPUT 1") < SCRIPT.index(
            'delete_all INPUT -i "$interface" -j "$active_input_chain"'
        )
        assert SCRIPT.index('ipt -A "$new_input_chain"') < SCRIPT.index("ipt -I INPUT 1")

    def test_transit_is_scoped_and_nat_is_reversible(self):
        env = Environment()
        env.filters["quote"] = shlex.quote
        env.filters["bool"] = bool
        env.filters["dict2items"] = lambda value: [dict(key=k, value=v) for k, v in value.items()]
        script = env.from_string(SCRIPT).render(
            wg_socrat_admin_firewall_interface="wg-socrat",
            wg_socrat_admin_firewall_chain_prefix="WG_SOCRAT_ADMIN",
            wg_socrat_admin_clients={"tim-phone": {"address": "10.250.0.7"}},
            wg_socrat_nodes={
                "socrat-0": {"address": "10.250.0.1"},
                "socrat-3": {"address": "10.250.0.5"},
            },
            inventory_hostname="socrat-0",
            wg_socrat_admin_forward_rules=[
                {"client": "tim-phone", "destination": "socrat-3", "tcp_ports": [2222]}
            ],
            wg_socrat_admin_firewall_ssh_port=2222,
            wg_socrat_admin_firewall_dns_port=53,
            wireguard_private_web_enabled=False,
            wireguard_private_http_enabled=False,
        )
        subprocess.run(["sh", "-n"], input=script, text=True, check=True)
        forward = "-s 10.250.0.7/32 -d 10.250.0.5/32 -p tcp --dport 2222"
        reverse = "-s 10.250.0.5/32 -d 10.250.0.7/32 -p tcp --sport 2222 -m conntrack --ctstate ESTABLISHED"
        assert forward in script
        assert reverse in script
        assert "-j SNAT --to-source 10.250.0.1" in script
        assert script.index(forward) < script.index("REJECT --reject-with icmp-admin-prohibited")
        assert script.index('ipt -t nat -A "$new_nat_chain"') < script.index(
            "ipt -t nat -I POSTROUTING"
        )
        assert script.index("ipt -t nat -I POSTROUTING") < script.index(
            'nat_delete_all "$active_nat_chain"'
        )
        assert "ipt -t nat -F POSTROUTING" not in script
        assert 'nat_delete_all "$chain"' in script
        assert 'nat_delete_chain "$chain"' in script

    def test_persistent_unit_runs_after_wireguard_and_supports_removal(self):
        assert "After=network-online.target wg-quick@wg-socrat.service" in UNIT
        assert "ExecStart={{ wg_socrat_admin_firewall_script_path }}" in UNIT
        assert "ExecStop={{ wg_socrat_admin_firewall_script_path }} remove" in UNIT
        assert "RemainAfterExit=yes" in UNIT
        assert "ExecReload={{ wg_socrat_admin_firewall_script_path }}" in UNIT
        assert "state: reloaded" in (ROLE / "handlers/main.yml").read_text()
        assert "systemd_service" in TASKS
        assert "enabled: true" in TASKS
        assert "systemctl stop wg-socrat-admin-firewall.service" in ROLLBACK
        assert "does not flush `INPUT`, `FORWARD`" in ROLLBACK


if __name__ == "__main__":
    unittest.main()
