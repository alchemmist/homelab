#!/usr/bin/env python3
"""Withdraw only plaintext32063 from subscriptions; retain cached-client listener.

Owner coordinates end-device refresh. No client/key/binding deletion or listener retirement.
Default preview; explicit fresh session+configuration hashes required for native API write.
"""

import argparse
import base64
import copy
import importlib.util
import json
import socket
import sqlite3
import time
import types
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Protocol

LEGACY_PORT = 32063
SUBSCRIPTION_PORT = 12096
EXPECTED_AFFECTED = 7
HTTP_OK = 200
MAX_SUBSCRIPTION_BYTES = 262144
LISTENER_ATTEMPTS = 30
LISTEN_ALLOWLIST = ("", "127.0.0.1", "0.0.0.0", "::")
BACKEND_ORIGIN = "http://127.0.0.1:12096"
PUBLIC_ORIGIN = "https://vpn.alchemmist.xyz"
PUBLIC_HOST = "vpn.alchemmist.xyz"
ALLOWED_URL_SCHEMES = ("http", "https")


def load(name: str, filename: str) -> types.ModuleType:
    """Import a reviewed sibling ops module by exact file name."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None or not spec.has_location:
        reason = "Cannot load helper module"
        raise ValueError(reason)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


native = load("native_session", "vpn-panel-session.py")
target = load("target_helpers", "vpn-reality-apply.py")
h = native.h


def select(config: dict[str, object]) -> dict[str, object]:
    """Identify the single 32063 plaintext subscription entry to withdraw."""
    inbounds = config["inbounds"]
    if not isinstance(inbounds, list):
        reason = "Expected one legacy inbound"
        raise TypeError(reason)
    rows = [r for r in inbounds if isinstance(r, dict) and r["port"] == LEGACY_PORT]
    if len(rows) != 1:
        msg = "Expected one legacy inbound"
        raise ValueError(msg)
    row = rows[0]
    stream: dict[str, object] = json.loads(str(row["stream_settings"]))
    if (
        not row["enable"]
        or row["protocol"] != "vless"
        or stream.get("network") != "xhttp"
        or stream.get("security") not in (None, "", "none")
    ):
        msg = "Legacy transport drift"
        raise ValueError(msg)
    if row.get("exclude_from_sub"):
        msg = "Already withdrawn; do not replay"
        raise ValueError(msg)
    value: dict[str, object] = row
    return value


def desired(config: dict[str, object]) -> dict[str, object]:
    """Return the configuration with exactly the legacy inbound withdrawn."""
    result = copy.deepcopy(config)
    row = select(result)
    row["exclude_from_sub"] = True
    value: dict[str, object] = result
    return value


def payload(inbound: dict[str, object], expected_id: str) -> dict[str, object]:
    """Validate and return the native API write body retiring one legacy inbound."""
    obj = copy.deepcopy(inbound)
    stream = target.json_field(obj.get("streamSettings"))
    if (
        obj.get("id") != expected_id
        or obj.get("port") != LEGACY_PORT
        or obj.get("protocol") != "vless"
        or obj.get("enable") is not True
        or obj.get("excludeFromSub")
        or stream.get("network") != "xhttp"
        or stream.get("security") not in (None, "", "none")
    ):
        msg = "API preimage drift"
        raise ValueError(msg)
    obj["excludeFromSub"] = True
    obj.pop("clientStats", None)
    value: dict[str, object] = obj
    return value


def normalize(body: bytes) -> list[str]:
    """Return the sorted, canonicalized vless subscription links from one response."""
    text = body.decode("utf-8").strip()
    if "://" not in text:
        text = base64.b64decode(text + "=" * (-len(text) % 4), validate=True).decode("utf-8")
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parsed = urllib.parse.urlsplit(line)
        if not parsed.scheme or "://" not in line:
            msg = "Unexpected subscription format"
            raise ValueError(msg)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if ("security", "reality") in query:
            query = [(k, v) for k, v in query if k != "sid"]
        result.append(
            urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(sorted(query))))
        )
    if not result:
        msg = "Empty subscription"
        raise ValueError(msg)
    return sorted(result)


def normalize_json(value: object) -> object:
    """Strip REALITY short_ids from a polar-side json subscription document."""
    if isinstance(value, dict):
        out = {k: normalize_json(v) for k, v in value.items()}
        reality = out.get("realitySettings")
        if isinstance(reality, dict):
            reality.pop("shortId", None)
        return out
    if isinstance(value, list):
        return [normalize_json(v) for v in value]
    return value


def _settings_mentions(settings: object, port: int) -> bool:
    """Tell whether one outbound settings block still references the legacy port."""
    if not isinstance(settings, dict):
        return False
    if settings.get("port") == port:
        return True
    vnext = settings.get("vnext", [])
    return isinstance(vnext, list) and any(
        isinstance(v, dict) and v.get("port") == port for v in vnext
    )


def json_legacy(config: object) -> bool:
    """Tell whether one polar json profile still targets the legacy port."""
    if not isinstance(config, dict):
        return False
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        return False
    return any(
        isinstance(o, dict)
        and o.get("protocol") == "vless"
        and isinstance(o.get("settings"), dict)
        and _settings_mentions(o["settings"], LEGACY_PORT)
        for o in outbounds
    )


def is_legacy(uri: object) -> bool:
    """Tell whether one published link still targets the withdrawn plaintext port."""
    if not isinstance(uri, str):
        return False
    parsed = urllib.parse.urlsplit(uri)
    return bool(parsed.scheme == "vless" and parsed.port == LEGACY_PORT)


def snapshot(
    database: Path,
    state: Path,
    phase: str,
    *,
    json_format: bool = False,
    exclude_client_ids: tuple[object, ...] = (),
) -> dict[str, list[object]]:
    """Snapshot every enabled client subscription from both publication frontends."""
    directory = h.private_directory(state / phase)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as c:
        settings = dict(c.execute("SELECT key,value FROM settings"))
        rows = c.execute("SELECT id,sub_id FROM clients WHERE enable=1 ORDER BY id").fetchall()
        rows = [row for row in rows if row[0] not in exclude_client_ids]
    if (
        int(settings["subPort"]) != SUBSCRIPTION_PORT
        or settings.get("subListen", "") not in LISTEN_ALLOWLIST
    ):
        msg = "Subscription listener drift"
        raise ValueError(msg)
    prefix = settings["subJsonPath" if json_format else "subPath"]
    if not prefix.startswith("/") or any(x in prefix for x in ("?", "#", "..", "\\")):
        msg = "Unsafe subscription path"
        raise ValueError(msg)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), native.NoRedirect())
    result: dict[str, list[object]] = {}
    for client_id, sub_id in rows:
        if not sub_id:
            msg = "Missing enabled subscription"
            raise ValueError(msg)
        suffix = "/" + prefix.strip("/") + "/" + urllib.parse.quote(sub_id, safe="")
        pair: list[list[object]] = []
        for label, origin in [
            ("backend", BACKEND_ORIGIN),
            ("public", PUBLIC_ORIGIN),
        ]:
            url = origin + suffix
            if urllib.parse.urlsplit(url).scheme not in ALLOWED_URL_SCHEMES:
                msg = "Unexpected subscription origin"
                raise ValueError(msg)
            req = urllib.request.Request(
                url,
                headers={
                    "Host": PUBLIC_HOST,
                    "User-Agent": "homelab-subscription-migration/1",
                },
            )
            with opener.open(req, timeout=12) as r:
                body = r.read(MAX_SUBSCRIPTION_BYTES + 1)
                if r.status != HTTP_OK or len(body) > MAX_SUBSCRIPTION_BYTES:
                    msg = "Subscription response refused"
                    raise ValueError(msg)
            links = normalize_json(json.loads(body)) if json_format else normalize(body)
            if not isinstance(links, list) or not links:
                msg = "Empty publication"
                raise ValueError(msg)
            h.save(directory / (str(client_id) + "-" + label + "-private.json"), links)
            pair.append(links)
        if pair[0] != pair[1]:
            msg = "Public/backend mismatch"
            raise ValueError(msg)
        result[str(client_id)] = pair[0]
    return result


def check_delta(
    before: dict[str, list[object]], after: dict[str, list[object]]
) -> dict[str, object]:
    """Require the population change to be exactly the seven legacy withdrawals."""
    if set(before) != set(after):
        msg = "Identity set changed"
        raise ValueError(msg)
    affected = 0
    removed = 0
    for key, links in before.items():
        expected = [uri for uri in links if not is_legacy(uri)]
        legacy = len(links) - len(expected)
        if legacy:
            affected += 1
            removed += legacy
            if not any(
                urllib.parse.urlsplit(str(u)).scheme == "vless"
                and dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(str(u)).query)).get(
                    "security"
                )
                == "reality"
                for u in expected
            ):
                msg = "Missing published REALITY replacement"
                raise ValueError(msg)
        if after[key] != expected:
            msg = "Unexpected subscription change"
            raise ValueError(msg)
    if affected != EXPECTED_AFFECTED or removed != EXPECTED_AFFECTED:
        msg = "Affected population drift"
        raise ValueError(msg)
    return {
        "identities": len(before),
        "affected": affected,
        "plaintext_links_removed": removed,
        "remaining_published_entries": sum(len(v) for v in after.values()),
        "unrelated_profiles_preserved": True,
    }


class _PanelSession(Protocol):
    """Native panel session surface this migration reads and writes through."""

    state: Path
    database: Path

    def open(self, wanted: str) -> None:
        """Open the session pinned by its approved hash."""
        ...

    def call(self, *args: object) -> list[dict[str, object]]:
        """Call one native panel API method."""
        ...

    def cleanup(self) -> None:
        """Release the session's temporary runtime state."""
        ...


