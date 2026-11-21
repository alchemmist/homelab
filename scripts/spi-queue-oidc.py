#!/usr/bin/env python3
"""Narrow native SPI OIDC provisioning. Default GET-only plan; never foundation replay.

Existing provider/client drift is a STOP, never a credential reset/adoption.
Fresh approved plan hash + encrypted-backup receipt are required for apply.
Any ambiguous write leaves a private uncertain marker and requires manual review.
No users/passwords/MFA/memberships/outposts/other applications are modified.
"""

import argparse
import hashlib
import json
import os
import secrets
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"
CATALOG = ROOT / "deploy/identity/spi-triage-oidc.json"
MARKER = {"homelab_app_iam": 1}
FLOWS = {
    "authentication_flow": "default-authentication-flow",
    "authorization_flow": "default-provider-authorization-explicit-consent",
    "invalidation_flow": "default-provider-invalidation-flow",
}


def require(ok, message) -> None:
    if not ok:
        raise RuntimeError(message)


def private(path) -> None:
    info = path.lstat()
    require(
        "Private regular operator-owned file required",
        ok=not path.is_symlink()
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077,
    )


def save(path, value) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow HTTP redirects."""

    def redirect_request(self, *args, **kwargs) -> None:

        'Refuse redirects so credentials are never forwarded.'
        return None


class API:
    """SPI queue OIDC provider API client."""

    def __init__(self, credentials: Path, *, write: bool = False) -> None:

        private(credentials)
        value = json.loads(credentials.read_text())
        self.token = value.get("AUTHENTIK_API_TOKEN") or value.get("AUTHENTIK_BOOTSTRAP_TOKEN")
        require(
            "Existing automation credential required",
            ok=isinstance(self.token, str) and bool(self.token),
        )
        self.write = write
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, value=None) -> "object | None":
        'Call the pinned API with strict path validation.'
        require(
            not path.startswith("/") and "://" not in path,
            "Fixed native API path required",
        )
        require(method == "GET" or self.write, "Plan is read-only")
        data = None if value is None else json.dumps(value).encode()
        req = urllib.request.Request(
            BASE + path,
            method=method,
            data=data,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        try:
            with self.http.open(req, timeout=15) as response:
                body = response.read(1048577)
            require("Oversized native response", ok=len(body) <= 1048576)
            result = json.loads(body) if body else None
            if method == "POST":
                require(
                    "Malformed native create response; inspect uncertain marker before retry",
                    ok=isinstance(result, dict)
                    and type(result.get("pk")) in (str, int)
                    and bool(result["pk"]),
                )
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError("Native API rejected operation: HTTP " + str(status)) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise RuntimeError(
                "Native API transport failed; do not retry ambiguous writes"
            ) from None

    def rows(self, path) -> "list[dict[str, object]]":
        'Collect all pages of rows for an API path.'
        result: list[dict[str, object]] = []
        for page in range(1, 21):
            data = self.call(
                "GET",
                path + ("&" if "?" in path else "?") + f"page_size=100&page={page}",
            )
            require(
                "Malformed native list response",
                ok=isinstance(data, dict)
                and isinstance(data.get("results"), list)
                and all(isinstance(row, dict) for row in data["results"]),
            )
            if not isinstance(data, dict):
                reason = "Malformed native list response"
                raise TypeError(reason)
            pagination = data.get("pagination")
            require(
                "Malformed native pagination", ok=pagination is None or isinstance(pagination, dict)
            )
            next_page = (pagination or {}).get("next")
            require(
                "Malformed native pagination cursor",
                ok=next_page is None or (type(next_page) is int and next_page in (0, page + 1)),
            )
            result.extend(cast("list[dict[str, object]]", row_data["results"]))
            if not next_page:
                return result
        raise RuntimeError("Bounded native pagination exceeded")


def one(api, path, field, value) -> "dict[str, object] | None":
    query = urllib.parse.urlencode({field: value})
    if path == "core/applications/":
        query += "&superuser_full_list=true"
    found = [row for row in api.rows(path + "?" + query) if row.get(field) == value]
    require("Ambiguous native object: " + cast("str", value), ok=len(found) <= 1)
    return found[0] if found else None


def group_valid(row) -> None:
    require(
        "SPI app group has unexpected inheritance/privilege/ownership",
        ok=row.get("is_superuser") is False
        and row.get("parents") == []
        and row.get("roles") == []
        and row.get("attributes") == MARKER,
    )


def inspect(
    api, catalog
) -> tuple[
    dict[str, object] | None,
    dict[str, object] | None,
    dict[str, dict[str, object] | None],
    dict[str, object],
]:
    provider = one(api, "providers/oauth2/", "name", catalog["provider"]["name"])
    app = one(api, "core/applications/", "slug", catalog["application"]["slug"])
    groups = {name: one(api, "core/groups/", "name", name) for name in catalog["groups"]}
    require(
        all(groups[name] for name in catalog["groups"][:2]),
        "Legacy admission groups missing",
    )
    if groups["app-spi-triage-operator"]:
        group_valid(groups["app-spi-triage-operator"])
    flow = {field: one(api, "flows/instances/", "slug", slug) for field, slug in FLOWS.items()}
    require("Native MFA/consent/invalidation flows missing", ok=all(flow.values()))
    signing = one(api, "crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate")
    require("Reviewed signing key missing", ok=signing and signing.get("pk"))
    scopes = api.rows("propertymappings/provider/scope/")
    openid = [
        row
        for row in scopes
        if row.get("managed") == "goauthentik.io/providers/oauth2/scope-openid"
    ]
    claims = [
        row
        for row in scopes
        if row.get("name") == "homelab-groups" and row.get("scope_name") == "groups"
    ]
    require(
        "Reviewed openid/groups mappings missing or ambiguous", ok=len(openid) == len(claims) == 1
    )
    require(
        "Reviewed groups claim expression drift",
        ok=claims[0].get("expression")
        == 'return {"groups": [group.name for group in request.user.ak_groups.all()]}',
    )
    settings = {
        **catalog["provider"],
        "signing_key": signing["pk"] if signing else None,
        "property_mappings": [openid[0]["pk"], claims[0]["pk"]],
        **{field: value["pk"] for field, value in flow.items() if value is not None},
    }
    return provider, app, groups, settings


def canonical_redirects(rows) -> "list[tuple[object, object]]":
    return sorted((r.get("matching_mode"), r.get("url")) for r in rows)


def validate_existing(api, catalog, state, provider, app, groups, settings) -> None:
    if provider or app:
        require(
            "Existing SPI identity without private client journal; stop, no adoption/rotation",
            ok=state is not None,
        )
        require("SPI admission group missing; manual review required", ok=all(groups.values()))
        require(
            "Partial native identity; manual review required",
            ok=bool(provider and app and app.get("provider") == provider["pk"]),
        )
        provider_row = cast("dict[str, object]", provider)
        app_row = cast("dict[str, object]", app)
        state_row = cast("dict[str, object]", state)
        for key, value in settings.items():
            actual = provider_row.get(key)
            if key == "redirect_uris":
                require(
                    "Strict callback drift",
                    ok=canonical_redirects(cast("list[dict[str, object]]", actual))
                    == canonical_redirects(cast("list[dict[str, object]]", value)),
                )
            elif key == "property_mappings":
                require(
                    "Scope mapping drift",
                    ok=sorted(cast("list[str]", actual)) == sorted(cast("list[str]", value)),
                )
            else:
                require("Provider settings drift: " + key, ok=actual == value)
        require(
            "Client credential drift",
            ok=secrets.compare_digest(
                cast("str", provider_row.get("client_secret", "")),
                cast("str", state_row["client_secret"]),
            ),
        )
        application = cast("dict[str, object]", catalog["application"])
        require(
            "SPI application drift",
            ok=all(app_row.get(k) == v for k, v in application.items()),
        )
        allowed = {cast("dict[str, object]", g)["pk"] for g in groups.values() if g}
        bindings = api.rows("policies/bindings/?target=" + str(app_row["pk"]))
        require("SPI binding count drift", ok=len(bindings) == len(allowed))
        seen = set()
        for binding in bindings:
            require(
                "Unexpected permissive/disabled SPI binding",
                ok=binding.get("group") in allowed
                and binding["group"] not in seen
                and not binding.get("user")
                and not binding.get("policy")
                and binding.get("enabled") is True
                and not binding.get("negate")
                and not binding.get("failure_result"),
            )
            seen.add(binding["group"])
    else:
        require(
            "Private journal without live provider; inspect previous attempt first",
            ok=state is None,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-plan-hash")
    parser.add_argument("--backup-receipt", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = args.state_dir.lstat()
    require(
        "Private state directory required",
        ok=(
            not args.state_dir.is_symlink()
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o077
        ),
    )
    uncertain = args.state_dir / "uncertain.json"
    require("Uncertain previous write: stop for native GET review", ok=not uncertain.exists())
    journal = args.state_dir / "credentials.json"
    state = None
    if journal.exists():
        private(journal)
        state = json.loads(journal.read_text())
    catalog = json.loads(CATALOG.read_text())
    api = API(args.credentials)
    provider, app, groups, settings = inspect(api, catalog)
    validate_existing(api, catalog, state, provider, app, groups, settings)
    context = {
        "catalog": catalog,
        "settings": settings,
        "provider": provider["pk"] if provider else None,
        "app": app["pk"] if app else None,
        "groups": {k: v["pk"] if v else None for k, v in groups.items()},
    }
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    if not args.apply or provider:
        print(
            json.dumps(
                {
                    "operations": 0 if provider else 6,
                    "plan_hash": digest,
                    "applied": False,
                }
            )
        )
        return
    require("Fresh plan approval required", ok=args.approve_plan_hash == digest)
    require("Fresh encrypted IdP backup receipt required", ok=args.backup_receipt is not None)
    private(args.backup_receipt)
    backup = json.loads(args.backup_receipt.read_text())
    from datetime import datetime

    observed = datetime.fromisoformat(backup["observedAt"])
    require(
        "Fresh backup receipt required (at most one hour old)",
        ok=0 <= (datetime.now(UTC) - observed).total_seconds() <= 3600,
    )
    archive = Path(backup["encryptedBackup"])
    private(archive)
    require(
        "Backup hash mismatch",
        ok=hashlib.sha256(archive.read_bytes()).hexdigest() == backup["sha256"],
    )
    save(args.state_dir / "before.json", context)
    save(uncertain, {"plan_hash": digest, "backup_sha256": backup["sha256"]})
    state = {
        "client_id": settings["client_id"],
        "client_secret": secrets.token_urlsafe(48),
    }
    save(journal, state)  # Persist before the first identity write.
    api.write = True
    if not groups["app-spi-triage-operator"]:
        groups["app-spi-triage-operator"] = cast(
            "dict[str, object]",
            api.call(
                "POST",
                "core/groups/",
                {
                    "name": "app-spi-triage-operator",
                    "is_superuser": False,
                    "parents": [],
                    "roles": [],
                    "attributes": MARKER,
                },
            ),
        )
        group_valid(groups["app-spi-triage-operator"])
    provider = cast(
        "dict[str, object]",
        api.call(
            "POST", "providers/oauth2/", {**settings, "client_secret": state["client_secret"]}
        ),
    )
    app = cast(
        "dict[str, object]",
        api.call(
            "POST", "core/applications/", {**catalog["application"], "provider": provider["pk"]}
        ),
    )
    for order, name in enumerate(catalog["groups"]):
        api.call(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": cast("dict[str, object]", groups[name])["pk"],
                "order": order,
                "enabled": True,
                "negate": False,
                "failure_result": False,
            },
        )
    provider, app, groups, settings = inspect(api, catalog)
    if provider is None or app is None:
        reason = "Created native identity missing after create"
        raise TypeError(reason)
    validate_existing(api, catalog, state, provider, app, groups, settings)
    save(
        args.state_dir / "after.json",
        {"provider": provider["pk"], "app": app["pk"], "plan_hash": digest},
    )
    uncertain.unlink()
    print(
        json.dumps(
            {
                "operations": 6,
                "applied": True,
                "runtime_secret_created": False,
                "note": "Use private credentials.json for the frontend-only Kubernetes Secret; never print it.",
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit("STOP: " + str(error)) from None
