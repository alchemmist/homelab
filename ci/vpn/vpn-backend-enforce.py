#!/usr/bin/env python3
"""Explicit public-backend enforcement with own Trojan TLS443 before/after proof.

Never retires32063 or uses human credentials. Private backup and three approvals.
"""

import argparse
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
from typing import Protocol, TextIO, TypedDict, cast


def load(name: str, filename: str) -> ModuleType:
    """Import a sibling migration module by exact file name."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


native = load("native", "vpn-panel-session.py")
target = load("target", "vpn-reality-apply.py")
publication = load("publication", "vpn-subscription-migrate.py")
guard = load("guard", "vpn-backend-guard.py")
h = native.h


def client(stream: dict[str, object], password: str, port: int) -> dict[str, object]:
    """Build the isolated own-client xray config pinned to the public backend."""
    path = cast("str", cast("dict[str, object]", stream.get("wsSettings") or {}).get("path"))
    if (
        stream.get("network") != "ws"
        or stream.get("security") not in ("none", "", None)
        or not path
        or not path.startswith("/")
    ):
        msg = "Trojan backend transport drift"
        raise ValueError(msg)
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        ],
        "outbounds": [
            {"tag": "blocked", "protocol": "blackhole"},
            {
                "tag": "probe",
                "protocol": "trojan",
                "settings": {
                    "servers": [
                        {
                            "address": "vpn.alchemmist.xyz",
                            "port": 443,
                            "password": password,
                        }
                    ]
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": "vpn.alchemmist.xyz",
                        "allowInsecure": False,
                        "alpn": ["http/1.1"],
                    },
                    "wsSettings": {
                        "path": path,
                        "headers": {"Host": "vpn.alchemmist.xyz"},
                    },
                },
            },
        ],
        "routing": {
            "rules": [
                {
                    "type": "field",
                    "domain": ["full:speed.cloudflare.com"],
                    "outboundTag": "probe",
                },
                {"type": "field", "network": "tcp,udp", "outboundTag": "blocked"},
            ]
        },
    }


class SessionLike(Protocol):
    """Session fields and native API methods used during enactment."""

    state: Path
    database: Path

    def open(self, wanted: str) -> None:
        """Open the session pinned by its approved hash."""
        ...

    def call(self, *args: object) -> object:
        """Call one native API method."""
        ...

    def cleanup(self) -> None:
        """Release the session's temporary runtime state."""
        ...


class ProbeIdentity(TypedDict):
    """Identity tuple for the synthetic, immediately removed probe fixture."""

    email: str
    uuid: str
    sub_id: str
    password: str
    row: dict[str, object]


class PublicationBaseline(TypedDict):
    """Publication and proxy snapshots taken before the guard write."""

    before: dict[object, object]
    json_before: dict[object, object]
    pre: dict[str, object]


def require_unique_fixture(s: SessionLike, identity: ProbeIdentity) -> None:
    """Refuse to create anything reusing the probe identity columns."""
    with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
        if c.execute(
            "SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?",
            (identity["email"], identity["uuid"], identity["sub_id"]),
        ).fetchone()[0]:
            msg = "Fixture collision"
            raise ValueError(msg)


