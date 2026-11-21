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
from collections.abc import Mapping
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if not args.run:
        p.error("--run required: this creates/deletes an inactive fixture")
    for path in (args.root, args.root / "credentials.json"):
        assert (
            not path.is_symlink()
            and path.stat().st_uid == os.getuid()
            and not path.stat().st_mode & 0o077
        )
    credential = json.loads((args.root / "credentials.json").read_text())
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda h, *a, **kw: original(
        "109.173.40.247" if h == "auth.socrat.alchemmist.xyz" else h, *a, **kw
    )

    def api(method: str, path: str, data: Mapping[str, object] | None = None):
        request = urllib.request.Request(
            "https://auth.socrat.alchemmist.xyz/api/v3/" + path,
            method=method,
            headers={
                "Authorization": "Bearer " + credential["AUTHENTIK_BOOTSTRAP_TOKEN"],
                "Content-Type": "application/json",
            },
            data=json.dumps(data).encode() if data is not None else None,
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def rows(path: str):
        result = []
        for page in range(1, 201):
            data = api(
                "GET", path + ("&" if "?" in path else "?") + "page_size=100&page=" + str(page)
            )
            result.extend(data["results"])
            if not data.get("pagination", {}).get("next"):
                return result
        raise RuntimeError("Incomplete inventory")

    groups = {g["name"]: g for g in rows("core/groups/")}
    apps = rows("core/applications/?superuser_full_list=true")
    bindings = rows("policies/bindings/")
    mappings = {m["name"]: m for m in rows("propertymappings/provider/scope/")}
    marker = secrets.token_hex(12)
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="app-access-native-test-", dir=args.root))
    directory.chmod(0o700)
    fixture = api(
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
    )
    path = "core/users/" + str(fixture["pk"]) + "/"
    journal = directory / "fixture.json"
    journal.write_text(json.dumps(fixture))
    journal.chmod(0o600)

    def check_fixture():
        current = api("GET", path)
        assert current["uuid"] == fixture["uuid"] and not current["is_active"]
        assert current["attributes"] == {"homelab_app_access_fixture": marker}
        return current

    def evaluate(name: str):
        result = api(
            "POST",
            "propertymappings/all/" + mappings[name]["pk"] + "/test/?format_result=false",
            {"user": fixture["pk"]},
        )
        assert result["successful"], "Native property mapping evaluation failed"
        value = result["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = ast.literal_eval(value)
        return value

    def admitted(group_pk: object):
        result = []
        for app in apps:
            subset = [b for b in bindings if b["target"] == app["pk"]]
            # Test guarantees only the simple ANY group lanes in this inventory.
            assert subset and app["policy_engine_mode"] == "any"
            assert all(
                b.get("enabled") and not b.get("negate") and not b.get("policy") for b in subset
            )
            if any(b.get("group") == group_pk for b in subset):
                result.append(app["slug"])
        return sorted(result)

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
    try:
        for group, slug, mapping, expected in cases:
            check_fixture()
            api("PATCH", path, {"groups": [groups[group]["pk"]]})
            assert check_fixture()["groups"] == [groups[group]["pk"]]
            assert admitted(groups[group]["pk"]) == [slug], "Cross-application admission leak"
            actual = evaluate(mapping)
            if slug == "litellm":
                assert actual["litellm_user_role"] == expected
                assert actual["litellm_user_id"] == "authentik:" + fixture["uuid"]
            else:
                assert expected in actual["groups"] and "homelab-owner" not in actual["groups"]
            # Projection aliases exist only in this client's token, not in IdP membership.
            assert check_fixture()["groups"] == [groups[group]["pk"]]
            successes.append(group)
            print("PASS native mapping + isolated admission:", group, flush=True)
        api("PATCH", path, {"groups": []})
        assert check_fixture()["groups"] == []
        assert (
            evaluate("homelab-litellm-reviewed-identity")["litellm_user_role"]
            == "internal_user_viewer"
        )
        result = {
            "native_mapping_cases": successes,
            "cross_app_admission_denied": True,
            "removed_membership_role_fallback_safe": True,
            "not_browser_acceptance": True,
        }
        verified = directory / "verified.json"
        verified.write_text(json.dumps(result))
        verified.chmod(0o600)
    finally:
        check_fixture()
        api("DELETE", path)
        assert not any(u["uuid"] == fixture["uuid"] for u in rows("core/users/"))
        print(
            "Inactive fixture deleted; no password/MFA/session or native application accounts created",
            flush=True,
        )
    print("PRIVATE_RECEIPT", directory)


if __name__ == "__main__":
    main()
