"""Regression: octal Ansible file modes stay strings after quote normalization."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_TASKS = _ROOT / "ansible/roles/debian_laptop/tasks/wifi_dns.yml"
_MODE_KEY = "mode"
_MODE = "0644"
_MODE_COUNT = 2
_SINGLE_OCTAL_MODE = re.compile(r"mode:\s*'0[0-7]{3,4}'")
_MODE_FILES: dict[str, tuple[str, ...]] = {
    "ansible/playbooks/grafana-tv-dns.yml": ("0700", "0700", "0700"),
    "ansible/playbooks/identity-hosts.yml": ("0640",),
    "ansible/playbooks/otel-litellm-sdk.yml": ("0600",),
    "ansible/playbooks/rancher-private-access.yml": ("0755", "0644", "0755"),
    "ansible/playbooks/socrat-3-swap.yml": ("0644",),
    "ansible/playbooks/socrat-5-otel-stage.yml": ("0755", "0755"),
    "ansible/playbooks/tv-admin.yml": ("0700", "0755", "0644", "0700", "0600"),
    "ansible/playbooks/vpn-transit-exit-fence.yml": ("0700", "0644"),
    "ansible/playbooks/vpn-transit-home-dns.yml": ("0644", "0644"),
    "ansible/playbooks/wireguard-worker-peers.yml": ("0600",),
    "ansible/roles/debian_laptop/tasks/wifi_dns.yml": ("0644", "0644"),
    "ansible/roles/desktop_environment/tasks/main.yml": (
        "0755",
        "0644",
        "0755",
        # Caffeine unit mode is now enforced by homelab_user_unit (test_user_unit.py).
        "0755",
        "0644",
        "0644",
        "0644",  # Hyprland Lua entry point for socrat-1 (d5bf9de7)
    ),
    "ansible/roles/desktop_panel/tasks/main.yml": (
        "0755",
        "0755",
        "0644",
        "0644",
        "0644",
    ),
    "ansible/roles/desktop_terminal/tasks/bottom.yml": ("0755", "0644", "0644"),
    "ansible/roles/identity_app_access/tasks/main.yml": ("0600",),
    "ansible/roles/identity_integrations/tasks/main.yml": (
        "0600",
        "0600",
        "0600",
        "0600",
        "0600",
        "0600",
        "0600",
    ),
    "ansible/roles/k3s_ha/tasks/member_activate.yml": ("0600",),
    "ansible/roles/k3s_worker/tasks/main.yml": (
        "0755",
        "0644",
        "0644",
        "0700",
        "0600",
        "0755",
        "0600",
        "0644",
        "0755",
        "0644",
    ),
    "ansible/roles/monitoring_rancher/tasks/main.yml": (
        "0700",
        "0600",
        "0600",
        "0700",
        "0600",
        "0600",
    ),
    "ansible/roles/node_ssh_client/tasks/main.yml": ("0755", "0644", "0644"),
    "ansible/roles/public_authoritative_dns/tasks/main.yml": (
        "0755",
        "0755",
        "0755",
        "0644",
        "0640",
        "0644",
    ),
    "ansible/roles/ssh_gateway/tasks/main.yml": (
        "0700",
        "0755",
        "0600",
        "0644",
        "0644",
        "0644",
    ),
    "ansible/roles/syncthing_private_monitors/tasks/main.yml": (
        "0700",
        "0755",
        "0644",
        "0600",
    ),
    "ansible/roles/syncthing_private_ui/tasks/prepare.yml": (
        "preserve",
        "0600",
        "0644",
    ),
    "ansible/roles/vpn_consolidation/tasks/main.yml": (
        "preserve",
        "0700",
        "0700",
        "0700",
    ),
    "ansible/roles/wiki_editor_access/tasks/main.yml": (
        "0700",
        "preserve",
        "0600",
        "0600",
    ),
    "ansible/roles/wireguard_private_web/tasks/main.yml": ("0700", "0755", "0644"),
}


def _collect_modes(node: object, found: list[str]) -> None:
    """Append every mapping value stored under the file-mode key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == _MODE_KEY:
                assert isinstance(value, str)
                found.append(value)
            else:
                _collect_modes(value, found)
        return
    if isinstance(node, list):
        for item in node:
            _collect_modes(item, found)


def test_wifi_dns_file_modes_stay_octal_strings() -> None:
    """Keep both resolver-file modes as the string 0644, not integers."""
    text = _TASKS.read_text(encoding="utf-8")
    found: list[str] = []
    _collect_modes(yaml.safe_load(text), found)
    assert found == [_MODE, _MODE]
    assert "mode: '0644'" not in text
    assert text.count('mode: "0644"') == _MODE_COUNT


def test_lane_octal_file_modes_stay_strings() -> None:
    """Keep every collected file mode equal to its pre-normalization string."""
    for relative, expected in _MODE_FILES.items():
        text = (_ROOT / relative).read_text(encoding="utf-8")
        found: list[str] = []
        for document in yaml.safe_load_all(text):
            _collect_modes(document, found)
        assert tuple(found) == expected
        assert _SINGLE_OCTAL_MODE.search(text) is None
