#!/usr/bin/env python3
"""Retire only excluded plaintext32063 after explicit owner cutover approval.

Update exact watchdog dependencies under its lock BEFORE native API disable.
Never delete clients/keys/bindings or stop K3s/native recovery services.
"""

import argparse
import copy
import fcntl
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import time
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
publication = load("publication", "vpn-subscription-migrate.py")
guard = load("guard", "vpn-backend-guard.py")
h = native.h
CONFIG = Path("/etc/homelab-vpn-failover/config.json")
UNIT = Path("/etc/systemd/system/monitoring-vpn.service")
TIMER = "homelab-vpn-watchdog.timer"


def run(args: list[str]) -> str:
    """Run one dependency operation, failing loudly on any nonzero exit."""
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError("Retirement dependency operation failed; inspect private receipt")
    return r.stdout


def watchdog_after(before: dict[str, object]) -> dict[str, object]:
    """Return the pre-image-exact watchdog config with the 32063 dependency removed."""
    after = copy.deepcopy(before)
    if before.get("state_dir") != "/var/lib/homelab-vpn-failover":
        raise ValueError("Unexpected watchdog state")
    endpoints = cast("list[list[str]]", after["tcp_endpoints"])
    endpoint_matches = [v for v in endpoints if v == ["127.0.0.1", 32063]]
    if len(endpoint_matches) != 1:
        raise ValueError("Watchdog preimage drift")
    endpoints.remove(endpoint_matches[0])
    ports = cast("list[dict[str, object]]", after["listen_ports"])
    primary_ports = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", after["native_unit_ports"])["homelab-vpn-primary.service"],
    )
    for items in (ports, primary_ports):
        port_matches = [v for v in items if v.get("port") == 32063 and v.get("protocol") == "tcp"]
        if len(port_matches) != 1:
            raise ValueError("Watchdog preimage drift")
        items.remove(port_matches[0])
    return after


def monitoring_after(before: str) -> str:
    """Return the monitoring unit text without the retired 32063 port."""
    old = "--ports 32087,32053,32083,32063 "
    if before.count(old) != 1:
        raise ValueError("Monitoring preimage drift")
    return before.replace(old, "--ports 32087,32053,32083 ")


def select(config: dict[str, object]) -> dict[str, object]:
    """Return the unique excluded legacy plaintext inbound; refuse any drift."""
    rows = [
        r for r in cast("list[dict[str, object]]", config["inbounds"]) if r.get("port") == 32063
    ]
    if len(rows) != 1:
        raise ValueError("Legacy count drift")
    row = rows[0]
    stream = cast("dict[str, object]", json.loads(cast("str", row["stream_settings"])))
    if (
        not row["enable"]
        or not row["exclude_from_sub"]
        or row["protocol"] != "vless"
        or stream.get("network") != "xhttp"
        or stream.get("security") not in (None, "", "none")
    ):
        raise ValueError("Not the excluded legacy plaintext inbound")
    return row


def desired(config: dict[str, object]) -> dict[str, object]:
    """Return the configuration with the legacy inbound disabled, exclusions kept."""
    result = copy.deepcopy(config)
    select(result)["enable"] = 0
    return result


def plan(state: Path) -> dict[str, object]:
    """Return the complete change plan hash material before anything is written."""
    s = native.NativeSession(state)
    session = s.preview()
    config = target.configuration(s.database)
    select(config)
    w = cast("dict[str, object]", json.loads(h.check_path(CONFIG).read_text()))
    u = h.check_path(UNIT).read_text()
    watchdog_after(w)
    monitoring_after(u)
    return {
        "session_sha256": h.digest(session),
        "configuration_sha256": h.digest(config),
        "watchdog_sha256": h.digest(w),
        "monitoring_sha256": h.digest(u),
        "only_native_change": "32063 enable true->false, exclusion retained",
        "owner_allows_cached_client_disconnect": True,
        "watchdog_dependency_removed_before_disable": True,
    }


