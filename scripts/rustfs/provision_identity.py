#!/usr/bin/env python3
"""Additive RustFS-only Authentik reconciler, explicit apply, no users/group edits.

Private directory contains credentials.json (AUTHENTIK_API_TOKEN) and persistent
rustfs-client.json. Existing object drift stops, never silently updates grants.
Uses the same provider serializers/flows as the existing configure.py, but does
not invoke that broad identity bootstrap.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self, TypedDict, cast

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from types import ModuleType
    from typing import IO, Never

BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"
GROUPS = ("homelab-owner", "homelab-platform-operator")
# Explicit live-validated human identity; never grant admin to an entire SSO group.
# UUID is also this provider's signed subject (sub_mode=user_uuid).
EXPRESSION = 'return {"rustfs_policy": ["consoleAdmin"] if request.user.pk == 5 and str(request.user.uuid) == "9e33877a-3eaa-4541-98eb-8cdc10088ef6" and request.user.username == "alchemmist" else (["spi-console-reader"] if ak_is_group_member(request.user, name="homelab-owner") or ak_is_group_member(request.user, name="homelab-platform-operator") else [])}'
COLLECTIONS = (
    "core/groups/",
    "flows/instances/",
    "crypto/certificatekeypairs/",
    "propertymappings/provider/scope/",
    "providers/oauth2/",
    "providers/proxy/",
    "core/applications/",
    "policies/bindings/",
    "outposts/instances/",
)


class HttpResponse(Protocol):
    """Minimal file-like response object the opener returns."""

    def read(self, size: int = -1) -> bytes:
        """Read up to size bytes from the response body."""
        ...

    def __enter__(self) -> Self:
        """Return the response as its own context manager."""
        ...

    def __exit__(self, *args: object) -> object:
        """Close the underlying connection."""
        ...


class Opener(Protocol):
    """urllib opener protocol limited to request dispatch."""

    def open(self, request: object, timeout: float | None = None) -> HttpResponse:
        """Dispatch the request and return the response."""
        ...


class Session(TypedDict):
    """State needed to invoke the Authentik API: auth, transport, mode."""

    opener: Opener
    token: str
    writable: bool


class Pagination(TypedDict):
    """Pagination cursor block of a v3 API listing page."""

    next: int | None


class Page(TypedDict):
    """One v3 API listing page."""

    results: list[dict[str, object]]
    pagination: Pagination


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow HTTP redirects."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: IO[bytes] | None,
        code: int,
        message: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Never:
        """Close the body and refuse redirects instead of following them."""
        if response is not None:
            response.close()
        raise ValueError("redirect refused")


def reconcile_app_bindings(
    session: Session,
    bindings: list[dict[str, object]],
    app_pk: object,
    groups: list[object],
) -> None:
    """Refuse drift on existing bindings and add the missing owner-group grants."""
    for binding in bindings:
        if (
            binding.get("group") not in groups
            or binding.get("policy")
            or binding.get("user")
            or binding.get("negate")
            or not binding.get("enabled")
            or binding.get("failure_result")
        ):
            raise ValueError("unexpected authorization binding")
    for order, group in enumerate(groups):
        if not any(b.get("group") == group for b in bindings):
            call_api(
                session,
                "POST",
                "policies/bindings/",
                {
                    "target": app_pk,
                    "group": group,
                    "order": order,
                    "enabled": True,
                    "failure_result": False,
                },
            )


def builtin_scope(rows: list[dict[str, object]], name: str) -> object:
    """Execute builtin_scope."""
    matches = [
        r for r in rows if r.get("managed") == "goauthentik.io/providers/oauth2/scope-" + name
    ]
    if len(matches) != 1 or matches[0].get("scope_name") != name:
        raise ValueError("missing/duplicate/mismatched builtin scope")
    return matches[0]["pk"]


def call_api(
    session: Session,
    method: str,
    path: str,
    record: dict[str, object] | None = None,
    *,
    allow_missing: bool = False,
) -> dict[str, object] | None:
    """Send one JSON request, refusing redirects and oversized responses."""
    if method != "GET" and not session["writable"]:
        raise ValueError("writes disabled")
    request = urllib.request.Request(
        BASE + path,
        method=method,
        headers={
            "Authorization": "Bearer " + session["token"],
            "Content-Type": "application/json",
        },
        data=json.dumps(record).encode() if record is not None else None,
    )
    try:
        with session["opener"].open(request, timeout=30) as r:
            data = r.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("oversized inventory")
            value = json.loads(data)
            return cast("dict[str, object] | None", value)
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        if allow_missing and code == 404:
            return None
        raise ValueError("identity request failed") from None


def read_generator(session: Session, path: str) -> list[dict[str, object]]:
    """Return the unique inventory rows for one API collection."""
    result: list[dict[str, object]] = []
    for page_number in range(1, 101):
        query = path + "?" + urllib.parse.urlencode({"page_size": 100, "page": page_number})
        raw = call_api(session, "GET", query)
        if raw is None:
            err = ValueError("unexpected missing listing")
            raise err
        page = cast("Page", raw)
        result.extend(page["results"])
        nxt = page["pagination"]["next"]
        if nxt is None or nxt == 0:
            return result
        if type(nxt) is not int or nxt != page_number + 1:
            raise ValueError("pagination mismatch")
    raise ValueError("inventory too large")


def lookup(
    records: list[dict[str, object]],
    key: str,
    value: str,
    *,
    required: bool = False,
) -> dict[str, object] | None:
    """Return the unique inventory row matching the key/value, if adopted."""
    found = [r for r in records if r.get(key) == value]
    if len(found) > 1 or (required and not found):
        raise ValueError("missing/duplicate prerequisite")
    return found[0] if found else None


class Catalogue(TypedDict):
    """Live API session plus the inventory snapshot taken so far."""

    session: Session
    inventory: dict[str, list[dict[str, object]]]


def reconcile_object(
    catalogue: Catalogue,
    path: str,
    key: str,
    value: str,
    settings: dict[str, object],
) -> dict[str, object]:
    """Add the missing object or refuse on drift; never edit existing objects."""
    session = catalogue["session"]
    inventory = catalogue["inventory"]
    old = lookup(inventory[path], key, value)
    if old:
        for k, v in settings.items():
            actual = old.get(k)
            if isinstance(v, list) and all(isinstance(x, (str, int)) for x in v):
                if sorted(cast("list[str]", actual or [])) != sorted(cast("list[str]", v)):
                    raise ValueError("existing object drift: " + path)
            elif k == "client_secret":
                # Some serializers redact secrets. Never rotate implicitly.
                continue
            elif actual != v:
                raise ValueError("existing object drift: " + path)
        return old
    new = call_api(session, "POST", path, settings)
    if new is None:
        err = ValueError("identity creation failed")
        raise err
    inventory[path].append(new)
    return new


def require_private_root(directory: Path) -> None:
    """Fail unless the private directory is operator-owned with closed permissions."""
    st = directory.lstat()
    if (
        not directory.is_dir()
        or directory.is_symlink()
        or st.st_uid != os.getuid()
        or st.st_mode & 0o077
    ):
        raise ValueError("private directory required")


def load_or_init_client(
    module: ModuleType,
    directory: Path,
    *,
    native_taken: bool,
    session: Session,
) -> dict[str, object]:
    """Load the persisted OAuth client journal or create one when absent."""
    client_record_path = directory / "rustfs-client.json"
    if client_record_path.exists():
        module.private(client_record_path)
        return cast("dict[str, object]", json.loads(client_record_path.read_text()))
    if native_taken:
        raise ValueError("lost private client journal")
    client: dict[str, object] = {
        "client_id": "spi-rustfs-console",
        "client_secret": secrets.token_urlsafe(48),
    }
    if session["writable"]:
        fd = os.open(client_record_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(client, out)
    return client


def main() -> None:
    """Execute main."""
    p = argparse.ArgumentParser()
    p.add_argument("--private-dir", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    spec = importlib.util.spec_from_file_location(
        "bootstrap", Path(__file__).with_name("bootstrap.py")
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load RustFS bootstrap")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    d = args.private_dir
    require_private_root(d)
    b.private(d / "credentials.json")
    token = json.loads((d / "credentials.json").read_text())["AUTHENTIK_API_TOKEN"]
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    session: Session = {
        "opener": cast("Opener", http),
        "token": token,
        "writable": args.apply,
    }
    catalogue: Catalogue = {"session": session, "inventory": {}}

    catalogue["inventory"] = {path: read_generator(session, path) for path in COLLECTIONS}
    inventory = catalogue["inventory"]
    # Application list is admission-filtered, including for automation principals.
    # Exact dedicated detail GET respects RBAC without requiring superuser listing.
    inventory["core/applications/"] = []
    for slug in ("spi-rustfs-native",):
        app = call_api(session, "GET", "core/applications/" + slug + "/", allow_missing=True)
        if app is not None:
            if app.get("slug") != slug:
                raise ValueError("application detail identity mismatch")
            inventory["core/applications/"].append(app)

    def required_pk(path: str, key: str, value: str) -> object:
        row = lookup(inventory[path], key, value, required=True)
        # A required lookup either returns its unique row or raises.
        return cast("dict[str, object]", row)["pk"]

    groups = [required_pk("core/groups/", "name", name) for name in GROUPS]
    flow = {
        slug: required_pk("flows/instances/", "slug", slug)
        for slug in (
            "default-authentication-flow",
            "default-provider-authorization-explicit-consent",
            "default-provider-authorization-implicit-consent",
            "default-provider-invalidation-flow",
        )
    }
    cert = required_pk("crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate")
    mappings = [
        builtin_scope(inventory["propertymappings/provider/scope/"], name)
        for name in ("openid", "profile", "email")
    ]
    # Refuse unexplained pre-existing providers when the private journal is lost.
    client = load_or_init_client(
        b,
        d,
        native_taken=lookup(inventory["providers/oauth2/"], "name", "spi-rustfs-native")
        is not None,
        session=session,
    )
    # Inventory-only plan has no mutation, even local client secret persistence.
    if not args.apply:
        print(
            "Plan: native OIDC + two owner/platform-only proxy applications; no memberships/users/roles modified."
        )
        return

    scope = reconcile_object(
        catalogue,
        "propertymappings/provider/scope/",
        "name",
        "spi-rustfs-policy",
        {
            "name": "spi-rustfs-policy",
            "scope_name": "rustfs_policy",
            "expression": EXPRESSION,
        },
    )
    native = reconcile_object(
        catalogue,
        "providers/oauth2/",
        "name",
        "spi-rustfs-native",
        {
            "name": "spi-rustfs-native",
            "client_type": "confidential",
            "grant_types": ["authorization_code"],
            "issuer_mode": "per_provider",
            **client,
            "authentication_flow": flow["default-authentication-flow"],
            "authorization_flow": flow["default-provider-authorization-explicit-consent"],
            "invalidation_flow": flow["default-provider-invalidation-flow"],
            "property_mappings": mappings + [scope["pk"]],
            "signing_key": cert,
            "redirect_uris": [
                {
                    "matching_mode": "strict",
                    "url": "https://rustfs.socrat.alchemmist.xyz/rustfs/admin/v3/oidc/callback/default",
                    "redirect_uri_type": "authorization",
                }
            ],
            "include_claims_in_id_token": True,
            "sub_mode": "user_uuid",
            "access_token_validity": "minutes=5",
            "refresh_token_validity": "hours=1",
        },
    )
    apps = [
        (
            "spi-rustfs-native",
            "RustFS native OIDC",
            native,
            "https://rustfs.socrat.alchemmist.xyz/",
        )
    ]
    for slug, name, provider, url in apps:
        app = reconcile_object(
            catalogue,
            "core/applications/",
            "slug",
            slug,
            {
                "name": name,
                "slug": slug,
                "provider": provider["pk"],
                "meta_launch_url": url,
                "policy_engine_mode": "any",
            },
        )
        bindings = [x for x in inventory["policies/bindings/"] if x.get("target") == app["pk"]]
        reconcile_app_bindings(session, bindings, app["pk"], groups)
    print(
        "Dedicated applications reconciled; verify discovery S256/client_secret_post and real browser authorization before routes."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Identity provisioning stopped; private state may be partial. No automatic rollback or existing identity edits."
        )