def _replacement_gate(config: dict[str, object]) -> dict[str, object]:
    """Require the legacy port to have exactly one entry with full replacements."""
    summary = h.summarize(config)
    row: dict[str, object] = next(r for r in summary["inbounds"] if r["port"] == LEGACY_PORT)
    if (
        row["client_links"] != EXPECTED_AFFECTED
        or row["links_with_existing_enabled_encrypted_alternative"] != EXPECTED_AFFECTED
    ):
        msg = "Replacement gate failed"
        raise ValueError(msg)
    return row


def _approve_plan_hashes(
    s: _PanelSession,
    original: dict[str, object],
    legacy: dict[str, object],
    session_hash: str,
    config_hash: str,
) -> None:
    """Bind the write session to fresh exact configuration and session approvals."""
    if h.digest(original) != config_hash:
        msg = "Fresh config approval required"
        raise ValueError(msg)
    _replacement_gate(original)
    s.open(session_hash)
    if target.semantic(target.configuration(s.database)) != target.semantic(original):
        msg = "Config changed opening session"
        raise ValueError(msg)
    h.save(s.state / "proxy-before-private.json", original)
    before = snapshot(s.database, s.state, "subscriptions-before")
    json_before = snapshot(s.database, s.state, "json-before", json_format=True)
    if set(json_before) != set(before):
        msg = "JSON identity mismatch"
        raise ValueError(msg)
    if sum(sum(json_legacy(v) for v in rows) for rows in json_before.values()) != EXPECTED_AFFECTED:
        msg = "JSON population drift"
        raise ValueError(msg)
    # Verify exact publication diff prospectively, before making any write.
    prospective = {key: [u for u in links if not is_legacy(u)] for key, links in before.items()}
    check_delta(before, prospective)
    _single_listener_row(s, legacy)


