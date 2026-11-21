"""Tests for the node SSH client helper."""

import getpass
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


class NodeSshClientTests(unittest.TestCase):
    """Exercise the node SSH client helper against temporary state."""
    def setUp(self) -> None:
        """Render the node SSH snippet into a disposable config."""

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        template = Environment(undefined=StrictUndefined).from_string(
            (ROOT / "ansible/roles/node_ssh_client/templates/nodes.conf.j2").read_text()
        )
        self.snippet = self.root / "nodes.conf"
        self.snippet.write_text(
            template.render(
                homelab_node_ssh_hosts={
                    "socrat-1": {"address": "10.250.0.3"},
                    "socrat-3": {"address": "10.250.0.5", "ssh_port": 2200},
                },
                hostvars={"socrat-1": {"homelab_ssh_port": 2222}},
                homelab_node_ssh_port=22,
            )
        )
        self.config = self.root / "config"
        self.config.write_text(f"Include {self.snippet}\nServerAliveCountMax 7\n")

    def resolve(self, host: str, *args: str) -> dict[str, str]:
        """Resolve effective ssh options for a host."""

        result = subprocess.run(
            ["ssh", "-G", "-F", str(self.config), *args, host],
            text=True,
            capture_output=True,
            check=True,
        )
        options: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if " " not in line:
                continue
            key, value = line.split(" ", 1)
            options[key] = value
        return options

    def test_alias_keeps_current_user_and_default_identity_policy(self) -> None:
        """Aliases keep the current user and default identity policy."""

        node = self.resolve("socrat-1")
        baseline = self.resolve("example.invalid")
        assert (node["hostname"], node["port"], node["user"]) == ("10.250.0.3", "2222", getpass.getuser())
        for key in ("identityfile", "identitiesonly", "forwardagent", "stricthostkeychecking"):
            assert node[key] == baseline[key]

    def test_explicit_user_override_remains_supported(self) -> None:
        """An explicit user override remains supported."""

        assert self.resolve("socrat-1", "-l", "tim")["user"] == "tim"

    def test_per_node_port_override(self) -> None:
        """A per-node port override wins over the default port."""

        node = self.resolve("socrat-3")
        assert (node["hostname"], node["port"]) == ("10.250.0.5", "2200")

    def test_include_does_not_leak_host_scope(self) -> None:
        """The include does not leak the host scope."""

        node = self.resolve("example.invalid")
        assert (node["hostname"], node["port"], node["serveralivecountmax"]) == ("example.invalid", "22", "7")

    def test_personal_settings_have_priority(self) -> None:
        """Personal settings keep priority over the included defaults."""

        self.config.write_text(
            f"Host socrat-1\n    User custom-account\nHost *\n    Include {self.snippet}\n"
        )
        assert self.resolve("socrat-1")["user"] == "custom-account"


if __name__ == "__main__":
    unittest.main()
