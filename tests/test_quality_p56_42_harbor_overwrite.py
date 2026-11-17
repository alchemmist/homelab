"""Lock the Harbor overwrite mapping after removing its repeated key."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATE = ROOT / "ansible/roles/identity_integrations/files/integrate.py"
HARBOR_KEYS: tuple[str, ...] = (
    "self_registration",
    "project_creation_restriction",
    "auth_mode",
    "oidc_name",
    "oidc_endpoint",
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_scope",
    "oidc_user_claim",
    "oidc_groups_claim",
    "oidc_admin_group",
    "oidc_verify_cert",
    "oidc_auto_onboard",
)
CONSTANTS: dict[str, bool | str] = {
    "self_registration": False,
    "project_creation_restriction": "adminonly",
    "auth_mode": "oidc_auth",
    "oidc_name": "Authentik",
    "oidc_endpoint": "https://auth.socrat.alchemmist.xyz/application/o/harbor/",
    "oidc_scope": "openid,profile,email,groups",
    "oidc_user_claim": "preferred_username",
    "oidc_groups_claim": "groups",
    "oidc_admin_group": "homelab-owner",
    "oidc_verify_cert": True,
    "oidc_auto_onboard": True,
}
SUBSCRIPT_CHAINS: dict[str, tuple[str, ...]] = {
    "oidc_client_id": ("clients", "harbor", "client_id"),
    "oidc_client_secret": ("clients", "harbor", "client_secret"),
}


def _constant_key(key: ast.expr | None) -> str:
    """Return one string-literal mapping key."""
    assert isinstance(key, ast.Constant)
    assert isinstance(key.value, str)
    return key.value


def _subscript_chain(node: ast.expr) -> tuple[str, ...]:
    """Return the name and literal indexes of a subscript chain."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Subscript):
        index = current.slice
        assert isinstance(index, ast.Constant)
        assert isinstance(index.value, str)
        parts.append(index.value)
        current = current.value
    assert isinstance(current, ast.Name)
    parts.append(current.id)
    parts.reverse()
    return tuple(parts)


def _harbor_config(tree: ast.AST) -> ast.Dict:
    """Return the Harbor CONFIG_OVERWRITE_JSON mapping without executing it."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "config"
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    message = "Harbor config dict was not found"
    raise AssertionError(message)


def test_harbor_project_creation_restriction_is_unique_and_adminonly() -> None:
    """Keep adminonly once and preserve client-field wiring and key order."""
    tree = ast.parse(INTEGRATE.read_text(encoding="utf-8"))
    config = _harbor_config(tree)
    keys = [_constant_key(key) for key in config.keys]
    assert keys == list(HARBOR_KEYS)
    assert len(keys) == len(set(keys))
    values = dict(zip(keys, config.values, strict=True))
    for name, expected in CONSTANTS.items():
        value = values[name]
        assert isinstance(value, ast.Constant)
        assert value.value == expected
    for name, chain in SUBSCRIPT_CHAINS.items():
        assert _subscript_chain(values[name]) == chain


def test_repeated_identical_restriction_preserves_insertion_order() -> None:
    """A repeated identical assignment keeps the first key position and JSON."""
    before: dict[str, bool | str] = {}
    before["self_registration"] = False
    before["project_creation_restriction"] = "adminonly"
    before["auth_mode"] = "oidc_auth"
    before["project_creation_restriction"] = "adminonly"
    after = {
        "self_registration": False,
        "project_creation_restriction": "adminonly",
        "auth_mode": "oidc_auth",
    }
    assert before == after
    assert list(before) == list(after)
    assert json.dumps(before) == json.dumps(after)