def atomic(path: Path, content: str, mode: int) -> None:
    """Write one file atomically via an owned temp file in the same directory."""
    h.check_path(path)
    if path.stat().st_uid != 0:
        raise ValueError("Non-root-owned dependency")
    fd, name = tempfile.mkstemp(prefix=".vpn83-retire-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), mode)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def healthy() -> dict[str, object]:
    """Prove the watchdog is still the healthy Kubernetes mode, no inhibition."""
    data = cast(
        "dict[str, object]",
        json.loads(run(["python3", "/usr/local/sbin/homelab-vpn-failover", "status"])),
    )
    if data.get("mode") != "kubernetes" or not data.get("healthy") or data.get("inhibited"):
        raise ValueError("Watchdog not healthy Kubernetes mode")
    return {"mode": "kubernetes", "healthy": True, "inhibited": False}


class SessionLike(Protocol):
    """Fields and methods of the dynamic NativeSession used by the migration."""

    state: Path
    database: object

    def open(self, wanted: str) -> None:
        """Open the session pinned by the approved plan hash."""
        ...

    def call(self, *args: object) -> list[dict[str, object]]:
        """Call one native API method."""
        ...

    def cleanup(self) -> None:
        """Release the session's temporary runtime state."""
        ...


class StageEvidence(TypedDict):
    """Mutable pre-state values each staged evidence write captures."""

    wanted: dict[str, object]
    original: dict[str, object]
    w: dict[str, object]
    u: str
    approval: str


def require_vps_root() -> None:
    """Refuse any host other than the pinned VPS running as root."""
    if socket.gethostname() != "socrat-2" or os.geteuid() != 0:
        raise ValueError("Requires VPS root")


def stage_evidence(
    s: SessionLike, stage: StageEvidence
) -> tuple[dict[object, object], dict[object, object]]:
    """Persist the immutable before-state evidence; return both snapshots."""
    h.save(s.state / "retirement-plan.json", stage["wanted"])
    h.save(s.state / "proxy-before-private.json", stage["original"])
    h.save(s.state / "watchdog-before-private.json", stage["w"])
    h.save(s.state / "monitoring-before.json", stage["u"])
    before = publication.snapshot(s.database, s.state, "before-uri")
    before_json = publication.snapshot(s.database, s.state, "before-json", True)
    if any(publication.is_legacy(v) for links in before.values() for v in links):
        raise ValueError("Legacy still published")
    h.save(
        s.state / "retirement-uncertain.json",
        {"approval": stage["approval"], "dependency_writes_may_follow": True},
    )
    return (
        cast("dict[object, object]", before),
        cast("dict[object, object]", before_json),
    )


def wait_watchdog_drained() -> None:
    """Pause only future dispatch; wait for the running watchdog job to drain."""
    run(["systemctl", "stop", TIMER])
    for attempt in range(100):
        active = subprocess.run(
            ["systemctl", "is-active", "homelab-vpn-watchdog.service"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if active in ("inactive", "failed"):
            return
        if attempt == 99:
            raise RuntimeError("Existing watchdog job did not drain")
        time.sleep(0.25)


def require_recovery_quiet(w: dict[str, object], message: str) -> None:
    """Fail with the given operator message if recovery or fallback is active."""
    state_dir = Path(cast("str", w["state_dir"]))
    if (state_dir / "active").exists() or (state_dir / "inhibit").exists():
        raise ValueError(message)


def require_preimages_unchanged(s: SessionLike, stage: StageEvidence) -> None:
    """Fail if any dependency or the proxy preimage changed while waiting."""
    if (
        cast("dict[str, object]", json.loads(CONFIG.read_text())) != stage["w"]
        or UNIT.read_text() != stage["u"]
        or target.semantic(target.configuration(s.database)) != target.semantic(stage["original"])
    ):
        raise ValueError("Concurrent preimage change")


def write_dependencies(next_w: dict[str, object], next_u: str) -> None:
    """Atomically install the changed watchdog and monitoring files."""
    atomic(CONFIG, h.canonical(next_w) + "\n", 0o600)
    atomic(UNIT, next_u, 0o644)
    run(["systemd-analyze", "verify", str(UNIT)])
    run(["systemctl", "daemon-reload"])


def disable_api_inbound(
    s: SessionLike, legacy: dict[str, object], original: dict[str, object]
) -> None:
    """Perform the single supported native API disable after drift checks."""
    rows = s.call("GET", "/inbounds/list")
    matches = [r for r in rows if r["id"] == legacy["id"]]
    if len(matches) != 1:
        raise ValueError("Native inbound missing")
    dto = copy.deepcopy(matches[0])
    if dto.get("enable") is not True or not dto.get("excludeFromSub"):
        raise ValueError("API state drift")
    for api_key, db_key in [
        ("settings", "settings"),
        ("streamSettings", "stream_settings"),
        ("sniffing", "sniffing"),
    ]:
        if target.json_field(dto[api_key]) != target.json_field(legacy[db_key]):
            raise ValueError("API/DB drift")
    if target.semantic(target.configuration(s.database)) != target.semantic(original):
        raise ValueError("Proxy changed before API write")
    dto["enable"] = False
    dto.pop("clientStats", None)
    s.call(
        "POST", "/inbounds/update/" + str(legacy["id"]), dto
    )  # Exactly one supported native write, no retry.
    current = target.configuration(s.database)
    h.save(s.state / "proxy-after-private.json", current)
    if target.semantic(current) != target.semantic(desired(original)):
        raise ValueError("Unexpected native change")


def wait_port_converged() -> None:
    """Confirm the retired port stopped listening and the watchdog stayed healthy."""
    for attempt in range(60):
        if guard.read_table() is None:
            raise ValueError("Backend guard missing")
        result = subprocess.run(
            ["ss", "-Hltn", "sport = :32063"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and not result.stdout.strip():
            try:
                healthy()
            except (ValueError, RuntimeError):
                pass
            else:
                return
        if attempt == 59:
            raise RuntimeError("Retired port/runtime not converged")
        time.sleep(0.5)


def verify_publication_readback(
    s: SessionLike,
    before: dict[object, object],
    before_json: dict[object, object],
    next_w: dict[str, object],
    next_u: str,
) -> None:
    """Confirm subscriptions stayed untouched and the new files read back exactly."""
    after = publication.snapshot(s.database, s.state, "after-uri")
    after_json = publication.snapshot(s.database, s.state, "after-json", True)
    if before != cast("dict[object, object]", after) or before_json != cast(
        "dict[object, object]", after_json
    ):
        raise ValueError("Publication changed unexpectedly")
    if (
        cast("dict[str, object]", json.loads(CONFIG.read_text())) != next_w
        or UNIT.read_text() != next_u
    ):
        raise ValueError("Dependency readback mismatch")


def apply(state: Path, approval: str) -> dict[str, object]:
    """Apply the owner-approved retirement of the excluded legacy inbound."""
    require_vps_root()
    wanted = plan(state)
    if h.digest(wanted) != approval:
        raise ValueError("Fresh complete approval required")
    original = target.configuration(native.DB)
    legacy = select(original)
    w = cast("dict[str, object]", json.loads(CONFIG.read_text()))
    u = UNIT.read_text()
    next_w = watchdog_after(w)
    next_u = monitoring_after(u)
    require_recovery_quiet(w, "Recovery/fallback active")
    healthy()
    run(["systemctl", "is-active", TIMER])
    s = native.NativeSession(state)
    s.open(wanted["session_sha256"])
    timer_paused = False
    lock = None
    try:
        stage: StageEvidence = {
            "wanted": wanted,
            "original": original,
            "w": w,
            "u": u,
            "approval": approval,
        }
        before, before_json = stage_evidence(s, stage)
        # Pause only future timer dispatch, never stop a running watchdog/K3s/native unit.
        timer_paused = True
        wait_watchdog_drained()
        fd = os.open(
            h.check_path(Path(cast("str", w["state_dir"])) / "lock"), os.O_RDWR | os.O_NOFOLLOW
        )
        lock = os.fdopen(fd, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        healthy()
        require_recovery_quiet(w, "Recovery state changed")
        require_preimages_unchanged(s, stage)
        write_dependencies(next_w, next_u)
        disable_api_inbound(s, legacy, original)
        wait_port_converged()
        verify_publication_readback(s, before, before_json, next_w, next_u)
        h.save(
            s.state / "retirement-acceptance.json",
            {
                "legacy_disabled": True,
                "legacy_not_listening": True,
                "all_original_uri_json_preserved": True,
                "watchdog_healthy": healthy(),
                "only_native_enable_changed": True,
                "client_records_keys_bindings_preserved": True,
                "owner_accepted_cached_client_disconnect": True,
                "actual_end_device_refresh_claimed": False,
            },
        )
        (s.state / "retirement-uncertain.json").unlink()
    finally:
        try:
            s.cleanup()
        finally:
            if lock:
                lock.close()
            if timer_paused:
                run(["systemctl", "start", TIMER])
                run(["systemctl", "is-active", TIMER])
    receipt: dict[str, object] = {
        "legacy_32063_retired": True,
        "watchdog_and_monitoring_updated": True,
        "watchdog_timer_resumed": True,
        "original_subscriptions_and_credentials_preserved": True,
        "temporary_credentials_removed": True,
        "clients_must_refresh_existing_subscription": True,
    }
    h.save(s.state / "receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    try:
        if a.apply:
            if not a.approve_plan_hash:
                p.error("Complete plan hash required")
            print(h.canonical(apply(a.state, a.approve_plan_hash)))
        else:
            value = plan(a.state)
            print(h.canonical({"plan": value, "plan_sha256": h.digest(value), "writes": 0}))
    except Exception:
        import traceback

        try:
            if a.state.exists():
                h.save(
                    h.private_directory(a.state) / "failure-private.json",
                    {"traceback": traceback.format_exc()},
                )
        except (ValueError, OSError):
            pass
        raise SystemExit(
            "Legacy retirement stopped; inspect private receipts; never replay writes."
        ) from None
