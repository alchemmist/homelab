"""Tests for private DNS zone provisioning and resolution."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/homelab_private_dns"


class PrivateDnsRoleTests(unittest.TestCase):
    """Validate the private DNS Ansible role defaults."""

    def setUp(self) -> None:
        """Load the role defaults, tasks and template."""
        self.defaults = (ROLE / "defaults/main.yml").read_text()
        self.tasks = (ROLE / "tasks/main.yml").read_text()
        self.config = (ROLE / "templates/dnsmasq.conf.j2").read_text()
        self.unit = (ROLE / "templates/homelab-private-dns.service.j2").read_text()

    def test_role_has_separate_service_and_config(self) -> None:
        """Role has separate service and config."""
        defaults = yaml.safe_load(self.defaults)
        assert defaults["homelab_private_dns_unit_name"] == "homelab-private-dns.service"
        assert defaults["homelab_private_dns_config_path"] == "/etc/homelab-private-dns.conf"
        templates = [
            task["ansible.builtin.template"]
            for task in yaml.safe_load(self.tasks)
            if "ansible.builtin.template" in task
        ]
        destinations = {template["src"]: template["dest"] for template in templates}
        assert destinations["dnsmasq.conf.j2"] == "{{ homelab_private_dns_config_path }}"
        assert destinations["homelab-private-dns.service.j2"] == (
            "/etc/systemd/system/{{ homelab_private_dns_unit_name }}"
        )

    def test_dnsmasq_is_bound_to_wireguard_address_and_has_explicit_upstreams(
        self,
    ) -> None:
        """Dnsmasq is bound to wireguard address and has explicit upstreams."""
        assert "listen-address={{ homelab_private_dns_listen_address }}" in self.config
        assert "bind-dynamic" in self.config
        assert "except-interface=lo" in self.config
        assert "interface={{ homelab_private_dns_interface }}" not in self.config
        assert "no-resolv" in self.config
        assert "no-hosts" in self.config
        assert "address=/#/" not in self.config
        assert "homelab_private_dns_upstream_servers: []" in self.defaults
        assert "server={{ server }}" in self.config

    def test_only_configured_upstreams_are_rendered(self) -> None:
        """Only configured upstreams are rendered."""
        from jinja2 import Template

        values = yaml.safe_load(self.defaults)
        values["homelab_private_dns_records"] = [
            {"name": "3.socrat.alchemmist.xyz", "address": "10.250.0.5"}
        ]
        template = Template(self.config)
        assert "server=" not in template.render(**values)
        values["homelab_private_dns_upstream_servers"] = ["1.1.1.1", "9.9.9.9"]
        rendered = template.render(**values)
        assert "server=1.1.1.1" in rendered
        assert "server=9.9.9.9" in rendered
        assert "host-record=3.socrat.alchemmist.xyz,10.250.0.5" in rendered
        assert "local=/3.socrat.alchemmist.xyz/" in rendered

    def test_records_are_rendered_as_explicit_addresses(self) -> None:
        """Records are rendered as explicit addresses."""
        assert re.search(
            r"host-record=\{\{ record\.name \}\},\{\{ record\.address \}\}", self.config
        )
        assert "local=/{{ record.name }}/" in self.config
        assert "address=/{{ record.name }}/{{ record.address }}" not in self.config
        assert "homelab_private_dns_records | sort(attribute='name')" in self.config

    def test_wireguard_lifecycle_is_part_of_private_dns_unit(self) -> None:
        """Wireguard lifecycle is part of private dns unit."""
        assert "Requires={{ homelab_private_dns_wg_service }}" in self.unit
        assert "After=network-online.target {{ homelab_private_dns_wg_service }}" in self.unit
        assert "PartOf={{ homelab_private_dns_wg_service }}" in self.unit
        assert "BindsTo={{ homelab_private_dns_wg_service }}" in self.unit

    def test_configuration_is_validated_before_start_and_restart(self) -> None:
        """Configuration is validated before start and restart."""
        assert "--test" in self.tasks
        assert "ExecStartPre={{ homelab_private_dns_binary }} --test" in self.unit
        assert "--keep-in-foreground" in self.unit
        assert "- name: Restart private DNS" in (ROLE / "handlers/main.yml").read_text()

    def test_platform_paths_cover_supported_hosts(self) -> None:
        """Platform paths cover supported hosts."""
        assert "Debian: dnsmasq-base" in self.defaults
        assert "Archlinux: /usr/bin/dnsmasq" in self.defaults
        assert "homelab_private_dns_user: homelab-dns" in self.defaults
        assert "homelab_private_dns_group: homelab-dns" in self.defaults
        assert "when: ansible_os_family == 'Debian'" in self.tasks
        assert "when: ansible_os_family == 'Archlinux'" in self.tasks

    def test_template_validates_before_replacing_live_configuration(self) -> None:
        """Template validates before replacing live configuration."""
        assert 'validate: "{{ homelab_private_dns_binary }} --test --conf-file=%s"' in self.tasks

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_ansible_accepts_valid_private_dns_values(self) -> None:
        """Ansible accepts valid private dns values."""
        result = self.run_validation(
            {
                "homelab_private_dns_listen_address": "10.250.0.1",
                "homelab_private_dns_records": [
                    {"name": "0.socrat.alchemmist.xyz", "address": "10.250.0.1"},
                    {"name": "1.socrat.alchemmist.xyz", "address": "10.250.0.3"},
                    {"name": "2.socrat.alchemmist.xyz", "address": "10.250.0.2"},
                ],
            }
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_ansible_rejects_invalid_private_dns_values(self) -> None:
        """Ansible rejects invalid private dns values."""
        result = self.run_validation(
            {
                "homelab_private_dns_listen_address": "10.250.0.999",
                "homelab_private_dns_records": [
                    {"name": "bad name", "address": "10.250.0.1"},
                ],
            }
        )
        assert result.returncode != 0

    def run_validation(self, variables: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Run the role validation with variables."""
        playbook = """
- hosts: localhost
  connection: local
  gather_facts: true
  roles:
    - homelab_private_dns
"""
        with tempfile.TemporaryDirectory() as directory:
            playbook_path = Path(directory) / "validate.yml"
            playbook_path.write_text(playbook)
            command = [
                "ansible-playbook",
                str(playbook_path),
                "--tags",
                "homelab_private_dns_validate",
                "-i",
                "localhost,",
                "-e",
                "ansible_os_family=Debian",
            ]
            command.extend(["-e", json.dumps({"ansible_os_family": "Debian", **variables})])
            return subprocess.run(
                command,
                cwd=ROOT,
                env={**os.environ, "ANSIBLE_ROLES_PATH": str(ROOT / "ansible/roles")},
                capture_output=True,
                text=True,
                check=False,
            )


if __name__ == "__main__":
    unittest.main()
