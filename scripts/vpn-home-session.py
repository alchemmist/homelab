#!/usr/bin/env python3
"""Bounded two-phase native session for an owned cross-node home probe.
Prepare leaves TTL-limited credentials PRIVATE on VPS; controller must always clean.
No human credentials/SQL writes; no listener changes. Default read-only preview.
"""

import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypedDict, cast


def load(name: str, filename: str) -> ModuleType:
    """Import a sibling migration module by exact file name."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


native = load("native", "vpn-panel-session.py")
target = load("target", "vpn-reality-apply.py")
backend = load("backend", "vpn-backend-enforce.py")
h = native.h


def restore(state):
    if os.geteuid() != 0 or socket.gethostname() != "socrat-2":
        raise ValueError("Requires VPS root")
    s = native.NativeSession(state)
    h.private_directory(s.state)
    fd = os.open(s.state / "lock", os.O_RDWR | os.O_NOFOLLOW)
    s.lock = os.fdopen(fd, "w")
    fcntl.flock(s.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    s.original = json.loads(h.check_path(s.state / "before-tokens.json").read_text())
    s.base = native.api_path(s.database)
    for kind in ("bootstrap", "cleanup", "worker"):
        p = h.check_path(s.state / (kind + ".json"))
        if p.exists():
            s.credentials[kind] = json.loads(p.read_text())
            s._owned(kind)
    return s


class SessionLike(Protocol):
    """Session fields and native API methods used by prepare and finish."""

    state: Path
    database: Path

    def call(self, *args: object) -> object:
        """Call one native API method."""
        ...

    def cleanup(self) -> None:
        """Release the session's temporary runtime state."""
        ...


class ProbeIdentity(TypedDict):
    """Identity tuple for the temporary fixture the controller must remove."""

    email: str
    uuid: str
    sub_id: str
    password: str


class ProbeContext(TypedDict):
    """Client payload components mutated while staging the probe."""

    client: dict[str, object]
    inbound_ids: list[object]
    udp_settings: dict[str, object]


def finish(s: SessionLike) -> dict[str, object]:
    """Remove only the owned fixture and prove the proxy is pristine."""
    marker = s.state / "home-fixture-private.json"
    try:
        if marker.exists():
            owned = cast("dict[str, object]", json.loads(marker.read_text()))
            with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
                rows = c.execute(
                    "SELECT uuid,sub_id,password FROM clients WHERE email=?",
                    (owned["email"],),
                ).fetchall()
            if rows:
                if (
                    len(rows) != 1
                    or rows[0][:2] != (owned["uuid"], owned["sub_id"])
                    or hashlib.sha256(rows[0][2].encode()).hexdigest() != owned["password_sha256"]
                ):
                    raise ValueError("Home fixture ownership mismatch")
                s.call("POST", "/clients/del/" + cast("str", owned["email"]), {})
            with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
                if c.execute(
                    "SELECT COUNT(*) FROM clients WHERE email=?", (owned["email"],)
                ).fetchone()[0]:
                    raise ValueError("Fixture still exists")
    finally:
        s.cleanup()
    original = cast(
        "dict[str, object]", json.loads((s.state / "home-proxy-before-private.json").read_text())
    )
    if target.semantic(target.configuration(s.database)) != target.semantic(original):
        raise ValueError("Proxy preservation failed")
    for name in ["home-configs-private.json", "xray-probe"]:
        (s.state / name).unlink(missing_ok=True)
    proof: dict[str, object] = {
        "fixture_removed": True,
        "temporary_tokens_removed": True,
        "original_tokens_preserved": True,
        "proxy_config_preserved": True,
    }
    h.save(s.state / "home-session-cleanup-receipt.json", proof)
    return proof


def require_public_endpoint(endpoint: str) -> None:
    """Refuse any non-public probe endpoint before touching the session."""
    import ipaddress

    if not ipaddress.ip_address(endpoint).is_global:
        raise ValueError("Public probe endpoint required")


def probe_rows(original: dict[str, object]) -> dict[int, dict[str, object]]:
    """Return the configuration inbound rows keyed by listening port."""
    return {
        int(cast("int", row.get("port"))): row
        for row in cast("list[dict[str, object]]", original["inbounds"])
    }


