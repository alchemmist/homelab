"""Apply the rebalanced k3s role to a node's config file."""

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import yaml


def configure(args):
    """Document the configure operation."""
    path = Path(args.config)
    if path.is_symlink():
        msg = "config must not be a symlink"
        raise ValueError(msg)
    exists = path.exists()
    original = path.read_bytes() if exists else b""
    current = yaml.safe_load(original) or {}
    if not isinstance(current, dict):
        msg = "config must be a YAML mapping"
        raise ValueError(msg)
    desired = dict(current)
    for key in (
        "cluster-init",
        "disable-apiserver",
        "disable-controller-manager",
        "disable-scheduler",
        "disable-etcd",
    ):
        desired.pop(key, None)
    if args.role == "control-plane":
        desired["disable-etcd"] = True
    desired.update(
        {
            "node-name": args.node_name,
            "node-ip": args.node_ip,
            "advertise-address": args.advertise_ip,
            "flannel-iface": "wg-socrat",
            "server": args.server,
        }
    )
    if args.token_file:
        desired.pop("token", None)
        desired["token-file"] = args.token_file
    sans = desired.get("tls-san", [])
    if isinstance(sans, str):
        sans = [sans]
    if not isinstance(sans, list) or any(not isinstance(value, str) for value in sans):
        msg = "tls-san must contain strings"
        raise ValueError(msg)
    desired["tls-san"] = list(dict.fromkeys([*sans, args.advertise_ip, "127.0.0.1"]))
    changed = desired != current or not exists or stat.S_IMODE(path.stat().st_mode) != 0o600
    result = {"changed": changed, "backup": None}
    if not changed or args.check:
        return result
    encoded = yaml.safe_dump(desired, sort_keys=False).encode()
    result["backup"] = _write_desired(path, original, encoded, exists)
    return result


def _write_desired(path, original, encoded, exists):
    """Atomically install the new config; return the backup file name, if any."""
    backup = None
    if exists:
        fd, backup = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return Path(backup).name if backup else None


def main() -> int:
    """Document the main operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--role", choices=("server", "control-plane"), required=True)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--node-ip", required=True)
    parser.add_argument("--advertise-ip", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--token-file")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = configure(args)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"error": type(error).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
