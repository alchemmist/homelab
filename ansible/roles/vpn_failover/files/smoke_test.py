#!/usr/bin/env python3
"""Smoke tests for the vpn_failover runtime (systemd units, site backups)."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

NAMESPACE = "homelab-vpn-smoke"
ROOT = Path("/opt/homelab-vpn-failover")
CONFIG = Path("/etc/homelab-vpn-failover")
UNITS = ["homelab-vpn-smoke-primary.service", "homelab-vpn-smoke-caddy.service"]
WORKLOADS = [
    (
        "primary",
        "/srv/x-ui-lab/db",
        "/srv/x-ui-lab/cert",
        "/srv/x-ui-lab/acme",
        ROOT / "primary/app/bin",
        "Asia/Tehran",
    ),
]


def run(*args, timeout=45):
    """Execute the run operation."""
    return subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=timeout
    ).stdout.strip()


def copy_directory(source, destination):
    """Execute the copy_directory operation."""
    source = Path(source)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False)
    else:
        destination.mkdir()


def backup_database(source, destination):
    """Execute the backup_database operation."""
    source = Path(source)
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError("Live database is missing or empty")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10) as original:
        with sqlite3.connect(destination) as backup:
            original.backup(backup)
            if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("Smoke database integrity check failed")


def launch(unit, properties, executable, *arguments):
    """Execute the launch operation."""
    command = [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit=" + unit,
        "--property=Type=exec",
        "--property=NetworkNamespacePath=/run/netns/" + NAMESPACE,
        "--property=KillMode=control-group",
        "--property=TimeoutStopSec=15s",
        "--property=UMask=0077",
        "--property=MemoryMax=192M",
        "--property=CPUQuota=50%",
    ]
    command += ["--property=" + value for value in properties]
    run(*command, executable, *arguments)


def verify_environment(runtime_root: Path) -> None:
    """Refuse to run when the isolation prerequisites are not clean."""
    if os.geteuid() != 0:
        raise RuntimeError("Smoke test requires root")
    os.umask(0o077)
    if runtime_root != ROOT:
        if (
            runtime_root.is_symlink()
            or runtime_root.parent != ROOT
            or not runtime_root.name.startswith("staged-")
        ):
            raise RuntimeError("Unowned candidate runtime root")
    namespaces = json.loads(run("ip", "-j", "netns", "list"))
    if any(item["name"] == NAMESPACE for item in namespaces):
        raise RuntimeError("Smoke namespace already exists; refusing to modify it")
    for unit in UNITS:
        state = run("systemctl", "show", unit, "--property=LoadState", "--value")
        if state != "not-found":
            raise RuntimeError("Smoke unit already exists; refusing to modify it")


def stage_workloads(
    workloads: list[tuple[str, str, str, str, object, str]], temporary: Path
) -> tuple[Path, Path]:
    """Copy databases, certificates and binaries into the sandbox."""
    for name, db, cert, acme, binaries, zone in workloads:
        target = temporary / name
        target.mkdir()
        (target / "db").mkdir()
        backup_database(Path(db) / "x-ui.db", target / "db/x-ui.db")
        for source, relative in ((cert, "cert"), (acme, "acme"), (binaries, "bin")):
            copy_directory(source, target / relative)
    storage = temporary / "caddy-storage"
    copy_directory("/srv/caddy/data/caddy", storage)
    caddyfile = temporary / "Caddyfile"
    caddy_config = (CONFIG / "Caddyfile").read_text()
    if "root /srv/caddy/data/caddy" not in caddy_config:
        raise RuntimeError("Unexpected Caddy storage configuration")
    caddyfile.write_text(caddy_config.replace("root /srv/caddy/data/caddy", "root " + str(storage)))
    configuration = temporary / "config.json"
    configuration.write_text((CONFIG / "config.json").read_text())
    return caddyfile, configuration


def launch_workloads(
    runtime_root: Path,
    temporary: Path,
    caddyfile: Path,
    workloads: list[tuple[str, str, str, str, object, str]],
) -> list[str]:
    """Start the isolated primary and Caddy units, returning their names."""
    started = []
    for name, db, cert, acme, binaries, zone in workloads:
        target = temporary / name
        unit = "homelab-vpn-smoke-" + name + ".service"
        properties = [
            "RootDirectory=" + str(runtime_root / name),
            "MountAPIVFS=yes",
            "WorkingDirectory=/app",
            "BindPaths="
            + " ".join(
                str(target / source) + ":" + destination
                for source, destination in [
                    ("db", "/etc/x-ui"),
                    ("cert", "/root/cert"),
                    ("acme", "/root/.acme.sh"),
                    ("bin", "/app/bin"),
                ]
            ),
            "BindReadOnlyPaths=/etc/resolv.conf",
            "Environment=XRAY_VMESS_AEAD_FORCED=false XUI_ENABLE_FAIL2BAN=false TZ=" + zone,
        ]
        started.append(unit)
        launch(unit, properties, "/app/x-ui")
    started.append(UNITS[-1])
    launch(
        UNITS[-1],
        [
            "Environment=XDG_DATA_HOME="
            + str(temporary / "caddy-data")
            + " XDG_CONFIG_HOME="
            + str(temporary / "caddy-config")
        ],
        str(ROOT / "caddy"),
        "run",
        "--config",
        str(caddyfile),
        "--adapter",
        "caddyfile",
    )
    return started


def wait_for_health(configuration: Path) -> None:
    """Poll the isolated health checker until it passes or times out."""
    deadline = time.monotonic() + 60
    while True:
        result = subprocess.run(
            [
                "ip",
                "netns",
                "exec",
                NAMESPACE,
                "/usr/bin/python3",
                "/usr/local/sbin/homelab-vpn-failover",
                "check",
                "--config",
                str(configuration),
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Isolated native VPN health checks did not pass")
        time.sleep(2)


def cleanup(
    temporary: Path, started: list[str], *, namespace_created: bool, cleanup_errors: list[str]
) -> None:
    """Stop the smoke units and remove every private artifact."""
    for unit in reversed(started):
        try:
            if run("systemctl", "show", unit, "--property=LoadState", "--value") != "not-found":
                run("systemctl", "stop", unit)
        except Exception:
            cleanup_errors.append("Could not stop " + unit)
    if namespace_created and not cleanup_errors:
        try:
            remaining = run("ip", "netns", "pids", NAMESPACE)
            if remaining:
                raise RuntimeError("Smoke namespace still has processes")
            run("ip", "netns", "delete", NAMESPACE)
        except Exception:
            cleanup_errors.append("Could not remove isolated network namespace")
    if not cleanup_errors:
        shutil.rmtree(temporary)
    if cleanup_errors:
        raise RuntimeError(
            "; ".join(cleanup_errors) + "; private artifacts retained at " + str(temporary)
        )


def main(runtime_root=ROOT):
    """Execute the main operation."""
    runtime_root = Path(runtime_root)
    verify_environment(runtime_root)
    workloads = [
        (name, db, cert, acme, runtime_root / name / "app/bin", zone)
        for name, db, cert, acme, _, zone in WORKLOADS
    ]
    temporary = Path(tempfile.mkdtemp(prefix="homelab-vpn-smoke-", dir="/var/tmp"))
    started: list[str] = []
    namespace_created = False
    cleanup_errors: list[str] = []
    try:
        caddyfile, configuration = stage_workloads(workloads, temporary)
        run("ip", "netns", "add", NAMESPACE)
        namespace_created = True
        run("ip", "-n", NAMESPACE, "link", "set", "lo", "up")
        run("ip", "-n", NAMESPACE, "address", "add", "172.18.0.1/16", "dev", "lo")
        started = launch_workloads(runtime_root, temporary, caddyfile, workloads)
        wait_for_health(configuration)
        proof = {
            "healthy": True,
            "runtime": "isolated native primary and Caddy",
            "production_runtime_changed": False,
        }
    finally:
        cleanup(
            temporary, started, namespace_created=namespace_created, cleanup_errors=cleanup_errors
        )

    if runtime_root != ROOT:
        proof.update(
            image=(runtime_root / "primary/.homelab-image").read_text().strip(),
            ui_sha256=hashlib.sha256((runtime_root / "primary/app/x-ui").read_bytes()).hexdigest(),
            accepted_at=time.time(),
            cleanup_verified=True,
        )
        receipt = runtime_root / ".isolated-smoke-accepted.json"
        with receipt.open("x") as stream:
            json.dump(proof, stream)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps(proof))  # noqa: T201


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--runtime-root", type=Path, default=ROOT)
        main(parser.parse_args().runtime_root)
    except Exception as error:
        print(json.dumps({"error": str(error)}))  # noqa: T201
        raise SystemExit(1) from error
