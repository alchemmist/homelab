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
from pathlib import Path
from typing import Literal, NamedTuple, cast


def _require_private_paths(root: Path) -> None:
    """Refuse root directories or credentials that other users can touch."""
    for path in (root, root / "credentials.json"):
        if path.is_symlink():
            msg = "Root paths must not be symlinks: " + str(path)
            raise RuntimeError(msg)
        if path.stat().st_uid != os.getuid():
            msg = "Root paths must be owned by this user: " + str(path)
            raise RuntimeError(msg)
        if path.stat().st_mode & 0o077:
            msg = "Root paths must not be group/world accessible: " + str(path)
            raise RuntimeError(msg)


GaiResult = list[
    tuple[Literal[socket.AddressFamily.AF_INET], socket.SocketKind, int, str, tuple[str, int]]
    | tuple[
        Literal[socket.AddressFamily.AF_INET6],
        socket.SocketKind,
        int,
        str,
        tuple[str, int, int, int] | tuple[int, bytes],
    ]
]


def _pin_public_dns() -> None:
    """Force the IdP hostname to resolve to the reviewed public address."""
    original = socket.getaddrinfo

    def pinned(
        host: str | bytes | None,
        port: bytes | str | int | None = None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> GaiResult:
        """Rewrite only the reviewed IdP hostname; pass everything else through."""
        target = "109.173.40.247" if host == "auth.socrat.alchemmist.xyz" else host
        return original(target, port, family, type, proto, flags)

    socket.getaddrinfo = pinned


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
    msg = "Incomplete inventory"
    raise RuntimeError(msg)


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
    if current["uuid"] != context.fixture["uuid"]:
        msg = "Live fixture changed identity mid-run"
        raise RuntimeError(msg)
    if current["is_active"]:
        msg = "Fixture must stay inactive"
        raise RuntimeError(msg)
    if current["attributes"] != {"homelab_app_access_fixture": context.marker}:
        msg = "Fixture attributes must carry only our marker"
        raise RuntimeError(msg)
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
    if not result["successful"]:
        msg = "Native property mapping evaluation failed"
        raise RuntimeError(msg)
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
        if not subset:
            msg = "Application must keep at least one binding"
            raise RuntimeError(msg)
        if app["policy_engine_mode"] != "any":
            msg = "Application must use the ANY lane"
            raise RuntimeError(msg)
        if any(not b.get("enabled") or b.get("negate") or b.get("policy") for b in subset):
            msg = "Application lanes must be simple enabled group bindings"
            raise RuntimeError(msg)
        if any(b.get("group") == group_pk for b in subset):
            slugs.append(cast("str", app["slug"]))
    return sorted(slugs)


def _verify_projected(
    actual: dict[str, object], slug: str, expected: object, fixture_uuid: object
) -> None:
    """Verify one native projection result against the reviewed expectations."""
    if slug == "litellm":
        if actual["litellm_user_role"] != expected:
            msg = "litellm role projection drifted from the reviewed mapping"
            raise RuntimeError(msg)
        if actual["litellm_user_id"] != "authentik:" + cast("str", fixture_uuid):
            msg = "litellm id projection must pin the fixture uuid"
            raise RuntimeError(msg)
        return
    groups_value = cast("list[object]", actual["groups"])
    if expected not in groups_value:
        msg = "Projected membership must include the reviewed group"
        raise RuntimeError(msg)
    if "homelab-owner" in groups_value:
        msg = "Privileged group must never be projected"
        raise RuntimeError(msg)


def _run_cases(context: _FixtureContext) -> None:
    """Walk every mapping case, recording the verified receipt at the end."""
    cases = [
        (
            "app-litellm-user",
            "litellm",
            "homelab-litellm-reviewed-identity",
            "internal_user",
        ),
        (
            "app-open-webui-user",
            "open-webui",
            "homelab-app-open-webui-profile",
            "homelab-observer",
        ),
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
        if _check_fixture(context)["groups"] != [group_pk]:
            msg = "Fixture membership patch must be reflected exactly once"
            raise RuntimeError(msg)
        if _admitted(context, group_pk) != [slug]:
            msg = "Cross-application admission leak"
            raise RuntimeError(msg)
        actual = cast("dict[str, object]", _evaluate(context, mapping))
        _verify_projected(actual, slug, expected, context.fixture["uuid"])
        # Projection aliases exist only in this client's token, not in IdP membership.
        if _check_fixture(context)["groups"] != [group_pk]:
            msg = "Fixture membership must not drift away from the single group"
            raise RuntimeError(msg)
        successes.append(group)
        print("PASS native mapping + isolated admission:", group, flush=True)
    _api(context.credential, "PATCH", context.path, {"groups": []})
    if _check_fixture(context)["groups"] != []:
        msg = "Fixture membership must be cleared exactly"
        raise RuntimeError(msg)
    litellm = cast("dict[str, object]", _evaluate(context, "homelab-litellm-reviewed-identity"))
    if litellm["litellm_user_role"] != "internal_user_viewer":
        msg = "Removed membership must fail safe to the viewer role"
        raise RuntimeError(msg)
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
    if any(u["uuid"] == context.fixture["uuid"] for u in _rows(context.credential, "core/users/")):
        msg = "Deleted fixture must leave no residue user"
        raise RuntimeError(msg)
    print(
        "Inactive fixture deleted; no password/MFA/session or native application accounts created",
        flush=True,
    )


def main() -> None:
    """Run the command-line entry point."""
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
