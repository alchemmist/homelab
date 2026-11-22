#!/usr/bin/env python3
"""Guarded Authentik OIDC provider for the NetBird pilot.

NetBird v0.82.0 embedded IdP (idp/dex buildOIDCConnectorConfig) asks Authentik for
openid, profile and email only. Generic OIDC and the authentik connector type do
not add a groups scope and do not set userIDKey or getUserInfo. Dex then reads
the groups claim from the ID token because insecureEnableGroups is true.

The stock Authentik profile mapping emits every group, and homelab-groups is a
separate groups scope the connector never requests. This tool attaches one
dedicated profile-scoped mapping that emits display claims plus an allowlist.
sub stays the Authentik user UUID. Email is only the email claim.

check and plan are Authentik GET-only. apply requires the plan digest, writes a
private journal of exact PKs/UUIDs and keeps the client secret in a runtime file.
The strict callback is derived from server.auth.issuer in the NetBird config with
the pinned GetRedirectURI algorithm. A missing issuer config blocks apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

AUTHENTIK_HOST = "auth.socrat.alchemmist.xyz"
MANAGEMENT_FQDN = "netbird.socrat.alchemmist.xyz"
AUTHENTIK_VERSION = "2026.8.5"
NETBIRD_RELEASE = "v0.82.0"
CONNECTOR_SHA256 = "3ef9df52d86ea9205055a8f44f7e4fa4cacb0d265c746474c506685a39f7ff34"
DEX_OIDC_SHA256 = "39b2adbe048fbcbe2d2f531f33e0a2de867cbc0eb960eacc39297e5d64e63747"
PROVIDER_NAME = "homelab-netbird"
APP_SLUG = "netbird-pilot"
APP_NAME = "NetBird"
MAPPING_NAME = "homelab-netbird-profile"
CLIENT_ID = "socrat-netbird"
MARKER_ATTRIBUTE = "homelab_netbird_oidc"
JOURNAL_NAME = "netbird-oidc-journal.json"
RUNTIME_NAME = "netbird-oidc-runtime.json"
GROUP_NAMES = (
    "netbird-pilot-login",
    "netbird-pilot-grafana",
    "netbird-pilot-ssh-socrat-2",
)
# Admission/pilot groups may include observers; full WG administration MUST NOT.
ADMIN_NETWORK_GROUP = "netbird-internal-admins"
PROFILE_GROUP_NAMES = (*GROUP_NAMES, ADMIN_NETWORK_GROUP)
ADMISSION_GROUP = "netbird-pilot-login"
UPSTREAM_SCOPES = ("openid", "profile", "email")
OPENID_MANAGED = "goauthentik.io/providers/oauth2/scope-openid"
EMAIL_MANAGED = "goauthentik.io/providers/oauth2/scope-email"
PROFILE_MANAGED = "goauthentik.io/providers/oauth2/scope-profile"
OUTPOST_MANAGED = "goauthentik.io/outposts/embedded"
CERT_NAME = "authentik Self-signed Certificate"
PILOT = (
    {
        "username": "alchemmist",
        "uuid": "9e33877a-3eaa-4541-98eb-8cdc10088ef6",
        "email": "anton.ingrish@gmail.com",
        "required_groups": ("homelab-owner",),
        "is_superuser": True,
    },
    {
        "username": "antropophag",
        "uuid": "6015c85b-82e9-49ce-a4e3-0270c676e26d",
        "email": "antropophag@gmail.com",
        "required_groups": ("homelab-observer",),
        "is_superuser": False,
    },
)


def callback_from_issuer(issuer: object) -> str:
    """Match idp/dex Provider.GetRedirectURI from NetBird v0.82.0.

    Trim one trailing slash, append /oauth2 when the issuer does not already end
    in that suffix, then append /callback. This does not invent a path of its own.
    """
    if not isinstance(issuer, str) or issuer == "" or any(c in issuer for c in " \t\r\n"):
        msg = "NetBird issuer is missing or contains whitespace"
        raise RuntimeError(msg)
    issuer = issuer.removesuffix("/")
    if not issuer.endswith("/oauth2"):
        issuer += "/oauth2"
    return issuer + "/callback"


def validate_management_issuer(issuer: str) -> str:
    """Document the validate management issuer operation."""
    parsed = urllib.parse.urlsplit(issuer)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or host != MANAGEMENT_FQDN
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        msg = "NetBird issuer must be https on the approved management FQDN"
        raise RuntimeError(msg)
    if host == AUTHENTIK_HOST:
        msg = "NetBird issuer must be the embedded IdP, not Authentik"
        raise RuntimeError(msg)
    return issuer


def issuer_from_netbird_config(path: str | Path) -> str:
    """Document the issuer from netbird config operation."""
    loaded = yaml.safe_load(Path(path).read_text())
    server = loaded.get("server") if isinstance(loaded, dict) else None
    auth = server.get("auth") if isinstance(server, dict) else None
    issuer = auth.get("issuer") if isinstance(auth, dict) else None
    if not isinstance(issuer, str):
        msg = "NetBird config has no server.auth.issuer string"
        raise RuntimeError(msg)
    return validate_management_issuer(issuer.strip())


def profile_expression() -> str:
    """Document the profile expression operation."""
    approved = ", ".join(repr(name) for name in PROFILE_GROUP_NAMES)
    return (
        "approved = (" + approved + ",)\n"
        "names = sorted({group.name for group in request.user.ak_groups.all() "
        "if group.name in approved})\n"
        'return {"name": request.user.name, "preferred_username": request.user.username,\n'
        # Authentik's expression serializer trims boundary whitespace on save.
        ' "nickname": request.user.username, "groups": names}'
    )


def authentik_issuer() -> str:
    """Document the authentik issuer operation."""
    return "https://" + AUTHENTIK_HOST + "/application/o/" + APP_SLUG + "/"


def _seal(body):
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if "client_secret" in encoded or "AUTHENTIK_BOOTSTRAP" in encoded:
        msg = "Refusing to seal a plan that contains a secret"
        raise RuntimeError(msg)
    body["sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    return body


def _private_write(path, value):
    path = Path(path)
    if path.is_symlink():
        msg = "Refusing to follow a private-file symlink"
        raise RuntimeError(msg)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(path, 0o600)


def _private_read(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.is_symlink():
        msg = "Refusing to follow a private-file symlink"
        raise RuntimeError(msg)
    return json.loads(path.read_text())


class Authentik:
    """Authentik HTTP API client for OIDC provider setup."""

    def __init__(self, base: str, token: str, get_only: bool) -> None:
        """Initialize the Authentik client."""
        self.base = base.rstrip("/")
        self.token = token
        self.get_only = get_only

    def __call__(self, method, path, payload=None):
        """Refuse writes in GET-only mode before making the Authentik request."""
        if self.get_only and method != "GET":
            msg = "GET-only action refused an Authentik write"
            raise RuntimeError(msg)
        target = path if path.startswith("http") else self.base + "/api/v3/" + path.lstrip("/")
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            target,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                "Authentik " + method + " failed with status " + str(error.code)
            ) from None

    def pages(self, path):
        """Follow pagination for an API path and collect all rows."""
        joiner = "&" if "?" in path else "?"
        url = path + joiner + "page_size=200"
        rows = []
        while url:
            page = self("GET", url)
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                msg = "Authentik collection response is incomplete"
                raise RuntimeError(msg)
            rows.extend(page["results"])
            nxt = (page.get("pagination") or {}).get("next")
            if not nxt:
                break
            marker = "/api/v3/"
            url = nxt.split(marker, 1)[1] if marker in str(nxt) else None
            if url is None:
                msg = "Authentik pagination link is not an API path"
                raise RuntimeError(msg)
        return rows


def _one(rows, field, value):
    found = [row for row in rows if row.get(field) == value]
    if len(found) > 1:
        msg = "Ambiguous Authentik object"
        raise RuntimeError(msg)
    return found[0] if found else None


def _managed(rows, managed):
    found = [row for row in rows if row.get("managed") == managed]
    if len(found) != 1:
        msg = "Reviewed Authentik scope mapping is missing"
        raise RuntimeError(msg)
    return found[0]


def load_inventory(api):
    """Document the load inventory operation."""
    version = api("GET", "admin/version/")
    if not isinstance(version, dict) or version.get("version_current") != AUTHENTIK_VERSION:
        msg = "Unreviewed Authentik version"
        raise RuntimeError(msg)
    return {
        "version": version["version_current"],
        "users": api.pages("core/users/"),
        "groups": api.pages("core/groups/"),
        "scopes": api.pages("propertymappings/provider/scope/"),
        "providers": api.pages("providers/oauth2/"),
        "applications": api.pages("core/applications/?superuser_full_list=true"),
        "outposts": api.pages("outposts/instances/"),
        "flows": api.pages("flows/instances/"),
        "certificates": api.pages("crypto/certificatekeypairs/"),
        "bindings": api.pages("policies/bindings/"),
    }


def _pilot_snapshot(inventory):
    superuser_groups = {row["pk"] for row in inventory["groups"] if row.get("is_superuser") is True}
    users = []
    for wanted in PILOT:
        matches = [row for row in inventory["users"] if row.get("username") == wanted["username"]]
        if len(matches) != 1:
            msg = "Reviewed pilot user is missing or ambiguous"
            raise RuntimeError(msg)
        user = matches[0]
        if (
            user.get("uuid") != wanted["uuid"]
            or user.get("email") != wanted["email"]
            or user.get("is_active") is not True
            or user.get("type", "internal") != "internal"
            or user.get("is_superuser") is not wanted["is_superuser"]
            or not isinstance(user.get("pk"), int)
        ):
            msg = "Reviewed pilot identity drifted"
            raise RuntimeError(msg)
        membership = user.get("groups")
        if not isinstance(membership, list):
            msg = "Pilot group membership is incomplete"
            raise RuntimeError(msg)
        names = []
        for pk in membership:
            group = next((row for row in inventory["groups"] if row.get("pk") == pk), None)
            if group is None or not isinstance(group.get("name"), str):
                msg = "Pilot membership points at an unknown group"
                raise RuntimeError(msg)
            names.append(group["name"])
        for required in wanted["required_groups"]:
            if required not in names:
                msg = "Reviewed legacy group membership is missing"
                raise RuntimeError(msg)
        if wanted["username"] != "alchemmist" and any(pk in superuser_groups for pk in membership):
            msg = "Pilot user has an unexpected superuser group"
            raise RuntimeError(msg)
        legacy = sorted(
            pk
            for pk in membership
            if next(row["name"] for row in inventory["groups"] if row.get("pk") == pk)
            not in GROUP_NAMES
        )
        users.append(
            {
                "username": wanted["username"],
                "pk": user["pk"],
                "uuid": user["uuid"],
                "is_superuser": user["is_superuser"],
                "legacy_groups": legacy,
            }
        )
    return users


def _group_owned(group, journal):
    recorded = (journal or {}).get("groups", {}).get(group["name"]) if group else None
    attributes = (group or {}).get("attributes") or {}
    return bool(
        recorded
        and group
        and group.get("pk") == recorded.get("pk")
        and attributes.get(MARKER_ATTRIBUTE) == (journal or {}).get("marker")
    )


def _redirect(url):
    return [{"matching_mode": "strict", "url": url, "redirect_uri_type": "authorization"}]


def _same_redirect(actual, expected):
    if not isinstance(actual, list) or len(actual) != 1 or not isinstance(actual[0], dict):
        return False
    row = actual[0]
    return (
        row.get("matching_mode") == "strict"
        and row.get("url") == expected
        and row.get("redirect_uri_type") == "authorization"
    )


def _plan_context(inventory, issuer):
    """Validate reviewed Authentik prerequisites; return shared planning context."""
    users = _pilot_snapshot(inventory)
    openid = _managed(inventory["scopes"], OPENID_MANAGED)
    email = _managed(inventory["scopes"], EMAIL_MANAGED)
    profile = _managed(inventory["scopes"], PROFILE_MANAGED)
    if "groups" not in (profile.get("expression") or "") or profile.get("scope_name") != "profile":
        msg = "Reviewed default profile mapping changed"
        raise RuntimeError(msg)
    expression = profile_expression()
    if "ak_groups" not in expression or "request.user.email" in expression or '"sub"' in expression:
        msg = "Dedicated profile expression lost its identity boundary"
        raise RuntimeError(msg)
    flows = {row.get("slug"): row.get("pk") for row in inventory["flows"]}
    for slug in (
        "default-authentication-flow",
        "default-provider-authorization-explicit-consent",
        "default-provider-invalidation-flow",
    ):
        if not isinstance(flows.get(slug), str):
            msg = "Reviewed authentication flow is missing"
            raise RuntimeError(msg)
    certificates = [row for row in inventory["certificates"] if row.get("name") == CERT_NAME]
    if len(certificates) != 1 or not isinstance(certificates[0].get("pk"), str):
        msg = "Reviewed signing key is missing or ambiguous"
        raise RuntimeError(msg)
    outposts = [row for row in inventory["outposts"] if row.get("managed") == OUTPOST_MANAGED]
    if len(outposts) != 1 or not isinstance(outposts[0].get("providers"), list):
        msg = "Expected one embedded outpost"
        raise RuntimeError(msg)
    blockers = []
    callback = None
    if issuer is None:
        blockers.append("missing NetBird issuer config; callback is not invented")
    else:
        validate_management_issuer(issuer)
        callback = callback_from_issuer(issuer)
    return {
        "users": users,
        "openid": openid,
        "email": email,
        "profile": profile,
        "expression": expression,
        "flows": flows,
        "certificate": certificates[0],
        "outpost": outposts[0],
        "callback": callback,
        "blockers": blockers,
    }


def _plan_adoption_blockers(inventory, context, journal):
    """Record blockers for adopting existing objects without their journal PKs."""
    blockers = context["blockers"]
    mapping = _one(inventory["scopes"], "name", MAPPING_NAME)
    provider = _one(inventory["providers"], "name", PROVIDER_NAME)
    application = _one(inventory["applications"], "slug", APP_SLUG)
    groups = [_one(inventory["groups"], "name", name) for name in GROUP_NAMES]
    context.update(mapping=mapping, provider=provider, application=application, groups=groups)
    if mapping and (
        journal.get("mapping_pk") != mapping.get("pk")
        or mapping.get("scope_name") not in ("profile", None)
    ):
        if journal.get("mapping_pk") != mapping.get("pk"):
            blockers.append("refusing to adopt an existing property mapping without its journal PK")
    if provider and journal.get("provider_pk") != provider.get("pk"):
        blockers.append("refusing to adopt an existing provider without its journal PK")
    if application and journal.get("application_pk") != application.get("pk"):
        blockers.append("refusing to adopt an existing application without its journal PK")
    for group in groups:
        if group and not _group_owned(group, journal):
            blockers.append("refusing to adopt an existing NetBird group without its marker and PK")
        if group and (
            group.get("is_superuser") is not False
            or group.get("parents")
            or group.get("roles")
            or group.get("children")
        ):
            blockers.append("NetBird admission group is privileged or inherited")
    if provider and provider.get("pk") in context["outpost"]["providers"]:
        blockers.append("NetBird OIDC provider must stay off the embedded outpost")


def _group_and_scope_operations(context):
    """Draft the group creation and profile mapping scope operations."""
    operations = []
    for name, group in zip(GROUP_NAMES, context["groups"]):
        if group is None:
            operations.append({"action": "create", "kind": "group", "name": name})
    mapping = context["mapping"]
    if mapping is None:
        operations.append({"action": "create", "kind": "scope", "name": MAPPING_NAME})
    elif (
        mapping.get("scope_name") != "profile" or mapping.get("expression") != context["expression"]
    ):
        operations.append({"action": "update", "kind": "scope", "pk": mapping["pk"]})
    return operations


def _provider_operation(context, desired_mappings, operations):
    """Draft the provider create/update operation once a callback is known."""
    provider = context["provider"]
    callback = context["callback"]
    provider_ready = (
        provider is not None
        and callback is not None
        and _provider_matches(
            provider,
            desired_mappings,
            callback,
            context["flows"],
            context["certificate"]["pk"],
            context["profile"]["pk"],
        )
    )
    if provider is None and callback is not None:
        operations.append({"action": "create", "kind": "provider"})
    elif (
        provider is not None
        and callback is not None
        and not provider_ready
        and context["mapping"] is not None
    ):
        operations.append({"action": "update", "kind": "provider", "pk": provider["pk"]})


def _application_operation(context, operations):
    """Draft the application create/update operation, keeping provider linkage."""
    application = context["application"]
    provider_pk = context["provider"].get("pk") if context["provider"] is not None else None
    app_fields = _application_fields()
    if application is None and any(op["kind"] == "provider" for op in operations):
        operations.append({"action": "create", "kind": "application"})
    elif application is not None:
        mismatched = any(application.get(key) != value for key, value in app_fields.items())
        if provider_pk is not None and application.get("provider") != provider_pk:
            mismatched = True
        if mismatched:
            operations.append({"action": "update", "kind": "application", "pk": application["pk"]})


def _review_application_bindings(inventory, context, operations):
    """Audit existing application bindings and draft the admission binding."""
    blockers = context["blockers"]
    application = context["application"]
    admission = next(
        group for name, group in zip(GROUP_NAMES, context["groups"]) if name == ADMISSION_GROUP
    )
    app_bindings = []
    if application is not None:
        app_bindings = [
            row for row in inventory["bindings"] if row.get("target") == application.get("pk")
        ]
        admission_pk = None if admission is None else admission.get("pk")
        foreign = [
            row
            for row in app_bindings
            if row.get("group") != admission_pk
            or row.get("user")
            or row.get("policy")
            or row.get("negate") is True
            or row.get("failure_result") is True
            or row.get("enabled") is not True
        ]
        if foreign or len(app_bindings) > 1:
            blockers.append("unexpected application binding; not removing it")
    creating_admission = any(
        op["kind"] == "group" and op.get("name") == ADMISSION_GROUP for op in operations
    )
    creating_app = any(
        op["kind"] == "application" and op["action"] == "create" for op in operations
    )
    if blockers:
        operations.clear()
    elif (
        (admission is not None or creating_admission)
        and (application is not None or creating_app)
        and not app_bindings
    ):
        operations.append({"action": "create", "kind": "binding"})


def _membership_operations(context, operations):
    """Draft add-user operations within the pinned owner and Tim pilot."""
    blockers = context["blockers"]
    users_by_pk = {user["pk"]: user for user in context["users"]}
    for name, group in zip(GROUP_NAMES, context["groups"]):
        if group is None:
            operations.extend(
                {
                    "action": "add_user",
                    "group": name,
                    "username": user["username"],
                    "user_pk": user["pk"],
                }
                for user in context["users"]
            )
            continue
        members = group.get("users")
        if not isinstance(members, list):
            blockers.append("NetBird group membership is incomplete")
            operations.clear()
            return
        unexpected = [pk for pk in members if pk not in users_by_pk]
        if unexpected:
            blockers.append("NetBird group has a member outside the owner and Tim pilot")
            operations.clear()
            return
        operations.extend(
            {
                "action": "add_user",
                "group": name,
                "username": user["username"],
                "user_pk": user["pk"],
            }
            for user in context["users"]
            if user["pk"] not in members
        )


def build_plan(inventory, issuer, journal):
    """Build the reviewed, sealed NetBird OIDC plan for the recorded pilot."""
    context = _plan_context(inventory, issuer)
    _plan_adoption_blockers(inventory, context, journal or {})
    operations = _group_and_scope_operations(context) if not context["blockers"] else []
    if not context["blockers"]:
        mapping = context["mapping"]
        desired_mappings = [context["openid"]["pk"], context["email"]["pk"]]
        if mapping is not None:
            desired_mappings.append(mapping["pk"])
        _provider_operation(context, desired_mappings, operations)
        _application_operation(context, operations)
        _review_application_bindings(inventory, context, operations)
        if not context["blockers"]:
            _membership_operations(context, operations)
    # Creating the mapping and provider in one plan is valid before either PK exists.
    # Drop a provider update that cannot name a mapping yet; create covers it.
    if any(op["action"] == "create" and op["kind"] == "scope" for op in operations):
        operations = [
            op
            for op in operations
            if not (op.get("kind") == "provider" and op.get("action") == "update")
        ]
    body = {
        "authentik_version": AUTHENTIK_VERSION,
        "netbird_release": NETBIRD_RELEASE,
        "connector_sha256": CONNECTOR_SHA256,
        "upstream_scopes": list(UPSTREAM_SCOPES),
        "groups_claim": "groups",
        "user_id_claim": "sub",
        "display_claim": "name",
        "email_claim": "email",
        "get_userinfo": False,
        "dashboard_groups_scope_sufficient": False,
        "authentik_issuer": authentik_issuer(),
        "netbird_issuer": issuer,
        "callback": context["callback"],
        "sub_mode": "user_uuid",
        "admission_group": ADMISSION_GROUP,
        "claim_groups": list(GROUP_NAMES),
        "pilot_users": context["users"],
        "outpost_pk": context["outpost"]["pk"],
        "outpost_providers": list(context["outpost"]["providers"]),
        "blockers": context["blockers"],
        "operations": operations,
    }
    return _seal(body)


def _application_fields():
    return {
        "name": APP_NAME,
        "slug": APP_SLUG,
        "meta_launch_url": "https://" + MANAGEMENT_FQDN + "/",
        "meta_description": (
            "NetBird pilot sign-in. Membership does not grant network access or Authentik admin."
        ),
        "group": "Socrat",
        "policy_engine_mode": "any",
    }


def _provider_matches(provider, mappings, callback, flows, certificate, stock_profile):
    current = provider.get("property_mappings") or []
    return (
        provider.get("client_type") == "confidential"
        and provider.get("client_id") == CLIENT_ID
        and provider.get("sub_mode") == "user_uuid"
        and provider.get("include_claims_in_id_token") is True
        and provider.get("issuer_mode") == "per_provider"
        and sorted(provider.get("grant_types") or []) == ["authorization_code", "refresh_token"]
        and stock_profile not in current
        and sorted(current) == sorted(mappings)
        and _same_redirect(provider.get("redirect_uris"), callback)
        and provider.get("authentication_flow") == flows["default-authentication-flow"]
        and provider.get("authorization_flow")
        == flows["default-provider-authorization-explicit-consent"]
        and provider.get("invalidation_flow") == flows["default-provider-invalidation-flow"]
        and provider.get("signing_key") == certificate
        and provider.get("access_token_validity") == "minutes=5"
        and provider.get("refresh_token_validity") == "hours=8"
        and "password" not in (provider.get("grant_types") or [])
        and "client_credentials" not in (provider.get("grant_types") or [])
    )


def _group_body(name, marker):
    return {
        "name": name,
        "is_superuser": False,
        "parents": [],
        "children": [],
        "users": [],
        "roles": [],
        "attributes": {MARKER_ATTRIBUTE: marker},
    }


def _provider_body(mappings, callback, flows, certificate, secret):
    return {
        "name": PROVIDER_NAME,
        "client_type": "confidential",
        "client_id": CLIENT_ID,
        "client_secret": secret,
        "sub_mode": "user_uuid",
        "include_claims_in_id_token": True,
        "issuer_mode": "per_provider",
        "grant_types": ["authorization_code", "refresh_token"],
        "property_mappings": mappings,
        "redirect_uris": _redirect(callback),
        "authentication_flow": flows["default-authentication-flow"],
        "authorization_flow": flows["default-provider-authorization-explicit-consent"],
        "invalidation_flow": flows["default-provider-invalidation-flow"],
        "signing_key": certificate,
        "access_token_validity": "minutes=5",
        "refresh_token_validity": "hours=8",
    }


def _load_secret(path, journal, create):
    current = _private_read(path)
    if current is not None:
        secret = current.get("client_secret") if isinstance(current, dict) else None
        if not isinstance(secret, str) or current.get("client_id") != CLIENT_ID or len(secret) < 32:
            msg = "Runtime client file is incomplete"
            raise RuntimeError(msg)
        digest = hashlib.sha256(secret.encode()).hexdigest()
        recorded = (journal or {}).get("client_secret_sha256")
        if recorded and recorded != digest:
            msg = "Runtime client secret does not match the journal fingerprint"
            raise RuntimeError(msg)
        return secret
    if not create:
        return None
    if journal and journal.get("provider_pk"):
        msg_0 = "Provider exists but the runtime client secret is missing; refusing to rotate it"
        raise RuntimeError(
            msg_0
        )
    secret = secrets.token_urlsafe(48)
    _private_write(path, {"client_id": CLIENT_ID, "client_secret": secret})
    return secret


def _legacy_preserved(before, after):
    previous = {row["username"]: set(row["legacy_groups"]) for row in before}
    for row in after:
        if previous[row["username"]] - set(row["legacy_groups"]):
            msg = "Legacy group membership changed; stopping"
            raise RuntimeError(msg)


def _prepare_journal(plan, journal, journal_path):
    """Create or verify the marker journal before issuing any changes."""
    if not journal.get("marker"):
        if journal:
            msg = "Refusing to replace a markerless journal before generating a client secret"
            raise RuntimeError(
                msg
            )
        journal = {
            "version": 1,
            "marker": secrets.token_hex(16),
            "status": "preparing",
            "groups": {},
            "pilot_users": {
                row["username"]: {"pk": row["pk"], "uuid": row["uuid"]}
                for row in plan["pilot_users"]
            },
        }
        _private_write(journal_path, journal)
    for row in plan["pilot_users"]:
        recorded = (journal.get("pilot_users") or {}).get(row["username"])
        if recorded != {"pk": row["pk"], "uuid": row["uuid"]}:
            msg = "Journal pilot UUID/PK does not match the live user"
            raise RuntimeError(msg)
    return journal


def _apply_group_create(api, operation, journal):
    """Create one journaled NetBird admission group."""
    created = api("POST", "core/groups/", _group_body(operation["name"], journal["marker"]))
    journal.setdefault("groups", {})[operation["name"]] = {
        "pk": created["pk"],
        "num_pk": created.get("num_pk"),
    }


def _apply_scope_create(api, journal):
    """Create the dedicated profile scope mapping."""
    created = api(
        "POST",
        "propertymappings/provider/scope/",
        {"name": MAPPING_NAME, "scope_name": "profile", "expression": profile_expression()},
    )
    journal["mapping_pk"] = created["pk"]


def _apply_scope_update(api, operation, journal):
    """Update the journaled profile scope mapping."""
    if operation["pk"] != journal.get("mapping_pk"):
        msg = "Mapping PK does not match the journal"
        raise RuntimeError(msg)
    api(
        "PATCH",
        "propertymappings/provider/scope/" + operation["pk"] + "/",
        {"scope_name": "profile", "expression": profile_expression()},
    )


def _apply_provider(state, operation):
    """Create or update the NetBird OAuth2 provider with restrictive scopes."""
    inventory = state["inventory"]
    journal = state["journal"]
    mapping_pk = journal.get("mapping_pk")
    openid = _managed(inventory["scopes"], OPENID_MANAGED)["pk"]
    email = _managed(inventory["scopes"], EMAIL_MANAGED)["pk"]
    if not isinstance(mapping_pk, str):
        msg = "Provider requires the journaled profile mapping PK"
        raise RuntimeError(msg)
    body = _provider_body(
        [openid, email, mapping_pk],
        state["plan"]["callback"],
        state["flows"],
        state["certificate"],
        state["secret"],
    )
    stock_profile = _managed(inventory["scopes"], PROFILE_MANAGED)["pk"]
    group_scopes = {row["pk"] for row in inventory["scopes"] if row.get("scope_name") == "groups"}
    group_scopes.discard(mapping_pk)
    if stock_profile in body["property_mappings"] or group_scopes.intersection(
        body["property_mappings"]
    ):
        msg = "Refusing to attach an unrestricted or unrequested groups mapping"
        raise RuntimeError(msg)
    if operation["action"] == "create":
        created = state["api"]("POST", "providers/oauth2/", body)
        journal["provider_pk"] = created["pk"]
    else:
        if operation["pk"] != journal.get("provider_pk"):
            msg = "Provider PK does not match the journal"
            raise RuntimeError(msg)
        state["api"]("PATCH", "providers/oauth2/" + str(operation["pk"]) + "/", body)


def _apply_application(api, operation, journal):
    """Create or update the journaled NetBird application entry."""
    fields = _application_fields()
    fields["provider"] = journal.get("provider_pk")
    if not isinstance(fields["provider"], int):
        msg = "Application requires the journaled provider PK"
        raise RuntimeError(msg)
    if operation["action"] == "create":
        created = api("POST", "core/applications/", fields)
        journal["application_pk"] = created["pk"]
    else:
        if operation["pk"] != journal.get("application_pk"):
            msg = "Application PK does not match the journal"
            raise RuntimeError(msg)
        api("PATCH", "core/applications/" + APP_SLUG + "/", fields)


def _apply_binding(api, journal):
    """Create the journaled admission binding."""
    group_pk = (journal.get("groups") or {}).get(ADMISSION_GROUP, {}).get("pk")
    if not isinstance(journal.get("application_pk"), str) or not isinstance(group_pk, str):
        msg = "Binding requires journaled application and admission group PKs"
        raise RuntimeError(msg)
    created = api(
        "POST",
        "policies/bindings/",
        {
            "target": journal["application_pk"],
            "group": group_pk,
            "order": 0,
            "enabled": True,
            "negate": False,
            "failure_result": False,
        },
    )
    journal["binding_pk"] = created["pk"]


def _apply_add_user(api, plan, operation, journal):
    """Add one journaled pilot user to their admission group."""
    group_pk = (journal.get("groups") or {}).get(operation["group"], {}).get("pk")
    if not isinstance(group_pk, str) or operation["user_pk"] != next(
        row["pk"] for row in plan["pilot_users"] if row["username"] == operation["username"]
    ):
        msg = "Refusing to change membership outside the journaled pilot"
        raise RuntimeError(msg)
    api("POST", "core/groups/" + group_pk + "/add_user/", {"pk": operation["user_pk"]})


def _apply_operations(state):
    """Apply the approved operation list once. Mid-apply plans change as objects appear."""
    api = state["api"]
    journal = state["journal"]
    for operation in state["plan"]["operations"]:
        if operation["action"] == "create" and operation.get("kind") == "group":
            _apply_group_create(api, operation, journal)
        elif operation["action"] == "create" and operation.get("kind") == "scope":
            _apply_scope_create(api, journal)
        elif operation.get("kind") == "scope" and operation["action"] == "update":
            _apply_scope_update(api, operation, journal)
        elif operation.get("kind") == "provider":
            _apply_provider(state, operation)
        elif operation.get("kind") == "application":
            _apply_application(api, operation, journal)
        elif operation.get("kind") == "binding" and operation["action"] == "create":
            _apply_binding(api, journal)
        elif operation["action"] == "add_user":
            _apply_add_user(api, state["plan"], operation, journal)
        else:
            msg = "Refusing an unknown apply operation"
            raise RuntimeError(msg)
        _private_write(state["journal_path"], journal)


def _verify_post_apply(api, plan, journal, journal_path, issuer):
    """Verify inventory after apply and journal the reconciled plan digest."""
    after = load_inventory(api)
    _legacy_preserved(plan["pilot_users"], _pilot_snapshot(after))
    outpost = next(row for row in after["outposts"] if row.get("pk") == plan["outpost_pk"])
    if outpost.get("providers") != list(plan["outpost_providers"]):
        msg = "Embedded outpost changed; stopping"
        raise RuntimeError(msg)
    if journal.get("provider_pk") in (outpost.get("providers") or []):
        msg = "NetBird provider was attached to the embedded outpost"
        raise RuntimeError(msg)
    confirmed = build_plan(after, issuer, journal)
    if confirmed["operations"] or confirmed["blockers"]:
        msg = "Post-apply drift; not retrying automatically"
        raise RuntimeError(msg)
    journal["status"] = "reconciled"
    journal["plan_sha256"] = confirmed["sha256"]
    journal["outpost_pk"] = plan["outpost_pk"]
    _private_write(journal_path, journal)
    return confirmed["sha256"]


def execute_apply(api, root, issuer, approved):
    """Apply one approved plan, journaling every object and verifying the result."""
    journal_path = root / JOURNAL_NAME
    runtime_path = root / RUNTIME_NAME
    journal = _private_read(journal_path) or {}
    inventory = load_inventory(api)
    plan = build_plan(inventory, issuer, journal)
    if plan["blockers"]:
        raise RuntimeError(plan["blockers"][0])
    if plan["callback"] is None:
        msg = "missing NetBird issuer config; callback is not invented"
        raise RuntimeError(msg)
    if approved != plan["sha256"]:
        msg = "Plan digest mismatch; review a fresh plan"
        raise RuntimeError(msg)
    journal = _prepare_journal(plan, journal, journal_path)
    secret = _load_secret(runtime_path, journal, create=True)
    journal["client_secret_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    journal["issuer"] = issuer
    journal["callback"] = plan["callback"]
    _private_write(journal_path, journal)
    state = {
        "api": api,
        "inventory": inventory,
        "plan": plan,
        "journal": journal,
        "journal_path": journal_path,
        "secret": secret,
        "flows": {row.get("slug"): row.get("pk") for row in inventory["flows"]},
        "certificate": next(
            row["pk"] for row in inventory["certificates"] if row.get("name") == CERT_NAME
        ),
    }
    _apply_operations(state)
    return _verify_post_apply(api, state["plan"], journal, journal_path, issuer)


def _mappings_agree(path):
    loaded = json.loads(Path(path).read_text())
    for wanted in PILOT:
        row = loaded.get(wanted["username"]) if isinstance(loaded, dict) else None
        if (
            not isinstance(row, dict)
            or row.get("idpUserUuid") != wanted["uuid"]
            or row.get("email") != wanted["email"]
        ):
            msg = "Account mapping does not match the pinned pilot UUID"
            raise RuntimeError(msg)
        if sorted(row.get("groups") or []) != sorted(wanted["required_groups"]):
            msg = "Account mapping legacy groups drifted"
            raise RuntimeError(msg)


def execute(argv):
    """Document the execute operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", nargs="?", choices=("check", "plan", "apply"), default="check")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--netbird-config", type=Path)
    parser.add_argument("--mappings", type=Path)
    parser.add_argument("--base-url", default="https://" + AUTHENTIK_HOST)
    parser.add_argument("--public-edge", choices=("109.173.40.247", "109.120.141.60"))
    args = parser.parse_args(argv)
    if args.public_edge:
        original = socket.getaddrinfo
        socket.getaddrinfo = lambda host, *rest, **kw: original(
            args.public_edge if host == AUTHENTIK_HOST else host, *rest, **kw
        )
    mappings = (
        args.mappings
        or Path(__file__).resolve().parents[4] / "deploy/identity/account-mappings.json"
    )
    _mappings_agree(mappings)
    credentials = _private_read(args.root / "credentials.json")
    token = credentials.get("AUTHENTIK_BOOTSTRAP_TOKEN") if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token:
        msg = "Authentik credential is unavailable"
        raise RuntimeError(msg)
    issuer = issuer_from_netbird_config(args.netbird_config) if args.netbird_config else None
    api = Authentik(args.base_url, token, get_only=args.action != "apply")
    journal = _private_read(args.root / JOURNAL_NAME)
    if args.action == "apply":
        import fcntl

        lock_path = args.root / ".netbird-oidc.lock"
        with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            digest = execute_apply(api, args.root, issuer, args.approve_sha256)
        print("reconciled=true plan_sha256=" + digest)
        return 0
    inventory = load_inventory(api)
    plan = build_plan(inventory, issuer, journal)
    if args.action == "plan":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if plan["blockers"] or plan["operations"]:
        print(
            "reconciled=false blockers="
            + str(len(plan["blockers"]))
            + " operations="
            + str(len(plan["operations"]))
        )
        return 1
    print("reconciled=true")
    return 0


def main(argv=None):
    """Document the main operation."""
    try:
        return execute(argv)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