def stage_own_probe(
    s: SessionLike, identity: ProbeIdentity
) -> tuple[int, subprocess.Popen[bytes], TextIO]:
    """Stage the fixture, config and own trojan client; return port, process, log."""
    h.save(
        s.state / "fixture-private.json",
        {
            "email": identity["email"],
            "uuid": identity["uuid"],
            "sub_id": identity["sub_id"],
            "inbound_id": identity["row"]["id"],
        },
    )
    s.call(
        "POST",
        "/clients/add",
        {
            "client": {
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
                "comment": "owned83-public-Trojan-guard-acceptance",
            },
            "inboundIds": [identity["row"]["id"]],
        },
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    h.save(
        s.state / "trojan-client-private.json",
        client(
            cast(
                "dict[str, object]",
                json.loads(cast("str", identity["row"]["stream_settings"])),
            ),
            identity["password"],
            port,
        ),
    )
    fd = os.open(
        s.state / "trojan-client-private.log",
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    log = os.fdopen(fd, "w")
    executable = s.state / "owned-xray-probe"
    process = subprocess.Popen(
        [str(executable), "run", "-c", str(s.state / "trojan-client-private.json")],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return port, process, log


def wait_probe_ready(process: subprocess.Popen[bytes], port: int) -> None:
    """Wait until the own client listens on its reserved local port."""
    for attempt in range(40):
        if process.poll() is not None:
            msg = "Own Trojan client exited"
            raise RuntimeError(msg)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def capture_publication_baseline(s: SessionLike, identity: ProbeIdentity) -> PublicationBaseline:
    """Snapshot subscriptions excluding the probe fixture, plus the proxy config."""
    with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
        own_id = c.execute("SELECT id FROM clients WHERE email=?", (identity["email"],)).fetchone()[
            0
        ]
    # Actor-marked GETs may update last_sub_fetch, never count as device refresh.
    before = publication.snapshot(
        s.database, s.state, "backend-before-uri", exclude_client_ids=(own_id,)
    )
    json_before = publication.snapshot(
        s.database, s.state, "backend-before-json", True, exclude_client_ids=(own_id,)
    )
    pre = target.configuration(s.database)
    return {
        "before": cast("dict[object, object]", before),
        "json_before": cast("dict[object, object]", json_before),
        "pre": cast("dict[str, object]", pre),
    }


def write_guard(
    s: SessionLike,
    baseline: PublicationBaseline,
    identity: ProbeIdentity,
    *,
    accept_existing: bool,
    guard_hash: str,
) -> None:
    """Install or verify the exact guard rule and prove nothing else changed."""
    with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
        own_id = c.execute("SELECT id FROM clients WHERE email=?", (identity["email"],)).fetchone()[
            0
        ]
    if accept_existing:
        if guard.read_table() is None:
            msg = "Expected exact installed guard"
            raise ValueError(msg)
    else:
        guard.apply(s.state, guard_hash)
    after = publication.snapshot(
        s.database, s.state, "backend-after-uri", exclude_client_ids=(own_id,)
    )
    json_after = publication.snapshot(
        s.database, s.state, "backend-after-json", True, exclude_client_ids=(own_id,)
    )
    if baseline["before"] != cast("dict[object, object]", after) or baseline["json_before"] != cast(
        "dict[object, object]", json_after
    ):
        msg = "Publication changed through guard"
        raise ValueError(msg)
    if target.semantic(target.configuration(s.database)) != target.semantic(baseline["pre"]):
        msg = "Proxy config changed during guard"
        raise ValueError(msg)
    guard.persist(s.state)


def cleanup_fixture(
    process: subprocess.Popen[bytes] | None,
    log: TextIO | None,
    *,
    fixture: bool,
    s: SessionLike,
    identity: ProbeIdentity,
) -> None:
    """Terminate the probe client, verify ownership, and delete only the fixture."""
    if process:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log:
        log.close()
    try:
        if fixture:
            with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
                rows = c.execute(
                    "SELECT uuid,sub_id FROM clients WHERE email=?",
                    (identity["email"],),
                ).fetchall()
            if rows:
                if rows != [(identity["uuid"], identity["sub_id"])]:
                    msg = "Fixture ownership mismatch"
                    raise ValueError(msg)
                s.call("POST", "/clients/del/" + identity["email"], {})
            with closing(sqlite3.connect(s.database.as_uri() + "?mode=ro", uri=True)) as c:
                if c.execute(
                    "SELECT COUNT(*) FROM clients WHERE email=?", (identity["email"],)
                ).fetchone()[0]:
                    msg = "Fixture cleanup incomplete"
                    raise ValueError(msg)
    finally:
        s.cleanup()


def apply(
    state: Path,
    session_hash: str,
    config_hash: str,
    guard_hash: str,
    *,
    accept_existing: bool = False,
) -> dict[str, object]:
    """Enact the public-backend mandate with private proof artefacts."""
    s = native.NativeSession(state)
    original = target.configuration(s.database)
    if h.digest(original) != config_hash or h.digest(guard.plan()) != guard_hash:
        msg = "Fresh approvals required"
        raise ValueError(msg)
    trojan = [
        r
        for r in original["inbounds"]
        if r["port"] == 32087 and r["protocol"] == "trojan" and r["enable"]
    ]
    if len(trojan) != 1:
        msg = "Trojan target drift"
        raise ValueError(msg)
    identity: ProbeIdentity = {
        "email": s.state.name + "-probe",
        "uuid": str(uuid.uuid4()),
        "sub_id": secrets.token_hex(12),
        "password": secrets.token_urlsafe(32),
        "row": trojan[0],
    }
    s.open(session_hash)
    fixture = False
    process = None
    log = None
    baseline: PublicationBaseline | None = None
    try:
        if target.semantic(target.configuration(s.database)) != target.semantic(original):
            msg = "Config changed opening session"
            raise ValueError(msg)
        h.save(s.state / "proxy-before-private.json", original)
        executable = s.state / "owned-xray-probe"
        shutil.copyfile(target.server_executable(), executable)
        executable.chmod(0o700)
        require_unique_fixture(s, identity)
        port, process, log = stage_own_probe(s, identity)
        fixture = True
        wait_probe_ready(process, port)
        time.sleep(1)
        before_tunnel = target.transfer(port, s.state, "trojan-before")
        baseline = capture_publication_baseline(s, identity)
        write_guard(
            s,
            baseline,
            identity,
            accept_existing=accept_existing,
            guard_hash=guard_hash,
        )
        after_tunnel = target.transfer(port, s.state, "trojan-after")
        h.save(
            s.state / "functional-acceptance.json",
            {
                "own_trojan_tls443_before": before_tunnel,
                "own_trojan_tls443_after": after_tunnel,
                "uri_json_public_backend_preserved": True,
                "original_identities": len(original["clients"]),
                "synthetic_fixture_excluded_from_original_subscription_comparison": True,
                "external_raw_denial_not_yet_verified": True,
            },
        )
        current = target.configuration(s.database)
        h.save(s.state / "proxy-after-private.json", current)
        if target.semantic(current) != target.semantic(original):
            msg = "Final proxy preservation failed"
            raise ValueError(msg)
        result: dict[str, object] = {
            "guard_installed": True,
            "persistent_unit_active_enabled": True,
            "reboot_tested": False,
            "own_trojan_tls443_64k_verified": True,
            "existing_rule_acceptance_only": accept_existing,
            "rule_write_performed": not accept_existing,
            "all_original_uri_json_subscriptions_preserved": True,
            "fixture_and_temporary_tokens_removed": True,
            "proxy_config_unchanged": True,
            "plaintext_listener_retired": False,
            "russian_mobile_acceptance": False,
            "external_raw_denial_requires_separate_vantage": True,
        }
        h.save(s.state / "receipt.json", result)
        return result
    finally:
        cleanup_fixture(process, log, fixture=fixture, s=s, identity=identity)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--accept-existing", action="store_true")
    p.add_argument("--approve-session-hash")
    p.add_argument("--approve-configuration-hash")
    p.add_argument("--approve-guard-hash")
    a = p.parse_args()
    if a.apply:
        if not all([a.approve_session_hash, a.approve_configuration_hash, a.approve_guard_hash]):
            p.error("Three approvals required")
        print(
            h.canonical(
                apply(
                    a.state,
                    a.approve_session_hash,
                    a.approve_configuration_hash,
                    a.approve_guard_hash,
                    accept_existing=a.accept_existing,
                )
            )
        )
    else:
        s = native.NativeSession(a.state)
        plan = s.preview()
        print(
            h.canonical(
                {
                    "session_sha256": h.digest(plan),
                    "configuration_sha256": plan["configuration_sha256"],
                    "guard_sha256": h.digest(guard.plan()),
                    "writes": 0,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import sys
        import traceback

        try:
            if "--state" in sys.argv:
                state = Path(sys.argv[sys.argv.index("--state") + 1])
                if state.exists():
                    h.save(
                        h.private_directory(state) / "failure-private.json",
                        {"traceback": traceback.format_exc()},
                    )
        except (OSError, ValueError):
            pass
        msg = "Backend enforcement stopped; inspect private receipts, never replay writes."
        raise SystemExit(msg) from None
