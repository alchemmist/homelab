"""Tests for the ssh_user role manual check helper."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "manual_ssh_check", ROOT / "ansible/roles/ssh_user/files/check.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ManualSSHTests(unittest.TestCase):
    """Check the manual SSH user provisioning policy end to end."""

    @classmethod
    def setUpClass(cls) -> None:
        """Generate a throwaway SSH keypair for the tests."""
        cls.temp = tempfile.TemporaryDirectory(prefix="manual-ssh-test-")
        cls.key = Path(cls.temp.name) / "fixture"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(cls.key)],
            check=True,
        )
        cls.public = cls.key.with_suffix(".pub").read_text()

    @classmethod
    def tearDownClass(cls) -> None:
        """Discard the throwaway key directory."""
        cls.temp.cleanup()

    def test_real_parser_canonicalizes_public_key_and_reports_fingerprint(self) -> None:
        """The real parser canonicalizes the key and reports its fingerprint."""
        result = check.validate("guest", self.public)
        assert result["public_key"] == " ".join(self.public.split()[:2])
        assert result["fingerprint"].startswith("SHA256:")

    def test_private_key_options_certificates_multiline_and_controls_are_rejected(
        self,
    ) -> None:
        """Private keys, options, duplicates and certificates are rejected."""
        for bad in [
            self.key.read_text(),
            'command="id" ' + self.public,
            self.public + self.public,
            self.public.rstrip() + "\tcomment",
            self.public.replace("ssh-ed25519", "ssh-ed25519-cert-v01@openssh.com"),
        ]:
            with self.assertRaises(ValueError):
                check.validate("guest", bad)

    def test_invalid_base64_ssh_wire_data_is_rejected_by_actual_parser(self) -> None:
        """Malformed wire data is rejected by the actual parser."""
        with self.assertRaises(ValueError):
            check.validate("guest", "ssh-ed25519 AAAA")

    def test_protected_and_injectable_names_are_rejected_before_parsing_key(
        self,
    ) -> None:
        """Protected or injectable usernames never reach the key parser."""
        with patch.object(check, "fingerprint") as parser:
            for name in [
                "root",
                "alchemmist",
                "ghactions",
                "nobody",
                "",
                "x;id",
                "../guest",
                "-guest",
                "UPPER",
                "x" * 32,
            ]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    check.validate(name, self.public)
            parser.assert_not_called()

    def test_play_scope_and_all_host_preflight(self) -> None:
        """The play is scoped to Socrat hosts with fatal preflight ordering."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/ssh-user.yml").read_text())[0]
        assert play["hosts"] == "Socrat"
        assert play["any_errors_fatal"]
        assert play["strategy"] == "linear"
        assert not play["gather_facts"]
        assert play["roles"] == ["ssh_user"]

    def test_additive_keys_not_exact_replacement_and_no_existing_group_stripping(
        self,
    ) -> None:
        """Keys are additive and existing groups and shells are preserved."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/ssh_user/tasks/main.yml").read_text())
        key = next(t for t in tasks if "ansible.posix.authorized_key" in t)
        assert not key["ansible.posix.authorized_key"]["exclusive"]
        assert key["become_user"] == "{{ ssh_user_key.username }}"
        assert any(t["name"].startswith("Require target-user execution") for t in tasks)
        assert "not ssh_user_account.has_requested_key" in key["when"]
        user = next(t for t in tasks if "ansible.builtin.user" in t)["ansible.builtin.user"]
        assert user["password_lock"]
        assert "omit if ssh_user_before.exists" in user["groups"]
        assert "omit if ssh_user_before.exists" in user["shell"]
        assert not any(
            "ansible.builtin.service" in t or "ansible.builtin.systemd" in t for t in tasks
        )

    def test_preflight_precedes_account_and_key_mutations(self) -> None:
        """Preflight validation precedes any account or key mutation."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/ssh_user/tasks/main.yml").read_text())
        before = next(i for i, t in enumerate(tasks) if t["name"].startswith("Preflight account"))
        mutate = next(i for i, t in enumerate(tasks) if "ansible.builtin.user" in t)
        assert before < mutate
        validators = [
            t
            for t in tasks
            if "ansible.builtin.script" in t and "before granting a key" in t["name"]
        ]
        assert len(validators) == 1

    def test_missing_inputs_stop_without_contacting_a_host(self) -> None:
        """Missing inputs abort the play without contacting any host."""
        # Fake local inventory: if the input guard fails, no account action runs.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory.yml"
            path.write_text(
                "all:\n  children:\n    Socrat:\n      hosts:\n        fixture:\n          ansible_connection: local\n          ansible_become: false\n"
            )
            p = subprocess.run(
                [
                    "ansible-playbook",
                    "-i",
                    str(path),
                    "playbooks/ssh-user.yml",
                    "--check",
                ],
                cwd=ROOT / "ansible",
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert p.returncode != 0
            assert "Supply ssh_username and ssh_public_key_file" in p.stdout
            assert "Preflight account" not in p.stdout
