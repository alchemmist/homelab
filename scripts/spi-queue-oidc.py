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

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"
CATALOG = ROOT / "deploy/identity/spi-triage-oidc.json"
MARKER = {"homelab_app_iam": 1}
FLOWS = {
    "authentication_flow": "default-authentication-flow",
    "authorization_flow": "default-provider-authorization-explicit-consent",
    "invalidation_flow": "default-provider-invalidation-flow",
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def private(path):
    info = path.lstat()
    require(
        not path.is_symlink()
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077,
        "Private regular operator-owned file required",
    )


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class API:
    def __init__(self, credentials, write=False):
        private(credentials)
        value = json.loads(credentials.read_text())
        self.token = value.get("AUTHENTIK_API_TOKEN") or value.get(
            "AUTHENTIK_BOOTSTRAP_TOKEN"
        )
        require(
            isinstance(self.token, str) and bool(self.token),
            "Existing automation credential required",
        )
        self.write = write
        self.http = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def call(self, method, path, value=None):
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
            require(len(body) <= 1048576, "Oversized native response")
            return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError(
                "Native API rejected operation: HTTP " + str(status)
            ) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise RuntimeError(
                "Native API transport failed; do not retry ambiguous writes"
            ) from None

    def rows(self, path):
        result = []
        for page in range(1, 21):
            data = self.call(
                "GET",
                path + ("&" if "?" in path else "?") + f"page_size=100&page={page}",
            )
            result.extend(data["results"])
            if not data.get("pagination", {}).get("next"):
                return result
        raise RuntimeError("Bounded native pagination exceeded")


def one(api, path, field, value):
    query = urllib.parse.urlencode({field: value})
    if path == "core/applications/":
        query += "&superuser_full_list=true"
    found = [row for row in api.rows(path + "?" + query) if row.get(field) == value]
    require(len(found) <= 1, "Ambiguous native object: " + value)
    return found[0] if found else None


def group_valid(row):
    require(
        row.get("is_superuser") is False
        and row.get("parents") == []
        and row.get("roles") == []
        and row.get("attributes") == MARKER,
        "SPI app group has unexpected inheritance/privilege/ownership",
    )


def inspect(api, catalog):
    provider = one(api, "providers/oauth2/", "name", catalog["provider"]["name"])
    app = one(api, "core/applications/", "slug", catalog["application"]["slug"])
    groups = {
        name: one(api, "core/groups/", "name", name) for name in catalog["groups"]
    }
    require(
        all(groups[name] for name in catalog["groups"][:2]),
        "Legacy admission groups missing",
    )
    if groups["app-spi-triage-operator"]:
        group_valid(groups["app-spi-triage-operator"])
    flow = {
        field: one(api, "flows/instances/", "slug", slug)
        for field, slug in FLOWS.items()
    }
    require(all(flow.values()), "Native MFA/consent/invalidation flows missing")
    signing = one(
        api, "crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate"
    )
    require(signing and signing.get("pk"), "Reviewed signing key missing")
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
        len(openid) == len(claims) == 1,
        "Reviewed openid/groups mappings missing or ambiguous",
    )
    require(
        claims[0].get("expression")
        == 'return {"groups": [group.name for group in request.user.ak_groups.all()]}',
        "Reviewed groups claim expression drift",
    )
    settings = {
        **catalog["provider"],
        "signing_key": signing["pk"],
        "property_mappings": [openid[0]["pk"], claims[0]["pk"]],
        **{field: value["pk"] for field, value in flow.items()},
    }
    return provider, app, groups, settings


def canonical_redirects(rows):
    return sorted((r.get("matching_mode"), r.get("url")) for r in rows)


def validate_existing(api, catalog, state, provider, app, groups, settings):
    if provider or app:
        require(
            state is not None,
            "Existing SPI identity without private client journal; stop, no adoption/rotation",
        )
        require(
            all(groups.values()), "SPI admission group missing; manual review required"
        )
        require(
            provider and app and app.get("provider") == provider["pk"],
            "Partial native identity; manual review required",
        )
        for key, value in settings.items():
            actual = provider.get(key)
            if key == "redirect_uris":
                require(
                    canonical_redirects(actual) == canonical_redirects(value),
                    "Strict callback drift",
                )
            elif key == "property_mappings":
                require(sorted(actual) == sorted(value), "Scope mapping drift")
            else:
                require(actual == value, "Provider settings drift: " + key)
        require(
            secrets.compare_digest(
                provider.get("client_secret", ""), state["client_secret"]
            ),
            "Client credential drift",
        )
        require(
            all(app.get(k) == v for k, v in catalog["application"].items()),
            "SPI application drift",
        )
        allowed = {g["pk"] for g in groups.values() if g}
        bindings = api.rows("policies/bindings/?target=" + str(app["pk"]))
        require(len(bindings) == len(allowed), "SPI binding count drift")
        seen = set()
        for binding in bindings:
            require(
                binding.get("group") in allowed
                and binding["group"] not in seen
                and not binding.get("user")
                and not binding.get("policy")
                and binding.get("enabled") is True
                and not binding.get("negate")
                and not binding.get("failure_result"),
                "Unexpected permissive/disabled SPI binding",
            )
            seen.add(binding["group"])
    else:
        require(
            state is None,
            "Private journal without live provider; inspect previous attempt first",
        )


def main():
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
        not args.state_dir.is_symlink()
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077,
        "Private state directory required",
    )
    uncertain = args.state_dir / "uncertain.json"
    require(
        not uncertain.exists(), "Uncertain previous write: stop for native GET review"
    )
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
    require(args.approve_plan_hash == digest, "Fresh plan approval required")
    require(
        args.backup_receipt is not None, "Fresh encrypted IdP backup receipt required"
    )
    private(args.backup_receipt)
    backup = json.loads(args.backup_receipt.read_text())
    from datetime import datetime

    observed = datetime.fromisoformat(backup["observedAt"])
    require(
        0 <= (datetime.now(UTC) - observed).total_seconds() <= 3600,
        "Fresh backup receipt required (at most one hour old)",
    )
    archive = Path(backup["encryptedBackup"])
    private(archive)
    require(
        hashlib.sha256(archive.read_bytes()).hexdigest() == backup["sha256"],
        "Backup hash mismatch",
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
        groups["app-spi-triage-operator"] = api.call(
            "POST",
            "core/groups/",
            {
                "name": "app-spi-triage-operator",
                "is_superuser": False,
                "parents": [],
                "roles": [],
                "attributes": MARKER,
            },
        )
        group_valid(groups["app-spi-triage-operator"])
    provider = api.call(
        "POST",
        "providers/oauth2/",
        {**settings, "client_secret": state["client_secret"]},
    )
    app = api.call(
        "POST",
        "core/applications/",
        {**catalog["application"], "provider": provider["pk"]},
    )
    for order, name in enumerate(catalog["groups"]):
        api.call(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": groups[name]["pk"],
                "order": order,
                "enabled": True,
                "negate": False,
                "failure_result": False,
            },
        )
    provider, app, groups, settings = inspect(api, catalog)
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
    main()
