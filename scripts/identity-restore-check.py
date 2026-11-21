#!/usr/bin/env python3
"""Restore an encrypted snapshot into disposable, socket-only PostgreSQL (not production)."""

import argparse
import io
import json
import shlex
import subprocess
import tarfile
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import IO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

spec = spec_from_file_location("backup", Path(__file__).with_name("identity-backup.py"))
if spec is None or spec.loader is None:
    reason = "Backup renderer module missing"
    raise RuntimeError(reason)
b = module_from_spec(spec)
spec.loader.exec_module(b)


def _read_member(tar: tarfile.TarFile, name: str) -> IO[bytes]:
    member = tar.extractfile(name)
    if member is None:
        reason = "Snapshot member missing"
        raise ValueError(reason)
    return member


def _verify_webui(tar: tarfile.TarFile) -> None:
    import sqlite3
    import tempfile

    # SQLite backups may retain a WAL-mode header; read an immutable private
    # temp file rather than trying to open WAL sidecars for an in-memory DB.
    temporary = tempfile.TemporaryDirectory(prefix="identity-sqlite-restore-")
    __import__("atexit").register(temporary.cleanup)
    database = Path(temporary.name) / "webui.db"
    b.save(database, _read_member(tar, "webui.db").read())
    connection = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity failed")
    ids = {r[0] for r in connection.execute("SELECT id FROM user")}
    expected = {
        u["openWebuiUserId"]
        for u in json.loads(
            (
                Path(__file__).resolve().parents[1] / "deploy/identity/account-mappings.json"
            ).read_text()
        ).values()
    }
    if not expected <= ids:
        raise RuntimeError("Reviewed original WebUI identities missing")
    connection.close()
    temporary.cleanup()
    print(
        json.dumps(
            {
                "sqliteRestore": "passed",
                "reviewedUserIdsPreserved": len(expected),
                "fullApplicationRecoveryTested": False,
            }
        )
    )


def _verify_harbor(tar: tarfile.TarFile) -> int:
    import hashlib

    blobs = 0
    with tarfile.open(fileobj=io.BytesIO(_read_member(tar, "registry.tar").read())) as registry:
        for member in registry.getmembers():
            if member.isfile() and member.name.endswith("/data"):
                digest = hashlib.sha256(_read_member(registry, member.name).read()).hexdigest()
                if member.name.split("/")[-2] != digest:
                    raise RuntimeError("Harbor blob checksum mismatch")
                blobs += 1
    if not blobs:
        raise RuntimeError("No registry blobs in snapshot")
    return blobs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backup", type=Path, required=True)
    p.add_argument("--service", choices=["authentik", "harbor", "open-webui"], default="authentik")
    p.add_argument("--key", type=Path, default=Path.home() / ".config/homelab/identity-backup.key")
    args = p.parse_args()
    encrypted = args.backup.read_bytes()
    if not encrypted.startswith(b.HEADER):
        raise SystemExit("Invalid backup format")
    offset = len(b.HEADER)
    archive = AESGCM(args.key.read_bytes()).decrypt(
        encrypted[offset : offset + 12], encrypted[offset + 12 :], b.HEADER
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        if args.service == "open-webui":
            _verify_webui(tar)
            return
        dump = _read_member(tar, "database.dump").read()
        if args.service == "authentik":
            json.load(_read_member(tar, "credentials.json"))
            with tarfile.open(fileobj=io.BytesIO(_read_member(tar, "data.tar").read())) as data:
                data.getmembers()  # Never extract host paths.
        else:
            blobs = _verify_harbor(tar)
    name = "identity-restore-" + uuid.uuid4().hex[:10]
    k = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml", "-n", "identity"]

    def run(argv: list[str], data: bytes | None = None) -> bytes:
        cmd = "env K3S_CONFIG_FILE=/dev/null " + shlex.join(k + argv)
        result = subprocess.run(b.SSH + [cmd], input=data, capture_output=True, timeout=300)
        if result.returncode:
            raise RuntimeError("Isolated restore operation failed (details suppressed)")
        return result.stdout

    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": "identity"},
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": "socrat-0"},
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [
                {
                    "name": "postgres",
                    "image": "postgres:17.11-trixie"
                    if args.service == "authentik"
                    else "postgres:18.6-trixie",
                    "args": ["-c", "listen_addresses="],
                    "env": [
                        {"name": "POSTGRES_HOST_AUTH_METHOD", "value": "trust"},
                        {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
                    ],
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "128Mi", "ephemeral-storage": "256Mi"},
                        "limits": {"memory": "512Mi", "ephemeral-storage": "2Gi"},
                    },
                    "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}],
                    "readinessProbe": {
                        "exec": {"command": ["pg_isready", "-U", "postgres"]},
                        "initialDelaySeconds": 5,
                    },
                }
            ],
            "volumes": [{"name": "data", "emptyDir": {"sizeLimit": "2Gi"}}],
        },
    }
    try:
        run(["create", "-f", "-"], json.dumps(pod).encode())
        run(["wait", "--for=condition=Ready", "pod/" + name, "--timeout=180s"])
        run(
            [
                "exec",
                "-i",
                name,
                "--",
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "--no-owner",
                "--exit-on-error",
            ],
            dump,
        )
        query = (
            "SELECT count(*) FROM authentik_core_group WHERE name LIKE 'homelab-%'"
            if args.service == "authentik"
            else "SELECT count(*) FROM harbor_user WHERE username='admin' AND deleted=false"
        )
        count = int(
            run(["exec", name, "--", "psql", "-U", "postgres", "-d", "postgres", "-Atc", query])
            .decode()
            .strip()
        )
        expected_count = 5 if args.service == "authentik" else 1
        if count != expected_count:
            raise RuntimeError("Expected restored identities missing")
        print(
            json.dumps(
                {
                    "databaseRestore": "passed",
                    "service": args.service,
                    "verifiedIdentityRows": count,
                    "verifiedBlobs": blobs if args.service == "harbor" else None,
                    "fullApplicationRecoveryTested": False,
                }
            )
        )
    finally:
        run(["delete", "pod", name, "--ignore-not-found", "--wait=true", "--timeout=60s"])


if __name__ == "__main__":
    main()