def stage_fixture_identity(s: SessionLike, identity: ProbeIdentity) -> None:
    """Refuse identity collisions and persist the fixture receipt privately."""
    with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
        if c.execute(
            "SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?",
            (identity["email"], identity["uuid"], identity["sub_id"]),
        ).fetchone()[0]:
            raise ValueError("Fixture collision")
    h.save(
        s.state / "home-fixture-private.json",
        {
            "email": identity["email"],
            "uuid": identity["uuid"],
            "sub_id": identity["sub_id"],
            "password_sha256": hashlib.sha256(identity["password"].encode()).hexdigest(),
        },
    )


def build_probe_client(identity: ProbeIdentity) -> dict[str, object]:
    """Build the TTL-limited probe client payload bound to chosen inbounds."""
    return {
        "id": identity["uuid"],
        "email": identity["email"],
        "subId": identity["sub_id"],
        "password": identity["password"],
        "security": "auto",
        "flow": "",
        "enable": True,
        "limitIp": 1,
        "totalGB": 10 * 1024 * 1024,
        "expiryTime": int(time.time() * 1000) + 20 * 60000,
        "comment": "owned83-home-fixed-path-probe",
    }


def choose_inbound_ids(
    rows: dict[int, dict[str, object]], *, include_all_vless: bool
) -> list[object]:
    """Select the exact inbound ids the probe may attach to."""
    inbound_ids = [rows[32053]["id"], rows[32087]["id"]]
    if include_all_vless:
        for port in (32083, 32084):
            if not rows[port]["enable"]:
                raise ValueError("Additional VLESS transport unavailable")
            inbound_ids.append(rows[port]["id"])
    return inbound_ids


def add_udp_probe(
    context: ProbeContext,
    rows: dict[int, dict[str, object]],
    original: dict[str, object],
    endpoint: str,
) -> None:
    """Add the owned userspace WireGuard probe binding when requested."""
    private = subprocess.check_output(["wg", "genkey"], text=True).strip()
    public = subprocess.check_output(["wg", "pubkey"], input=private + "\n", text=True).strip()
    context["client"].update(privateKey=private, publicKey=public, allowedIPsByInbound={})
    for port, label in [(32085, "wireguard")]:
        if not rows[port]["enable"]:
            raise ValueError("UDP probe inbound unavailable")
        server = cast("dict[str, object]", json.loads(cast("str", rows[port]["settings"])))
        candidate = "10.254.83.231/32"
        if candidate in h.canonical(original):
            raise ValueError("Fixture address collision; stop")
        cast("dict[str, object]", context["client"]["allowedIPsByInbound"])[
            str(rows[port]["id"])
        ] = [candidate]
        context["inbound_ids"].append(rows[port]["id"])
        server_public = subprocess.check_output(
            ["wg", "pubkey"], input=cast("str", server["secretKey"]) + "\n", text=True
        ).strip()
        settings = dict(
            secretKey=private,
            address=[candidate],
            peers=[
                {
                    "publicKey": server_public,
                    "endpoint": endpoint + ":" + str(port),
                    "allowedIPs": ["0.0.0.0/0"],
                }
            ],
            noKernelTun=True,
            mtu=1420,
        )
        context["udp_settings"][label] = settings


def register_probe_client(s: SessionLike, context: ProbeContext) -> None:
    """Register exactly one probe client restricted to the selected inbounds."""
    s.call(
        "POST", "/clients/add", {"client": context["client"], "inboundIds": context["inbound_ids"]}
    )


def add_vless_configs(
    configs: dict[str, object],
    rows: dict[int, dict[str, object]],
    reality: dict[str, object],
) -> None:
    """Derive the extra fixed-path VLESS transports from the reality config."""
    for port in (32083, 32084):
        stream = cast("dict[str, object]", json.loads(cast("str", rows[port]["stream_settings"])))
        config = copy.deepcopy(reality)
        out = cast("dict[str, object]", cast("list[object]", config["outbounds"])[1])
        out_settings = cast("dict[str, object]", out["settings"])
        cast("dict[str, object]", cast("list[object]", out_settings["vnext"])[0])["port"] = port
        r = cast("dict[str, object]", stream["realitySettings"])
        out["streamSettings"] = {
            "network": stream["network"],
            "security": "reality",
            "realitySettings": {
                "serverName": cast("list[object]", r["serverNames"])[0],
                "fingerprint": "chrome",
                "publicKey": cast("dict[str, object]", r["settings"])["publicKey"],
                "shortId": cast("list[object]", r["shortIds"])[0],
            },
        }
        field = "grpcSettings" if stream["network"] == "grpc" else "xhttpSettings"
        cast("dict[str, object]", out["streamSettings"])[field] = copy.deepcopy(
            stream.get(field) or stream.get("splithttpSettings") or {}
        )
        configs["vless-" + str(port)] = config


