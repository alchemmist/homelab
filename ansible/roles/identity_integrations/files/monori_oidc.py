"""Provision only Monori; never change existing human identities or MFA flows."""

import json
import os
import secrets
from urllib.parse import urlencode

from app_iam import rows, standard_scope_ids, validate_bindings


def configure_monori(root, api):
    """Create a confidential provider and attach it only after owner admission exists."""
    service = json.loads((root / "monori-services.json").read_text())["monori"]
    if service["groups"] != ["homelab-owner"]:
        raise RuntimeError("Review Monori admission policy before expanding access")

    def match(path, field, value, required=True):
        query = {field: value}
        if path == "core/applications/":
            query["superuser_full_list"] = "true"
        records = rows(api, path + "?" + urlencode(query))
        if any(not isinstance(r, dict) or field not in r or "pk" not in r for r in records):
            raise RuntimeError("Malformed identity lookup: " + path)
        found = [r for r in records if r[field] == value]
        if len(found) > 1 or (required and not found):
            raise RuntimeError("Missing or ambiguous identity configuration: " + value)
        return found[0] if found else None

    mapping = json.loads((root / "monori-account-mappings.json").read_text())["antropophag"]
    member = match("core/users/", "username", "antropophag")
    if member.get("uuid") != mapping["idpUserUuid"] or member.get("is_active") is not True:
        raise RuntimeError("Review Monori member identity")
    owner = match("core/groups/", "name", "homelab-owner")["pk"]
    app = match("core/applications/", "slug", "monori", False)
    provider = match("providers/oauth2/", "name", "homelab-monori", False)
    by_client = match("providers/oauth2/", "client_id", "socrat-monori", False)
    if (by_client or {}).get("pk") != (provider or {}).get("pk"):
        raise RuntimeError("Monori client ID collision")
    path = root / "monori-client-secret"
    if path.is_symlink() or (
        path.exists()
        and (path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid())
    ):
        raise RuntimeError("Unsafe retained client secret")
    if not path.exists():
        if app or provider:
            raise RuntimeError(
                "Restore retained credentials; refusing to adopt an existing application"
            )
        with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
            out.write(secrets.token_urlsafe(48))
    secret = path.read_text().strip()
    if len(secret) < 32:
        raise RuntimeError("Invalid retained secret; refusing rotation")
    config = {
        "name": "homelab-monori",
        "client_type": "confidential",
        "client_id": "socrat-monori",
        "authentication_flow": match(
            "flows/instances/", "slug", "default-authentication-flow"
        )["pk"],
        "authorization_flow": match(
            "flows/instances/",
            "slug",
            "default-provider-authorization-explicit-consent",
        )["pk"],
        "invalidation_flow": match(
            "flows/instances/", "slug", "default-provider-invalidation-flow"
        )["pk"],
        "signing_key": match(
            "crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate"
        )["pk"],
        "property_mappings": standard_scope_ids(
            rows(api, "propertymappings/provider/scope/")
        ),
        "redirect_uris": [
            {
                "matching_mode": "strict",
                "url": service["redirect"],
                "redirect_uri_type": "authorization",
            }
        ],
        "sub_mode": "hashed_user_id",
        "issuer_mode": "per_provider",
        "include_claims_in_id_token": True,
        "grant_types": ["authorization_code"],
    }
    if provider:
        retained = provider.get("client_secret")
        if not isinstance(retained, str) or not secrets.compare_digest(
            retained.encode(), secret.encode()
        ):
            raise RuntimeError(
                "Cannot verify retained Monori secret against provider; refusing reconciliation"
            )
        for k, value in config.items():
            current = provider.get(k)
            if k == "property_mappings":
                current, value = sorted(current or []), sorted(value)
            if current != value:
                raise RuntimeError("Review existing Monori provider drift: " + k)
    if app and (
        app.get("policy_engine_mode") != "any"
        or app.get("provider") not in (None, (provider or {}).get("pk"))
    ):
        raise RuntimeError("Review existing Monori application drift")
    if not app:
        app = api(
            "POST",
            "core/applications/",
            {
                "name": service["name"],
                "slug": "monori",
                "group": "Socrat",
                "policy_engine_mode": "any",
                "meta_launch_url": service["url"],
                "meta_icon": service["icon"],
            },
        )
    bindings = rows(api, "policies/bindings/?" + urlencode({"target": app["pk"]}))
    users = [b for b in bindings if b.get("user") is not None]
    if users and (len(users) != 1 or users[0]["user"] != member["pk"] or users[0].get("group")
                  or users[0].get("policy") or not users[0].get("enabled")
                  or users[0].get("negate") or users[0].get("failure_result")):
        raise RuntimeError("Monori user binding drift")
    if not validate_bindings([b for b in bindings if b.get("user") is None], {owner}):
        api(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": owner,
                "order": 0,
                "enabled": True,
                "failure_result": False,
            },
        )
    if not users:
        api("POST", "policies/bindings/", {"target": app["pk"], "user": member["pk"],
            "order": 1, "enabled": True, "failure_result": False})
    if not provider:
        provider = api("POST", "providers/oauth2/", {**config, "client_secret": secret})
    if app.get("provider") is None:
        api("PATCH", "core/applications/monori/", {"provider": provider["pk"]})
    return secret
