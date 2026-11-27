#!/usr/bin/env python3
"""Register only n8n's native Authentik OIDC client for socrat-n8n SSO login.

Scoped twin of provision-openhands-oidc.py: same iam module, same rails.
Default GET-only plan. No users, memberships, flows, outposts or other apps change.
Apply requires the exact plan hash and a fresh encrypted identity backup receipt.
n8n keeps native invitations (no JIT); OIDC only replaces the password form for
accounts that already exist. Credential delivery stays in the operator-only
Secret automation/socrat-authentik-n8n; it is never printed.
"""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("iam", ROOT / "scripts/spi-queue-oidc.py")
iam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iam)
HOST = "n8n.socrat.alchemmist.xyz"
CLIENT = "socrat-n8n"
APP = {
    "name": "n8n",
    "slug": "n8n",
    "group": "Socrat",
    "meta_launch_url": "https://" + HOST + "/",
    "policy_engine_mode": "any",
    "meta_description": "Native n8n OIDC login for invited users. Accounts must already exist in n8n; no JIT provisioning.",
}
PROVIDER = {
    "name": "homelab-n8n",
    "client_id": CLIENT,
    "client_type": "confidential",
    "sub_mode": "user_uuid",
    "grant_types": ["authorization_code"],
    "include_claims_in_id_token": True,
    "access_token_validity": "minutes=5",
    "refresh_token_validity": "hours=8",
    "issuer_mode": "per_provider",
    "redirect_uris": [
        {"matching_mode": "strict", "url": "https://" + HOST + "/rest/sso/oidc/callback"}
    ],
}


def write_private(path, data) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())


def inspect(api):
    owner = iam.one(api, "core/groups/", "name", "homelab-owner")
    iam.require(
        "Existing owner group missing",
        ok=owner is not None,
    )
    flows = {
        key: iam.one(api, "flows/instances/", "slug", value) for key, value in iam.FLOWS.items()
    }
    iam.require(
        "Existing authentication/consent/invalidation flow missing",
        ok=all(flows.values()),
    )
    signing = iam.one(
        api, "crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate"
    )
    iam.require(
        "Existing signing key missing",
        ok=signing is not None,
    )
    mappings = api.rows("propertymappings/provider/scope/")
    selected = []
    for scope in ["openid", "profile", "email"]:
        found = [
            v
            for v in mappings
            if v.get("managed") == "goauthentik.io/providers/oauth2/scope-" + scope
        ]
        iam.require(
            "Missing/ambiguous standard scope: " + scope,
            ok=len(found) == 1,
        )
        selected.append(found[0]["pk"])
    settings = {
        **PROVIDER,
        "signing_key": signing["pk"],
        "property_mappings": selected,
        **{key: value["pk"] for key, value in flows.items()},
    }
    provider = iam.one(api, "providers/oauth2/", "name", PROVIDER["name"])
    by_client = iam.one(api, "providers/oauth2/", "client_id", CLIENT)
    iam.require(
        "Client-id collision",
        ok=(provider or {}).get("pk") == (by_client or {}).get("pk"),
    )
    app = iam.one(api, "core/applications/", "slug", APP["slug"])
    return owner, settings, provider, app


