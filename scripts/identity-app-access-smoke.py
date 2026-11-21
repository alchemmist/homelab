#!/usr/bin/env python3
"""Explicit disabled-fixture native mapping/admission test; NOT a browser login.

Run on socrat-0 with --run ROOT. Creates one inactive passwordless IdP fixture,
changes ONLY its memberships, tests native Authentik mappings, then deletes it.
No real human password/MFA/session, native app account or API key is touched.
"""

import argparse
import ast
import json
import os
import secrets
import socket
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, cast


def _require_private_paths(root: Path) -> None:
    """Refuse root directories or credentials that other users can touch."""
    for path in (root, root / "credentials.json"):
        assert (
            not path.is_symlink()
            and path.stat().st_uid == os.getuid()
            and not path.stat().st_mode & 0o077
        )


def _pin_public_dns() -> Callable[..., object]:
    """Force the IdP hostname to resolve to the reviewed public address."""
    original: Callable[..., object] = socket.getaddrinfo
    socket.getaddrinfo = lambda h, *a, **kw: original(
        "109.173.40.247" if h == "auth.socrat.alchemmist.xyz" else h, *a, **kw
    )
    return original


def _api(credential: dict[str, object], method: str, path: str, data: object = None) -> object:
    """Issue one Authentik API call against the reviewed public address."""
    request = urllib.request.Request(
        "https://auth.socrat.alchemmist.xyz/api/v3/" + path,
        method=method,
        headers={
            "Authorization": "Bearer " + cast("str", credential["AUTHENTIK_BOOTSTRAP_TOKEN"]),
            "Content-Type": "application/json",
        },
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def _rows(credential: dict[str, object], path: str) -> list[dict[str, object]]:
    """Collect every row of a paginated Authentik inventory endpoint."""
    rows: list[dict[str, object]] = []
    for page in range(1, 201):
        data = cast(
            "dict[str, object]",
            _api(
                credential,
                "GET",
                path + ("&" if "?" in path else "?") + "page_size=100&page=" + str(page),
            ),
        )
        rows.extend(cast("list[dict[str, object]]", data["results"]))
        if not cast("dict[str, object]", data.get("pagination", {})).get("next"):
            return rows
    raise RuntimeError("Incomplete inventory")


class _FixtureContext(NamedTuple):
    """Everything the mapping/admission cases need about the live fixture."""

    credential: dict[str, object]
    directory: Path
    fixture: dict[str, object]
    path: str
    marker: str
    groups: dict[object, dict[str, object]]
    apps: list[dict[str, object]]
    bindings: list[dict[str, object]]
    mappings: dict[object, dict[str, object]]


def _check_fixture(context: _FixtureContext) -> dict[str, object]:
    """Fetch the fixture and assert it stays inactive with only our marker."""
    current = cast("dict[str, object]", _api(context.credential, "GET", context.path))
    assert current["uuid"] == context.fixture["uuid"] and not current["is_active"]
    assert current["attributes"] == {"homelab_app_access_fixture": context.marker}
    return current


def _evaluate(context: _FixtureContext, name: str) -> object:
    """Test one native property mapping for the fixture user."""
    result = cast(
        "dict[str, object]",
        _api(
            context.credential,
            "POST",
            "propertymappings/all/"
            + cast("str", context.mappings[name]["pk"])
            + "/test/?format_result=false",
            {"user": context.fixture["pk"]},
        ),
    )
    assert result["successful"], "Native property mapping evaluation failed"
    value = result["result"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = ast.literal_eval(value)
    return value


def _admitted(context: _FixtureContext, group_pk: object) -> list[str]:
    """List app slugs whose ANY-lane binds exactly this group."""
    slugs = []
    for app in context.apps:
        subset = [b for b in context.bindings if b["target"] == app["pk"]]
        # Test guarantees only the simple ANY group lanes in this inventory.
        assert subset and app["policy_engine_mode"] == "any"
        assert all(b.get("enabled") and not b.get("negate") and not b.get("policy") for b in subset)
        if any(b.get("group") == group_pk for b in subset):
            slugs.append(cast("str", app["slug"]))
    return sorted(slugs)


def _run_cases(context: _FixtureContext) -> None:
    """Walk every mapping case, recording the verified receipt at the end."""
    cases = [
        ("app-litellm-user", "litellm", "homelab-litellm-reviewed-identity", "internal_user"),
        ("app-open-webui-user", "open-webui", "homelab-app-open-webui-profile", "homelab-observer"),
        ("app-lms-student", "lms", "homelab-app-lms-profile", "lms-students"),
        ("app-lms-teacher", "lms", "homelab-app-lms-profile", "lms-teachers"),
        (
            "app-grafana-viewer",
            "grafana",
            "authentik default OAuth Mapping: OpenID 'profile'",
            "app-grafana-viewer",
        ),
        (
            "app-grafana-editor",
            "grafana",
            "authentik default OAuth Mapping: OpenID 'profile'",
            "app-grafana-editor",
        ),
        (
            "app-wiki-reader",
            "wiki",
            "authentik default OAuth Mapping: OpenID 'profile'",
            "app-wiki-reader",
        ),
        (
            "app-wiki-editor",
            "wiki",
            "authentik default OAuth Mapping: OpenID 'profile'",
            "app-wiki-editor",
        ),
    ]
    successes = []
    for group, slug, mapping, expected in cases:
        _check_fixture(context)
        group_pk = context.groups[group]["pk"]
        _api(context.credential, "PATCH", context.path, {"groups": [group_pk]})
        assert _check_fixture(context)["groups"] == [group_pk]
        assert _admitted(context, group_pk) == [slug], "Cross-application admission leak"
        actual = _evaluate(context, mapping)
        if slug == "litellm":
            assert actual["litellm_user_role"] == expected
            assert actual["litellm_user_id"] == "authentik:" + context.fixture["uuid"]
        else:
            assert expected in actual["groups"] and "homelab-owner" not in actual["groups"]
        # Projection aliases exist only in this client's token, not in IdP membership.
        assert _check_fixture(context)["groups"] == [group_pk]
        successes.append(group)
        print("PASS native mapping + isolated admission:", group, flush=True)
    _api(context.credential, "PATCH", context.path, {"groups": []})
    assert _check_fixture(context)["groups"] == []
    assert (
        _evaluate(context, "homelab-litellm-reviewed-identity")["litellm_user_role"]
        == "internal_user_viewer"
    )
    result = {
        "native_mapping_cases": successes,
        "cross_app_admission_denied": True,
        "removed_membership_role_fallback_safe": True,
        "not_browser_acceptance": True,
    }
    verified = context.directory / "verified.json"
    verified.write_text(json.dumps(result))
    verified.chmod(0o600)


def _delete_fixture(context: _FixtureContext) -> None:
    """Delete the fixture and verify no residue user remains."""
    _check_fixture(context)
    _api(context.credential, "DELETE", context.path)
    assert not any(
        u["uuid"] == context.fixture["uuid"] for u in _rows(context.credential, "core/users/")
    )
    print(
        "Inactive fixture deleted; no password/MFA/session or native application accounts created",
        flush=True,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if not args.run:
        p.error("--run required: this creates/deletes an inactive fixture")
    _require_private_paths(args.root)
    credential = json.loads((args.root / "credentials.json").read_text())
    _pin_public_dns()
    groups = {g["name"]: g for g in _rows(credential, "core/groups/")}
    apps = _rows(credential, "core/applications/?superuser_full_list=true")
    bindings = _rows(credential, "policies/bindings/")
    mappings = {m["name"]: m for m in _rows(credential, "propertymappings/provider/scope/")}
    marker = secrets.token_hex(12)
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="app-access-native-test-", dir=args.root))
    directory.chmod(0o700)
    fixture = cast(
        "dict[str, object]",
        _api(
            credential,
            "POST",
            "core/users/",
            {
                "username": "iam-test-" + marker,
                "name": "Inactive app IAM mapping test",
                "is_active": False,
                "type": "external",
                "groups": [],
                "attributes": {"homelab_app_access_fixture": marker},
            },
        ),
    )
    path = "core/users/" + str(fixture["pk"]) + "/"
    journal = directory / "fixture.json"
    journal.write_text(json.dumps(fixture))
    journal.chmod(0o600)
    context = _FixtureContext(
        credential, directory, fixture, path, marker, groups, apps, bindings, mappings
    )
    try:
        _run_cases(context)
    finally:
        _delete_fixture(context)
    print("PRIVATE_RECEIPT", directory)


if __name__ == "__main__":
    main()
