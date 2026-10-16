from pathlib import Path
import unittest
import shlex
import subprocess

from jinja2 import Environment


ROLE = Path(__file__).resolve().parents[1] / 'ansible/roles/wireguard_admin_firewall'
TASKS = (ROLE / 'tasks/main.yml').read_text()
DEFAULTS = (ROLE / 'defaults/main.yml').read_text()
SCRIPT = (ROLE / 'templates/wg-socrat-admin-firewall.sh.j2').read_text()
UNIT = (ROLE / 'templates/wg-socrat-admin-firewall.service.j2').read_text()
ROLLBACK = (ROLE / 'ROLLBACK.md').read_text()


class WireGuardAdminFirewallTests(unittest.TestCase):
    def test_uses_client_registry_and_exact_interface(self):
        self.assertIn('wg_socrat_admin_clients', DEFAULTS)
        self.assertIn('interface={{ wg_socrat_admin_firewall_interface | quote }}', SCRIPT)
        self.assertIn('wg-socrat', DEFAULTS)
        self.assertIn('dict2items', SCRIPT)
        self.assertIn('item.value.address', TASKS)

    def test_only_allows_ssh_and_private_dns_to_the_node(self):
        self.assertIn('--dport {{ wg_socrat_admin_firewall_ssh_port }}', SCRIPT)
        self.assertIn('--dport {{ wg_socrat_admin_firewall_dns_port }}', SCRIPT)
        self.assertIn('-p tcp', SCRIPT)
        self.assertIn('-p udp', SCRIPT)
        self.assertIn('NEW,ESTABLISHED', SCRIPT)
        self.assertIn('--ctstate RELATED', SCRIPT)
        self.assertIn('--ctorigdstport', SCRIPT)
        self.assertIn('REJECT --reject-with icmp-port-unreachable', SCRIPT)

    def test_private_web_access_is_explicitly_disabled_by_default(self):
        self.assertIn('wireguard_private_web_enabled: false', DEFAULTS)
        self.assertIn("{% if wireguard_private_web_enabled | bool %}", SCRIPT)
        self.assertIn('--dport {{ wireguard_private_web_proxy_port }}', SCRIPT)
        self.assertIn('--ctorigdstport {{ wireguard_private_web_public_port }}', SCRIPT)

    def test_forwarding_from_admin_clients_is_rejected(self):
        self.assertIn('FORWARD', SCRIPT)
        self.assertIn('REJECT --reject-with icmp-admin-prohibited', SCRIPT)
        self.assertIn('INPUT 1 -i "$interface"', SCRIPT)
        self.assertIn('FORWARD 1 -i "$interface"', SCRIPT)

    def test_preserves_unrelated_firewall_chains(self):
        self.assertIn('input_chain_a={{ wg_socrat_admin_firewall_chain_prefix }}_INPUT_A', SCRIPT)
        self.assertIn('input_chain_b={{ wg_socrat_admin_firewall_chain_prefix }}_INPUT_B', SCRIPT)
        self.assertIn('forward_chain_a={{ wg_socrat_admin_firewall_chain_prefix }}_FORWARD_A', SCRIPT)
        self.assertIn('forward_chain_b={{ wg_socrat_admin_firewall_chain_prefix }}_FORWARD_B', SCRIPT)
        self.assertNotIn('ipt -F INPUT', SCRIPT)
        self.assertNotIn('ipt -F FORWARD', SCRIPT)
        self.assertIn('remove_rules', SCRIPT)
        self.assertIn('delete_all', SCRIPT)

    def test_replaces_owned_policy_only_after_new_chain_is_built(self):
        self.assertIn('"$iptables" -w 5', SCRIPT)
        self.assertIn('new_input_chain', SCRIPT)
        self.assertIn('new_forward_chain', SCRIPT)
        self.assertLess(SCRIPT.index('ipt -I INPUT 1'), SCRIPT.index('delete_all INPUT -i "$interface" -j "$active_input_chain"'))
        self.assertLess(SCRIPT.index('ipt -A "$new_input_chain"'), SCRIPT.index('ipt -I INPUT 1'))

    def test_transit_is_scoped_and_nat_is_reversible(self):
        env = Environment()
        env.filters['quote'] = shlex.quote
        env.filters['bool'] = bool
        env.filters['dict2items'] = lambda value: [dict(key=k, value=v) for k, v in value.items()]
        script = env.from_string(SCRIPT).render(
            wg_socrat_admin_firewall_interface='wg-socrat',
            wg_socrat_admin_firewall_chain_prefix='WG_SOCRAT_ADMIN',
            wg_socrat_admin_clients={'tim-phone': {'address': '10.250.0.7'}},
            wg_socrat_nodes={'socrat-0': {'address': '10.250.0.1'}, 'socrat-3': {'address': '10.250.0.5'}},
            inventory_hostname='socrat-0',
            wg_socrat_admin_forward_rules=[{'client': 'tim-phone', 'destination': 'socrat-3', 'tcp_ports': [2222]}],
            wg_socrat_admin_firewall_ssh_port=2222,
            wg_socrat_admin_firewall_dns_port=53,
            wireguard_private_web_enabled=False,
            wireguard_private_http_enabled=False,
        )
        subprocess.run(['sh', '-n'], input=script, text=True, check=True)
        forward = '-s 10.250.0.7/32 -d 10.250.0.5/32 -p tcp --dport 2222'
        reverse = '-s 10.250.0.5/32 -d 10.250.0.7/32 -p tcp --sport 2222 -m conntrack --ctstate ESTABLISHED'
        self.assertIn(forward, script)
        self.assertIn(reverse, script)
        self.assertIn('-j SNAT --to-source 10.250.0.1', script)
        self.assertLess(script.index(forward), script.index('REJECT --reject-with icmp-admin-prohibited'))
        self.assertLess(script.index('ipt -t nat -A "$new_nat_chain"'), script.index('ipt -t nat -I POSTROUTING'))
        self.assertLess(script.index('ipt -t nat -I POSTROUTING'), script.index('nat_delete_all "$active_nat_chain"'))
        self.assertNotIn('ipt -t nat -F POSTROUTING', script)
        self.assertIn('nat_delete_all "$chain"', script)
        self.assertIn('nat_delete_chain "$chain"', script)

    def test_persistent_unit_runs_after_wireguard_and_supports_removal(self):
        self.assertIn('After=network-online.target wg-quick@wg-socrat.service', UNIT)
        self.assertIn('ExecStart={{ wg_socrat_admin_firewall_script_path }}', UNIT)
        self.assertIn('ExecStop={{ wg_socrat_admin_firewall_script_path }} remove', UNIT)
        self.assertIn('RemainAfterExit=yes', UNIT)
        self.assertIn('ExecReload={{ wg_socrat_admin_firewall_script_path }}', UNIT)
        self.assertIn('state: reloaded', (ROLE / 'handlers/main.yml').read_text())
        self.assertIn('systemd_service', TASKS)
        self.assertIn('enabled: true', TASKS)
        self.assertIn('systemctl stop wg-socrat-admin-firewall.service', ROLLBACK)
        self.assertIn('does not flush `INPUT`, `FORWARD`', ROLLBACK)


if __name__ == '__main__':
    unittest.main()
