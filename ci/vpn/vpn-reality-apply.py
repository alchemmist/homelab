#!/usr/bin/env python3
"""One explicit native API target correction with a synthetic VLESS acceptance client.

No listener retirement/firewall update/SQL mutation or human credential use.
Preview is read-only. Apply requires both fresh hashes and private node state.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import sqlite3
import ssl
import subprocess
import time
import types
import uuid
from contextlib import closing
from pathlib import Path
from typing import NamedTuple, Protocol, TextIO

# One raw proxy row and one whole projected database snapshot.
Row = dict[str, object]
Config = dict[str, list[Row]]

TARGET_PORT = 32053
DECLARED_SNI = "www.yahoo.com"
WRONG_TARGET = "www.intel.com:443"
CORRECTED_TARGET = "www.yahoo.com:443"
TRANSFER_URL = "https://speed.cloudflare.com/__down?bytes=65536"
TRANSFER_BYTES = 65536
TRANSFER_LIMIT_BYTES = 131072
CURL_MAX_TIME = 25
CURL_TIMEOUT = 30
XRAY_BINARY = "xray-linux-amd64"
CONFIG_MARKER = b"bin/config.json"
READINESS_ATTEMPTS = 40
READINESS_INTERVAL = 0.25
FALLBACK_ATTEMPTS = 40
FALLBACK_INTERVAL = 0.5
PROBE_TLS_TIMEOUT = 10
FALLBACK_TLS_TIMEOUT = 2
REQUIRED_TLS = "TLSv1.3"
REQUIRED_ALPN = "h2"
FIXTURE_QUOTA_BYTES = 10 * 1024 * 1024
FIXTURE_TTL_MS = 20 * 60000
FIXTURE_COMMENT = "owned-vpn83-temporary-acceptance"


class _Identity(NamedTuple):
    """Temporary synthetic client identity owned exclusively by this run."""

    email: str
    fixture_id: str
    sub_id: str


class _Panel(Protocol):
    """Structural surface of the native panel session consumed here."""

    state: Path
    database: Path

    def open(self, approval: str) -> object: ...

    def preview(self) -> object: ...

    def call(self, method: str, path: str, body: object = None) -> object: ...

    def cleanup(self) -> None: ...


def load(name: str, filename: str) -> types.ModuleType:
    """Load a sibling operational module by deployed-copy file name."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None or not spec.has_location:
        reason = "Cannot load helper module"
        raise ValueError(reason)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


session_module = load("panel_session", "vpn-panel-session.py")
planner = load("reality_plan", "vpn-reality-plan.py")
h = session_module.h


