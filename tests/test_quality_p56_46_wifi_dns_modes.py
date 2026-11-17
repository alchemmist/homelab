"""Regression: laptop DNS recovery keeps file modes as octal strings."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_TASKS = _ROOT / "ansible/roles/debian_laptop/tasks/wifi_dns.yml"
_MODE_KEY = "mode"
_MODE = "0644"
_MODE_COUNT = 2


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