def _single_listener_row(s: _PanelSession, legacy: dict[str, object]) -> None:
    """Pin the native API inbound and verify DB/API fields still agree."""
    rows = s.call("GET", "/inbounds/list")
    matches = [r for r in rows if r["id"] == legacy["id"]]
    if len(matches) != 1:
        msg = "Missing native inbound"
        raise ValueError(msg)
    for api_key, db_key in [
        ("settings", "settings"),
        ("streamSettings", "stream_settings"),
        ("sniffing", "sniffing"),
    ]:
        if target.json_field(matches[0][api_key]) != target.json_field(legacy[db_key]):
            msg = "API/DB drift"
            raise ValueError(msg)


def _await_retained_listener() -> None:
    """Confirm the cached-client listener is still answering, without artificial waits."""
    for attempt in range(LISTENER_ATTEMPTS):
        try:
            with socket.create_connection(("127.0.0.1", LEGACY_PORT), timeout=1):
                break
        except OSError:
            if attempt == LISTENER_ATTEMPTS - 1:
                raise
            time.sleep(0.5)


def apply(state: Path, session_hash: str, config_hash: str) -> dict[str, object]:
    """Withdraw the plaintext inbound once, then prove both frontends and listener state."""
    s = native.NativeSession(state)
    original = target.configuration(s.database)
    legacy = select(original)
    _approve_plan_hashes(s, original, legacy, session_hash, config_hash)
    try:
        before = snapshot(s.database, s.state, "subscriptions-before")
        json_before = snapshot(s.database, s.state, "json-before", json_format=True)
        pre = target.configuration(s.database)
        rows = s.call("GET", "/inbounds/list")
        matches = [r for r in rows if r["id"] == legacy["id"]]
        if len(matches) != 1:
            msg = "Missing native inbound"
            raise ValueError(msg)
        dto = payload(matches[0], str(legacy["id"]))
        if target.semantic(pre) != target.semantic(original) or target.semantic(
            target.configuration(s.database)
        ) != target.semantic(original):
            msg = "Concurrent config change"
            raise ValueError(msg)
        h.save(
            s.state / "subscription-write-uncertain.json",
            {
                "field": "excludeFromSub",
                "inbound_id": legacy["id"],
                "old": False,
                "new": True,
            },
        )
        s.call("POST", "/inbounds/update/" + str(legacy["id"]), dto)
        current = target.configuration(s.database)
        h.save(s.state / "proxy-after-private.json", current)
        if target.semantic(current) != target.semantic(desired(original)):
            msg = "Unexpected native write delta"
            raise ValueError(msg)
        after = snapshot(s.database, s.state, "subscriptions-after")
        proof = check_delta(before, after)
        json_after = snapshot(s.database, s.state, "json-after", json_format=True)
        if set(json_before) != set(json_after):
            msg = "JSON identity set changed"
            raise ValueError(msg)
        for key, rows in json_before.items():
            if json_after[key] != [v for v in rows if not json_legacy(v)]:
                msg = "Unexpected JSON publication delta"
                raise ValueError(msg)
        proof["json_subscriptions_verified"] = True
        # Listener deliberately remains enabled; no artificial device acceptance.
        _await_retained_listener()
        proof.update(
            {
                "only_exclude_from_sub_changed": True,
                "legacy_listener_retained": True,
                "client_credentials_and_bindings_preserved": True,
                "owner_coordinates_device_refresh": True,
                "end_device_acceptance_claimed": False,
                "audit_get_is_not_device_refresh": True,
            }
        )
        h.save(s.state / "publication-acceptance.json", proof)
        (s.state / "subscription-write-uncertain.json").unlink()
    finally:
        s.cleanup()
    proof["temporary_credentials_removed"] = True
    h.save(s.state / "receipt.json", proof)
    return proof


def main() -> None:
    """Preview the withdrawal hashes, or apply them under fresh approvals."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-session-hash")
    p.add_argument("--approve-configuration-hash")
    a = p.parse_args()
    if a.apply:
        if not a.approve_session_hash or not a.approve_configuration_hash:
            p.error("Both fresh hashes required")
        print(h.canonical(apply(a.state, a.approve_session_hash, a.approve_configuration_hash)))
    else:
        s = native.NativeSession(a.state)
        plan = s.preview()
        config = target.configuration(s.database)
        select(config)
        print(
            h.canonical(
                {
                    "session_sha256": h.digest(plan),
                    "configuration_sha256": h.digest(config),
                    "only_change": "32063 excludeFromSub false->true",
                    "listener_retirement": False,
                    "writes": 0,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, ImportError, sqlite3.Error):
        msg = "Subscription migration stopped; inspect private receipts, never blindly replay."
        raise SystemExit(msg) from None