def configuration(database: Path) -> Config:
    """Return an integrity-checked read-only projection of the panel database."""
    with (
        closing(sqlite3.connect(h.check_path(database).as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(":memory:")) as snapshot,
    ):
        source.backup(snapshot)
        if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            msg = "Integrity check failed"
            raise ValueError(msg)
        projected = h.projection(snapshot)
    config: Config = {}
    for table, values in projected.items():
        config[table] = [dict(row) for row in values]
    return config


def semantic(config: Config) -> dict[str, list[object]]:
    """Return a canonical value-space view in which JSON formatting is not a change."""

    def normalize(value: object) -> object:
        if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
            try:
                return normalize(json.loads(value))
            except ValueError:
                pass
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value

    view: dict[str, list[object]] = {}
    for table, rows in config.items():
        view[table] = sorted([normalize(row) for row in rows], key=h.canonical)
    return view


def corrected(config: Config) -> Config:
    """Return the only expected post-update snapshot: the target destination corrected."""
    after = copy.deepcopy(config)
    rows = [r for r in after["inbounds"] if r["port"] == TARGET_PORT]
    if len(rows) != 1:
        msg = "Unexpected target count"
        raise ValueError(msg)
    raw = rows[0]["stream_settings"]
    if not isinstance(raw, str):
        reason = "Expected legacy JSON stream settings"
        raise TypeError(reason)
    stream: Row = json.loads(raw)
    reality = stream["realitySettings"]
    if not isinstance(reality, dict):
        reason = "Expected REALITY settings"
        raise TypeError(reason)
    if reality.get("serverNames") != [DECLARED_SNI] or reality.get("target") != WRONG_TARGET:
        msg = "Target/SNI drift"
        raise ValueError(msg)
    reality["target"] = CORRECTED_TARGET
    rows[0]["stream_settings"] = h.canonical(stream)
    result: Config = after
    return result


def json_field(value: object) -> object:
    """Decode legacy JSON string fields; native objects are copied verbatim."""
    # 3x-ui3.11 emits native objects; its decoder also accepts legacy JSON strings.
    if value is None or value == "":
        return None
    return json.loads(value) if isinstance(value, str) else copy.deepcopy(value)


def api_payload(inbound: Row) -> Row:
    """Return the single native update DTO: only the corrected target destination."""
    after = copy.deepcopy(inbound)
    if (
        after.get("port") != TARGET_PORT
        or after.get("protocol") != "vless"
        or not after.get("enable")
    ):
        msg = "Unexpected native inbound"
        raise ValueError(msg)
    stream_value = json_field(after["streamSettings"])
    if not isinstance(stream_value, dict):
        reason = "Expected stream settings mapping"
        raise TypeError(reason)
    if stream_value.get("security") != "reality" or stream_value.get("network") != "xhttp":
        msg = "Transport drift"
        raise ValueError(msg)
    reality = stream_value["realitySettings"]
    if not isinstance(reality, dict):
        reason = "Expected REALITY settings"
        raise TypeError(reason)
    if reality.get("serverNames") != [DECLARED_SNI] or reality.get("target") != WRONG_TARGET:
        msg = "API target drift"
        raise ValueError(msg)
    reality["target"] = CORRECTED_TARGET
    after["streamSettings"] = (
        h.canonical(stream_value) if isinstance(inbound["streamSettings"], str) else stream_value
    )
    after.pop("clientStats", None)  # Not an editable client-statistics operation.
    result: Row = after
    return result


def vless_client(stream: Row, client_id: str, port: int) -> Row:
    """Build the loopback synthetic acceptance client from public parameters only."""
    reality = stream["realitySettings"]
    if not isinstance(reality, dict):
        reason = "Expected REALITY settings"
        raise TypeError(reason)
    settings = reality.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    public = settings.get("publicKey")
    if not public or not reality.get("shortIds"):
        msg = "Missing native client parameters"
        raise ValueError(msg)
    xhttp = stream.get("xhttpSettings") or stream.get("splithttpSettings")
    if not isinstance(xhttp, dict) or "path" not in xhttp:
        msg = "Missing XHTTP path"
        raise ValueError(msg)
    short_ids = reality["shortIds"]
    if not isinstance(short_ids, list) or not short_ids:
        reason = "Expected REALITY short ids"
        raise TypeError(reason)
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
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": TARGET_PORT,
                            "users": [{"id": client_id, "encryption": "none", "flow": ""}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "xhttp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": DECLARED_SNI,
                        "fingerprint": "chrome",
                        "publicKey": public,
                        "shortId": short_ids[0],
                    },
                    "xhttpSettings": {
                        "path": xhttp["path"],
                        "mode": xhttp.get("mode", "auto"),
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


def server_executable() -> str:
    """Return the one known running server executable path, refusing ambiguity."""
    found: list[str] = []
    for path in Path("/proc").glob("[0-9]*/exe"):
        try:
            if path.readlink().name != XRAY_BINARY:
                continue
            args = (path.parent / "cmdline").read_bytes().split(b"\0")
            if any(x.endswith(CONFIG_MARKER) for x in args):
                found.append(str(path))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    if len(found) != 1:
        msg = "Expected one known running server executable"
        raise ValueError(msg)
    return found[0]


def transfer(port: int, state: Path, phase: str) -> Row:
    """Perform one authenticated cloudflare transfer through the private probe tunnel."""
    output = state / (phase + "-body.bin")
    env = dict(os.environ, NO_PROXY="", no_proxy="")
    args = [
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        str(CURL_MAX_TIME),
        "--max-filesize",
        str(TRANSFER_LIMIT_BYTES),
        "--proxy",
        "socks5h://127.0.0.1:" + str(port),
        "--output",
        str(output),
        "--write-out",
        "%{http_code} %{size_download}",
        TRANSFER_URL,
    ]
    result = subprocess.run(
        args, check=False, capture_output=True, text=True, env=env, timeout=CURL_TIMEOUT
    )
    h.save(
        state / (phase + "-curl-private.json"),
        {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    if (
        result.returncode
        or result.stdout.strip() != "200 " + str(TRANSFER_BYTES)
        or not output.is_file()
        or output.stat().st_size != TRANSFER_BYTES
    ):
        msg = "Authenticated transfer failed; inspect private evidence"
        raise RuntimeError(msg)
    proof: Row = {
        "http_status": 200,
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "native_authenticated_tunnel": True,
        "vantage": "same-node-synthetic-not-Russian-ISP",
    }
    output.unlink()
    h.save(state / (phase + "-proof.json"), proof)
    return proof


def _candidate_tls_gate() -> None:
    """Require the corrected public candidate destination to still serve TLS1.3/H2."""
    context = ssl.create_default_context()
    context.set_alpn_protocols([REQUIRED_ALPN])
    with (
        socket.create_connection((DECLARED_SNI, 443), timeout=PROBE_TLS_TIMEOUT) as raw,
        context.wrap_socket(raw, server_hostname=DECLARED_SNI) as tls,
    ):
        if tls.version() != REQUIRED_TLS or tls.selected_alpn_protocol() != REQUIRED_ALPN:
            msg = "Candidate failed TLS/H2"
            raise ValueError(msg)


def _fallback_gate() -> None:
    """Wait only on real local fallback readiness, not repeated external transfers."""
    for attempt in range(FALLBACK_ATTEMPTS):
        try:
            context = ssl.create_default_context()
            context.set_alpn_protocols([REQUIRED_ALPN])
            with (
                socket.create_connection(
                    ("127.0.0.1", TARGET_PORT), timeout=FALLBACK_TLS_TIMEOUT
                ) as raw,
                context.wrap_socket(raw, server_hostname=DECLARED_SNI) as tls,
            ):
                if tls.version() != REQUIRED_TLS or tls.selected_alpn_protocol() != REQUIRED_ALPN:
                    msg = "Fallback TLS/H2 failed"
                    raise ValueError(msg)
        except (OSError, ssl.SSLError) as exc:
            if attempt == FALLBACK_ATTEMPTS - 1:
                msg = "Fallback never converged"
                raise RuntimeError(msg) from exc
            time.sleep(FALLBACK_INTERVAL)
        else:
            return


def _single_target(original: Config) -> Row:
    """Return the sole Reality target inbound of the projected proxy."""
    matches = [r for r in original["inbounds"] if r["port"] == TARGET_PORT]
    if len(matches) != 1:
        msg = "Projected target missing"
        raise ValueError(msg)
    return matches[0]


def _recent_or_stop(panel: _Panel, original: Config, message: str) -> None:
    """Fail closed unless the private database still matches the preapproved snapshot."""
    if semantic(configuration(panel.database)) != semantic(original):
        raise ValueError(message)


def _fixture_gate(panel: _Panel, identity: _Identity) -> None:
    """Refuse to start when our fixture identity collides with any existing client."""
    with closing(sqlite3.connect(panel.database.as_uri() + "?mode=ro", uri=True)) as con:
        if con.execute(
            "SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?",
            identity,
        ).fetchone()[0]:
            msg = "Fixture collision"
            raise ValueError(msg)


def _add_acceptance_client(panel: _Panel, inbound_id: object, identity: _Identity) -> None:
    """Create the one temporary synthetic client bound to the target inbound."""
    panel.call(
        "POST",
        "/clients/add",
        {
            "client": {
                "id": identity.fixture_id,
                "email": identity.email,
                "subId": identity.sub_id,
                "password": secrets.token_urlsafe(24),
                "security": "auto",
                "flow": "",
                "enable": True,
                "limitIp": 1,
                "totalGB": FIXTURE_QUOTA_BYTES,
                "expiryTime": int(time.time() * 1000) + FIXTURE_TTL_MS,
                "comment": FIXTURE_COMMENT,
            },
            "inboundIds": [inbound_id],
        },
    )


def _reserve_probe_port() -> int:
    """Reserve one loopback port for the synthetic acceptance client."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _start_probe(
    panel: _Panel, executable: str, target: Row, fixture_id: str
) -> tuple[subprocess.Popen[bytes], TextIO, int]:
    """Start the private acceptance client and return its process, private log and port."""
    port = _reserve_probe_port()
    raw = target["stream_settings"]
    if not isinstance(raw, str):
        reason = "Expected legacy JSON stream settings"
        raise TypeError(reason)
    cfg = vless_client(json.loads(raw), fixture_id, port)
    h.save(panel.state / "probe-client-private.json", cfg)
    log = (panel.state / "probe-client-private.log").open("x")
    chmod_target = Path(log.name)
    chmod_target.chmod(0o600)
    proc = subprocess.Popen(
        [executable, "run", "-c", str(panel.state / "probe-client-private.json")],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc, log, port


def _await_probe_ready(port: int, proc: subprocess.Popen[bytes]) -> None:
    """Wait until the private acceptance client accepts local connections."""
    for _ in range(READINESS_ATTEMPTS):
        if proc.poll() is not None:
            msg = "Private acceptance client exited"
            raise RuntimeError(msg)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(READINESS_INTERVAL)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop the private acceptance client, escalating once after a bounded wait."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _api_rows(panel: _Panel, path: str, target_id: object) -> Row:
    """Return the native API row with exactly the given inbound id."""
    rows = panel.call("GET", path)
    if not isinstance(rows, list):
        reason = "Expected native API list"
        raise TypeError(reason)
    matches = [dict(row) for row in rows if row["id"] == target_id]
    if len(matches) != 1:
        msg = "Native API target missing"
        raise ValueError(msg)
    result: Row = matches[0]
    return result


def _gate_native_preimage(panel: _Panel, target_id: object, target_hash: str) -> Config:
    """Verify the API/DB preimage, then perform the only native write."""
    before_api = configuration(panel.database)
    api_row = _api_rows(panel, "/inbounds/list", target_id)
    payload = api_payload(api_row)
    prewrite = configuration(panel.database)
    if semantic(before_api) != semantic(prewrite):
        msg = "Concurrent config change during API read"
        raise ValueError(msg)
    db_target_rows = [r for r in prewrite["inbounds"] if r["id"] == target_id]
    if len(db_target_rows) != 1:
        msg = "Projected target missing"
        raise ValueError(msg)
    for api_key, db_key in (
        ("settings", "settings"),
        ("streamSettings", "stream_settings"),
        ("sniffing", "sniffing"),
    ):
        if json_field(api_row[api_key]) != json_field(db_target_rows[0][db_key]):
            msg = "API/DB projection mismatch"
            raise ValueError(msg)
    h.save(panel.state / "proxy-prewrite-private.json", prewrite)
    h.save(panel.state / "target-write-uncertain.json", {"target_plan_sha256": target_hash})
    # Only one native write. An ambiguous response is not automatically retried.
    panel.call("POST", "/inbounds/update/" + str(target_id), payload)
    return prewrite


def _create_fixture(panel: _Panel, original: Config, plan: Row, identity: _Identity) -> Row:
    """Record the owned synthetic identity for the target inbound before any write."""
    _recent_or_stop(panel, original, "Proxy changed while opening session")
    h.save(panel.state / "target-plan.json", plan)
    h.save(panel.state / "proxy-before-private.json", original)
    _fixture_gate(panel, identity)
    target = _single_target(original)
    h.save(
        panel.state / "fixture-private.json",
        {
            "email": identity.email,
            "uuid": identity.fixture_id,
            "sub_id": identity.sub_id,
            "inbound_id": target["id"],
        },
    )
    return target


def _remove_fixture(panel: _Panel, identity: _Identity) -> None:
    """Delete the synthetic client only when it is still exactly ours."""
    with closing(sqlite3.connect(panel.database.as_uri() + "?mode=ro", uri=True)) as con:
        rows = con.execute(
            "SELECT uuid,sub_id FROM clients WHERE email=?", (identity.email,)
        ).fetchall()
    if rows:
        if rows != [identity[1:]]:
            msg = "Fixture ownership mismatch"
            raise ValueError(msg)
        panel.call("POST", "/clients/del/" + identity.email, {})
    with closing(sqlite3.connect(panel.database.as_uri() + "?mode=ro", uri=True)) as con:
        if con.execute("SELECT COUNT(*) FROM clients WHERE email=?", (identity.email,)).fetchone()[
            0
        ]:
            msg = "Fixture cleanup incomplete"
            raise ValueError(msg)


def apply(state: Path, policy: Row, session_hash: str, target_hash: str) -> Row:
    """Correct the one Reality target end to end and return the private receipt."""
    reality = policy["realityCorrection"]
    if not isinstance(reality, dict):
        reason = "Explicit apply policy required"
        raise TypeError(reason)
    if reality.get("apiApplyEnabled") is not True:
        msg = "API apply is disabled by source policy"
        raise ValueError(msg)
    panel: _Panel = session_module.NativeSession(state)
    original = configuration(panel.database)
    plan = planner.build(original, policy)
    operations = plan["operations"]
    if not isinstance(operations, list):
        reason = "Expected planned operations"
        raise TypeError(reason)
    if plan["plan_sha256"] != target_hash or len(operations) != 1:
        msg = "Target approval drift"
        raise ValueError(msg)
    # Candidate must be validated before credentials or client state are written.
    _candidate_tls_gate()
    executable = server_executable()
    identity = _Identity(panel.state.name + "-probe", str(uuid.uuid4()), secrets.token_hex(12))
    fixture = False
    proc: subprocess.Popen[bytes] | None = None
    log: TextIO | None = None
    applied = False
    before: Row = {}
    panel.open(session_hash)
    try:
        target = _create_fixture(panel, original, plan, identity)
        # Mark intent before an API response can be lost; cleanup ownership-checks DB.
        fixture = True
        _add_acceptance_client(panel, target["id"], identity)
        proc, log, port = _start_probe(panel, executable, target, identity.fixture_id)
        _await_probe_ready(port, proc)
        time.sleep(1)
        before = transfer(port, panel.state, "before")
        # Fresh native DTO plus complete config preimage after our own fixture.
        prewrite = _gate_native_preimage(panel, target["id"], target_hash)
        _confirm_waiting(panel, prewrite, port, before)
        applied = True
    finally:
        if proc is not None:
            _terminate(proc)
        if log is not None:
            log.close()
        try:
            if fixture:
                _remove_fixture(panel, identity)
        finally:
            panel.cleanup()
    return _final_preservation(panel, original, applied=applied)


def _confirm_waiting(panel: _Panel, prewrite: Config, port: int, before: Row) -> None:
    """Confirm the correction with the retained pre-update transfer evidence."""
    expected = corrected(prewrite)
    if semantic(configuration(panel.database)) != semantic(expected):
        msg = "Unexpected API normalization/drift; inspect private data"
        raise RuntimeError(msg)
    _fallback_gate()
    after = transfer(port, panel.state, "after")
    h.save(
        panel.state / "target-acceptance.json",
        {
            "target_corrected": True,
            "fallback_verified": True,
            "before": before,
            "after": after,
            "only_expected_config_change": True,
        },
    )
    (panel.state / "target-write-uncertain.json").unlink()


def _final_preservation(panel: _Panel, original: Config, *, applied: bool) -> Row:
    """Verify closed-state preservation, then write and return the receipt."""
    final = configuration(panel.database)
    expected = corrected(original) if applied else original
    h.save(panel.state / "proxy-after-private.json", final)
    if semantic(final) != semantic(expected):
        msg = "Final proxy preservation check failed"
        raise RuntimeError(msg)
    receipt: Row = {
        "target_corrected": applied,
        "fixture_removed": True,
        "temporary_credentials_removed": True,
        "existing_credentials_preserved": True,
        "only_target_changed": True,
        "human_credentials_used": False,
        "russian_isp_acceptance": False,
        "plaintext_retired": False,
        "raw_backends_enforced": False,
    }
    h.save(panel.state / "receipt.json", receipt)
    return receipt


def main() -> None:
    """Run the read-only preview or the fully approved single-target apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-session-hash")
    parser.add_argument("--approve-target-plan-hash")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    if args.apply:
        if not args.approve_session_hash or not args.approve_target_plan_hash:
            parser.error("Both fresh hashes required")
        receipt = apply(
            args.state, policy, args.approve_session_hash, args.approve_target_plan_hash
        )
        print(h.canonical(receipt))
    else:
        preview_session: _Panel = session_module.NativeSession(args.state)
        plan = preview_session.preview()
        target = planner.build(configuration(preview_session.database), policy)
        print(
            h.canonical(
                {
                    "session_sha256": h.digest(plan),
                    "target_plan_sha256": target["plan_sha256"],
                    "target_operations": target["operations"],
                    "writes": 0,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        RuntimeError,
        ImportError,
        TypeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ):
        msg = (
            "Target operation stopped; inspect private receipts before retrying. "
            "No automatic replay."
        )
        raise SystemExit(msg) from None