def prepare(
    state: Path,
    approval: str,
    endpoint: str = "91.189.82.238",
    *,
    include_udp: bool = False,
    include_all_vless: bool = False,
) -> dict[str, object]:
    """Stage the private TTL-limited home probe; the controller must clean up."""
    require_public_endpoint(endpoint)
    s = native.NativeSession(state)
    s.open(approval)
    try:
        original = target.configuration(s.database)
        h.save(s.state / "home-proxy-before-private.json", original)
        rows = probe_rows(original)
        if not all(rows[p]["enable"] for p in (32053, 32087)):
            raise ValueError("Probe inbounds unavailable")
        identity: ProbeIdentity = {
            "email": s.state.name + "-probe",
            "uuid": str(uuid.uuid4()),
            "sub_id": secrets.token_hex(12),
            "password": secrets.token_urlsafe(32),
        }
        stage_fixture_identity(s, identity)
        context: ProbeContext = {
            "client": build_probe_client(identity),
            "inbound_ids": choose_inbound_ids(rows, include_all_vless=include_all_vless),
            "udp_settings": {},
        }
        if include_udp:
            add_udp_probe(context, rows, original, endpoint)
        register_probe_client(s, context)
        reality = target.vless_client(
            json.loads(cast("str", rows[32053]["stream_settings"])), identity["uuid"], 1080
        )
        reality["outbounds"][1]["settings"]["vnext"][0]["address"] = endpoint
        trojan = backend.client(
            json.loads(cast("str", rows[32087]["stream_settings"])), identity["password"], 1080
        )
        trojan["outbounds"][1]["settings"]["servers"][0]["address"] = endpoint
        configs: dict[str, object] = {"reality": reality, "trojan": trojan}
        if include_all_vless:
            add_vless_configs(configs, rows, cast("dict[str, object]", reality))
        for label, settings in context["udp_settings"].items():
            config = copy.deepcopy(reality)
            config["outbounds"][1] = {
                "tag": reality["outbounds"][1]["tag"],
                "protocol": label,
                "settings": settings,
            }
            configs[label] = config
        h.save(s.state / "home-configs-private.json", configs)
        executable = s.state / "xray-probe"
        shutil.copyfile(target.server_executable(), executable)
        executable.chmod(0o700)
        proof: dict[str, object] = {
            "prepared": True,
            "expires_within_minutes": 20,
            "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "controller_must_cleanup": True,
            "no_human_identity_used": True,
        }
        h.save(s.state / "home-prepare-receipt.json", proof)
        return proof
    except Exception:
        finish(s)
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--cleanup", action="store_true")
    p.add_argument("--approve-session-hash")
    p.add_argument("--endpoint", default="91.189.82.238")
    p.add_argument(
        "--include-udp", action="store_true", help="Add an owned userspace WireGuard probe binding"
    )
    p.add_argument("--include-all-vless", action="store_true")
    a = p.parse_args()
    try:
        if a.prepare:
            if not a.approve_session_hash:
                p.error("Fresh approval required")
            print(
                h.canonical(
                    prepare(
                        a.state,
                        a.approve_session_hash,
                        endpoint=a.endpoint,
                        include_udp=a.include_udp,
                        include_all_vless=a.include_all_vless,
                    )
                )
            )
        elif a.cleanup:
            print(h.canonical(finish(restore(a.state))))
        else:
            s = native.NativeSession(a.state)
            print(h.canonical({"session_sha256": h.digest(s.preview()), "writes": 0}))
    except Exception:
        raise SystemExit(
            "Home native session stopped; inspect private receipts, no blind replay."
        ) from None