def validate(api, owner, settings, provider, app, journal) -> None:
    iam.require(
        "Partial identity or missing private journal; no adoption/reset",
        ok=provider and app and journal and journal.get("status") == "active",
    )
    for key, value in settings.items():
        actual = provider.get(key)
        if key in ["property_mappings", "grant_types"]:
            actual, value = sorted(actual or []), sorted(value)
        if key == "redirect_uris":
            actual, value = (
                iam.canonical_redirects(actual),
                iam.canonical_redirects(value),
            )
        iam.require(
            "OIDC provider drift: " + key,
            ok=actual == value,
        )
    iam.require(
        "Identity ownership drift",
        ok=provider["pk"] == journal["provider_pk"] and str(app["pk"]) == str(journal["app_pk"]),
    )
    iam.require(
        "Client-secret drift; no rotation",
        ok=secrets.compare_digest(provider.get("client_secret", ""), journal["client_secret"]),
    )
    iam.require(
        "Application drift",
        ok=app.get("provider") == provider["pk"] and all(app.get(k) == v for k, v in APP.items()),
    )
    bindings = api.rows("policies/bindings/?target=" + str(app["pk"]))
    iam.require(
        "Unexpected application bindings",
        ok=len(bindings) == 1,
    )
    b = bindings[0]
    iam.require(
        "Owner-only admission binding drift",
        ok=b.get("group") == owner["pk"]
        and not b.get("user")
        and not b.get("policy")
        and b.get("enabled") is True
        and not b.get("negate")
        and not b.get("failure_result"),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    private = Path.home() / ".config/homelab/n8n-oidc"
    p.add_argument("--credentials", type=Path, default=private / "authentik-api-token.json")
    p.add_argument("--state-dir", type=Path, default=private / "oidc")
    p.add_argument("--backup-receipt", type=Path, default=private / "oidc-backup-receipt.json")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    if not a.credentials.exists():
        # Reuse the shared operator token (same permission set) via read-only copy.
        shared = Path.home() / ".config/homelab/openhands/authentik-api-token.json"
        a.credentials.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = json.loads(shared.read_text())
        write_private(a.credentials, data)
    a.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    iam.require(
        "Unsafe state directory",
        ok=not a.state_dir.is_symlink() and not a.state_dir.stat().st_mode & 0o077,
    )
    lock = os.open(a.state_dir / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    marker = a.state_dir / "uncertain.json"
    file = a.state_dir / "client.json"
    iam.require(
        "Uncertain prior write; inspect manually, do not retry",
        ok=not marker.exists(),
    )
    journal = None
    if file.exists():
        iam.private(file)
        journal = json.loads(file.read_text())
    api = iam.API(a.credentials)
    owner, settings, provider, app = inspect(api)
    if provider or app:
        validate(api, owner, settings, provider, app, journal)
    else:
        iam.require(
        "Private journal without live identity; stop",
        ok=journal is None,
    )
    context = {
        "application": APP,
        "provider": settings,
        "owner_group": owner["pk"],
        "existing": bool(provider),
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    if not a.apply:
        print(
            json.dumps(
                {
                    "plan_hash": digest,
                    "creates": 0 if provider else 3,
                    "allowed_group": "homelab-owner",
                    "existing_identities_modified": False,
                }
            )
        )
        return
    iam.require(
        "Exact fresh plan approval required",
        ok=a.approve_plan_hash == digest,
    )
    if not provider:
        iam.private(a.backup_receipt)
        receipt = json.loads(a.backup_receipt.read_text())
        from datetime import UTC, datetime

        age = (datetime.now(UTC) - datetime.fromisoformat(receipt["observedAt"])).total_seconds()
        backup = Path(receipt["encryptedBackup"])
        iam.private(backup)
        iam.require(
        "Fresh valid encrypted backup required",
        ok=0 <= age <= 3600
            and hashlib.sha256(backup.read_bytes()).hexdigest() == receipt["sha256"],
    )
        write_private(marker, {"plan_hash": digest})
        journal = {
            "status": "pending",
            "client_secret": secrets.token_urlsafe(48),
        }
        write_private(file, journal)
        api = iam.API(a.credentials, write=True)
        provider = api.call(
            "POST",
            "providers/oauth2/",
            {**settings, "client_secret": journal["client_secret"]},
        )
        app = api.call("POST", "core/applications/", {**APP, "provider": provider["pk"]})
        api.call(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": owner["pk"],
                "order": 0,
                "enabled": True,
                "negate": False,
                "failure_result": False,
            },
        )
        journal.update(status="active", provider_pk=provider["pk"], app_pk=app["pk"])
        fd = os.open(file, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, "w") as f:
            json.dump(journal, f)
            f.flush()
            os.fsync(f.fileno())
        owner, settings, provider, app = inspect(api)
        validate(api, owner, settings, provider, app, journal)
        marker.unlink()
    # Credential delivery is operator-only; the n8n chart mounts it as env refs.
    old = subprocess.check_output(
        [
            "kubectl",
            "-n",
            "automation",
            "get",
            "secret",
            "socrat-authentik-n8n",
            "--ignore-not-found",
            "-o",
            "json",
        ]
    )
    if old.strip():
        old = json.loads(old)
        iam.require(
        "Unexpected existing Secret owner",
        ok=old["metadata"].get("labels", {}).get("homelab-app") == "n8n",
    )
    payload = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "socrat-authentik-n8n",
            "namespace": "automation",
            "labels": {"homelab-app": "n8n"},
        },
        "type": "Opaque",
        "stringData": {
            "client-id": CLIENT,
            "client-secret": journal["client_secret"],
        },
    }
    apply = ["kubectl", "apply", "-f", "-"]
    subprocess.run(apply, input=json.dumps(payload).encode(), check=True)
    print(
        json.dumps(
            {
                "applied": True,
                "application_slug": APP["slug"],
                "client_id": CLIENT,
                "secret": "automation/socrat-authentik-n8n",
                "issuer": "https://auth.socrat.alchemmist.xyz/application/o/n8n/",
                "redirect_uri": PROVIDER["redirect_uris"][0]["url"],
            }
        )
    )


if __name__ == "__main__":
    main()
