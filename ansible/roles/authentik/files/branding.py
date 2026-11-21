#!/usr/bin/env python3
"""Reconcile Quiet Mono Brand assets/CSS only; never replace authentication code.

Run as the owner with credentials in the protected Authentik deployment directory.
"""

import argparse
import datetime
import hashlib
import json
import os
import socket
import urllib.parse
import urllib.request
from pathlib import Path
from typing import cast

HOST = "auth.socrat.alchemmist.xyz"
BASE = "https://" + HOST
FIELDS = (
    "domain",
    "default",
    "branding_title",
    "branding_logo",
    "branding_favicon",
    "branding_default_flow_background",
    "branding_custom_css",
    "attributes",
    "default_application",
    "flow_authentication",
    "flow_invalidation",
    "flow_recovery",
    "flow_unenrollment",
    "flow_user_settings",
    "flow_device_code",
    "flow_user_switch",
    "flow_lockdown",
    "flow_request",
    "web_certificate",
    "client_certificates",
)


def protected_json(path: Path, value: object) -> None:
    """Atomically persist JSON readable only by the owner."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
    path.chmod(0o600)


def api(
    method: str, path: str, headers: dict[str, str], data: object | None = None
) -> dict[str, object]:
    """Call the Authentik v3 API and return the parsed (object) JSON response."""
    request = urllib.request.Request(
        BASE + "/api/v3/" + path,
        method=method,
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        if not body:
            return {}
        return cast("dict[str, object]", json.loads(body))


def exact_brand(
    headers: dict[str, str],
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    """Return every brand row and the unique domain brand, if present."""
    rows = cast(
        "list[dict[str, object]]", api("GET", "core/brands/?page_size=100", headers)["results"]
    )
    matches = [row for row in rows if row["domain"] == HOST]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous domain brand; refusing to change it")
    return rows, matches[0] if matches else None


def _rollback(headers: dict[str, str], journal_path: Path, backup_arg: Path) -> None:
    """Restore the journaled pre-theme Brand, flow titles and native stages."""
    backup = cast("dict[str, object]", json.loads(backup_arg.read_text()))
    _, current = exact_brand(headers)
    before = cast("dict[str, object]", backup["brand_before"])
    if before:
        if not current or current["brand_uuid"] != before["brand_uuid"]:
            raise RuntimeError("Brand identity changed; manual review required")
        api(
            "PATCH",
            "core/brands/" + cast("str", current["brand_uuid"]) + "/",
            headers,
            {key: before[key] for key in FIELDS if key in before},
        )
    elif current:
        journal = cast("dict[str, object]", json.loads(journal_path.read_text()))
        if current["brand_uuid"] != journal["brand_uuid"]:
            raise RuntimeError("Refusing to remove an unrelated brand")
        api("DELETE", "core/brands/" + cast("str", current["brand_uuid"]) + "/", headers)
    flow = cast("dict[str, object]", backup["flow_before"])
    api(
        "PATCH",
        "flows/instances/" + cast("str", flow["slug"]) + "/",
        headers,
        {"title": flow["title"]},
    )
    if backup.get("identification_before"):
        stage = cast("dict[str, object]", backup["identification_before"])
        api(
            "PATCH",
            "stages/identification/" + cast("str", stage["pk"]) + "/",
            headers,
            {"password_stage": stage["password_stage"], "user_fields": stage["user_fields"]},
        )
    if backup.get("password_before"):
        stage = cast("dict[str, object]", backup["password_before"])
        api(
            "PATCH",
            "stages/password/" + cast("str", stage["pk"]) + "/",
            headers,
            {"allow_show_password": stage["allow_show_password"]},
        )
    print("Brand and native display settings restored; no user/provider/session changes")


def _collect_asset_urls(theme: Path) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    """Verify every theme asset on the public edge and map it to its URL."""
    assets = cast("dict[str, dict[str, object]]", json.loads((theme / "assets.json").read_text()))
    urls: dict[str, str] = {}
    for key, asset in assets.items():
        path = theme / cast("str", asset["path"])
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != asset["sha256"]:
            raise RuntimeError("Asset checksum mismatch: " + key)
        # Do not persist Authentik media JWT URLs in CSS: those expire.
        url = BASE + "/-/quiet-mono/v1/" + digest[:12] + "-" + path.name
        with urllib.request.urlopen(url, timeout=60) as response:
            if hashlib.sha256(response.read()).hexdigest() != digest:
                raise RuntimeError("Public static asset verification failed: " + key)
        urls[key] = url
    return urls, assets


def _nature_photo_hashes(
    theme: Path, assets: dict[str, dict[str, object]], field: str
) -> set[object]:
    nature = cast("dict[str, object]", json.loads((theme / "nature.json").read_text()))
    return {
        assets[cast("dict[str, str]", photo)[field]]["sha256"]
        for photo in cast("list[object]", nature["photos"])
        if field in cast("dict[str, str]", photo)
    }


def _verify_nature_responses(
    theme: Path, urls: dict[str, str], assets: dict[str, dict[str, object]]
) -> None:
    """Verify the randomized Nature photo/scene responses against journaled assets."""
    if not (theme / "nature.json").exists():
        return
    for variant in ["desktop", "mobile"]:
        url = BASE + "/-/quiet-mono/v1/nature/" + variant
        with urllib.request.urlopen(url, timeout=60) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
            allowed = _nature_photo_hashes(theme, assets, variant)
            if digest not in allowed or "immutable" not in response.headers.get(
                "Cache-Control", ""
            ):
                raise RuntimeError("Random Nature response failed verification")
        urls["NATURE_RANDOM_" + variant.upper()] = url
    scene_url = BASE + "/-/quiet-mono/v1/nature/scene.css"
    with urllib.request.urlopen(scene_url, timeout=60) as response:
        if (
            hashlib.sha256(response.read()).hexdigest()
            not in _nature_photo_hashes(theme, assets, "sceneCss")
            or response.headers.get("Cache-Control") != "no-store"
        ):
            raise RuntimeError("Random scene CSS verification failed")
    urls["NATURE_SCENE"] = scene_url


def _render_css(theme: Path, urls: dict[str, str]) -> str:
    """Substitute asset URLs and normalize; DRF trims the textarea value."""
    css = (theme / "theme.css").read_text()
    for key, url in urls.items():
        css = css.replace("__ASSET_" + key + "__", url)
    if "__ASSET_" in css:
        raise RuntimeError("Unresolved CSS asset reference")
    return css.strip()


def _resolve_native_stages(headers: dict[str, str]) -> tuple[dict[str, object], dict[str, object]]:
    """Fetch the reviewed identification and password stages exactly once."""
    ident = cast(
        "list[dict[str, object]]",
        api("GET", "stages/identification/?name=default-authentication-identification", headers)[
            "results"
        ],
    )
    password = cast(
        "list[dict[str, object]]",
        api("GET", "stages/password/?name=default-authentication-password", headers)["results"],
    )
    if len(ident) != 1 or len(password) != 1:
        raise RuntimeError("Expected reviewed native identification/password stages")
    return ident[0], password[0]


def _revert_applied(
    headers: dict[str, str],
    previous: tuple[
        dict[str, object] | None, dict[str, object], dict[str, object], dict[str, object]
    ],
    created: dict[str, object] | None,
) -> None:
    """Restore the pre-change brand, flow title and stages after a failed apply."""
    current, flow, ident, password = previous
    if created:
        if current:
            api(
                "PATCH",
                "core/brands/" + cast("str", created["brand_uuid"]) + "/",
                headers,
                {key: current[key] for key in FIELDS if key in current},
            )
        else:
            api("DELETE", "core/brands/" + cast("str", created["brand_uuid"]) + "/", headers)
    api(
        "PATCH",
        "flows/instances/" + cast("str", flow["slug"]) + "/",
        headers,
        {"title": flow["title"]},
    )
    api(
        "PATCH",
        "stages/identification/" + cast("str", ident["pk"]) + "/",
        headers,
        {"password_stage": ident.get("password_stage"), "user_fields": ident["user_fields"]},
    )
    api(
        "PATCH",
        "stages/password/" + cast("str", password["pk"]) + "/",
        headers,
        {"allow_show_password": password.get("allow_show_password", False)},
    )


def _apply_brand(
    headers: dict[str, str],
    root: Path,
    journal_path: Path,
    urls: dict[str, str],
    css: str,
) -> None:
    """Apply the reviewed domain brand and native combined form, with rollback."""
    rows, current = exact_brand(headers)
    base = current or next(row for row in rows if row["default"])
    flows = cast(
        "list[dict[str, object]]",
        api("GET", "flows/instances/?slug=default-authentication-flow", headers)["results"],
    )
    if len(flows) != 1:
        raise RuntimeError("Expected one default authentication flow")
    flow = flows[0]
    ident, password = _resolve_native_stages(headers)
    if ident.get("password_stage") not in (None, password["pk"]):
        raise RuntimeError("Unexpected inline password stage; refusing to replace it")
    # Do not silently overwrite an unrelated existing custom theme.
    if (
        current
        and current.get("branding_custom_css")
        and "Quiet Mono v5" not in cast("str", current["branding_custom_css"])
    ):
        raise RuntimeError("Unmanaged domain CSS found; manual review required")
    payload = {key: base[key] for key in FIELDS if key in base}
    base_attributes = base.get("attributes")
    attributes = cast(
        "dict[str, object]",
        dict(base_attributes if isinstance(base_attributes, dict) else {}),
    )
    settings = attributes.get("settings")
    attributes["settings"] = {
        **(settings if isinstance(settings, dict) else {}),
        "locale": "en",
        "theme": "light",
    }
    payload.update(
        domain=HOST,
        default=False,
        branding_title="Socrat",
        branding_logo=urls["MASK"],
        branding_favicon=urls["FAVICON"],
        branding_default_flow_background=urls["CLEAR_BACKGROUND"]
        if "NATURE_RANDOM_DESKTOP" in urls
        else urls["LAKE"],
        branding_custom_css=css,
        attributes=attributes,
    )
    if (
        current
        and all(current.get(key) == value for key, value in payload.items())
        and flow["title"] == "Sign in"
        and ident.get("password_stage") == password["pk"]
        and password.get("allow_show_password")
    ):
        print("Quiet Mono Brand already reconciled; no changes")
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = root / "theme-backups" / ("before-quiet-mono-" + stamp + ".json")
    protected_json(
        backup_path,
        {
            "brand_before": current,
            "default_brand": base,
            "flow_before": flow,
            "identification_before": ident,
            "password_before": password,
        },
    )
    created = None
    try:
        if current:
            created = api(
                "PATCH", "core/brands/" + cast("str", current["brand_uuid"]) + "/", headers, payload
            )
        else:
            created = api("POST", "core/brands/", headers, payload)
        api(
            "PATCH",
            "flows/instances/" + cast("str", flow["slug"]) + "/",
            headers,
            {"title": "Sign in"},
        )
        api(
            "PATCH",
            "stages/identification/" + cast("str", ident["pk"]) + "/",
            headers,
            {"password_stage": password["pk"], "user_fields": ident["user_fields"]},
        )
        api(
            "PATCH",
            "stages/password/" + cast("str", password["pk"]) + "/",
            headers,
            {"allow_show_password": True},
        )
        protected_json(
            journal_path,
            {
                "brand_uuid": created["brand_uuid"],
                "backup": str(backup_path),
                "css_sha256": hashlib.sha256(css.encode()).hexdigest(),
                "version": "2026.8.5",
            },
        )
    except Exception:
        _revert_applied(headers, (current, flow, ident, password), created)
        raise
    print(
        "Applied domain Brand, title and native combined identification/password form; protected rollback saved"
    )


def main():
    'Main.'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("theme", type=Path)
    parser.add_argument("--action", choices=["prepare", "apply", "rollback"], default="prepare")
    parser.add_argument("--backup", type=Path)
    parser.add_argument(
        "--public-edge", help="Process-local resolution only; TLS/SNI stays verified"
    )
    args = parser.parse_args()
    if args.public_edge:
        original = socket.getaddrinfo
        socket.getaddrinfo = lambda host, *a, **kw: original(
            args.public_edge if host == HOST else host, *a, **kw
        )
    credentials = cast(
        "dict[str, object]", json.loads((args.root / "credentials.json").read_text())
    )
    headers = {"Authorization": "Bearer " + cast("str", credentials["AUTHENTIK_BOOTSTRAP_TOKEN"])}
    if (
        args.action != "rollback"
        and api("GET", "admin/version/", headers).get("version_current") != "2026.8.5"
    ):
        raise RuntimeError("Theme requires reviewed Authentik 2026.8.5; refusing version drift")
    journal_path = args.root / "quiet-mono-brand-journal.json"
    if args.action == "rollback":
        if not args.backup:
            raise RuntimeError("Explicit --backup required for rollback")
        _rollback(headers, journal_path, args.backup)
        return
    urls, assets = _collect_asset_urls(args.theme)
    _verify_nature_responses(args.theme, urls, assets)
    css = _render_css(args.theme, urls)
    protected_json(args.root / "quiet-mono-media.json", urls)
    rendered = args.root / "quiet-mono-rendered.css"
    rendered.write_text(css)
    rendered.chmod(0o600)
    if args.action == "prepare":
        print(
            "Prepared/verified",
            len(urls),
            "same-origin immutable static assets; no brand/flow changes",
        )
        return
    _apply_brand(headers, args.root, journal_path, urls, css)


if __name__ == "__main__":
    main()
