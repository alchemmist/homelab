#!/usr/bin/env python3
"""Read-only VPN config projection and private online backup. Never emits identities/keys.

This does not authenticate clients, change SQLite, restart Xray or install firewall rules.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import cast

TABLE_QUERIES: dict[str, str] = {
    "inbounds": 'SELECT * FROM "inbounds"',
    "clients": 'SELECT * FROM "clients"',
    "client_inbounds": 'SELECT * FROM "client_inbounds"',
    "hosts": 'SELECT * FROM "hosts"',
}
TABLES = tuple(TABLE_QUERIES)
VOLATILE = {"inbounds": {"up", "down", "last_traffic_reset_time"}}
PRIVATE_DIR_MODE = 0o700


def canonical(value: object) -> str:
    """Return the canonical json encoding used for digests and on-disk receipts."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    """Return the canonical sha256 digest of a projected value."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def check_path(path: Path | str) -> Path:
    """Resolve a path, refusing every symlink in it."""
    resolved: Path = Path(path).absolute()
    if any(p.is_symlink() for p in (resolved, *resolved.parents)):
        msg = "Symlinks are not allowed"
        raise ValueError(msg)
    return resolved


def private_directory(path: Path | str) -> Path:
    """Create or require a caller-owned 0700 private evidence directory."""
    directory: Path = check_path(path)
    directory.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    st = directory.stat()
    if (
        not stat.S_ISDIR(st.st_mode)
        or st.st_uid != os.geteuid()
        or stat.S_IMODE(st.st_mode) != PRIVATE_DIR_MODE
    ):
        msg = "State directory must be caller-owned, mode 0700"
        raise ValueError(msg)
    return directory


def save(path: Path, value: object) -> None:
    """Atomically create one canonical json file at exactly 0600, never overwriting."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(canonical(value) + "\n")
        file.flush()
        os.fsync(file.fileno())


def _row_key(row: dict[str, object]) -> str:
    """Order projected rows canonically by their full content."""
    return canonical(row)


def projection(con: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    """Project every frozen table row through the read-only connection."""
    con.row_factory = sqlite3.Row
    result: dict[str, list[dict[str, object]]] = {}
    for table in TABLES:
        result[table] = sorted(
            [
                {k: record[k] for k in record if k not in VOLATILE.get(table, set())}
                for record in map(dict, con.execute(TABLE_QUERIES[table]))
            ],
            key=_row_key,
        )
    return result


def summarize(config: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    """Summarize the projection without ever emitting identities, keys or targets."""
    links = config["client_inbounds"]
    result: list[dict[str, object]] = []
    for row in sorted(config["inbounds"], key=lambda x: cast("int", x["port"])):
        stream = json.loads(str(row["stream_settings"] or "{}"))
        reality = stream.get("realitySettings") or {}
        target = reality.get("target", reality.get("dest", ""))
        # Target may be an address or a host:port, never emit arbitrary URLs/userinfo.
        if not isinstance(target, str) or any(x in target for x in ("/", "@", "?", "#", "\n")):
            target = "[non-host target withheld]"
        result.append(
            {
                "port": row["port"],
                "protocol": row["protocol"],
                "enabled": bool(row["enable"]),
                "network": stream.get("network"),
                "security": stream.get("security"),
                "target": target,
                "server_name_count": len(reality.get("serverNames") or []),
                "client_links": sum(x["inbound_id"] == row["id"] for x in links),
            }
        )
    encrypted = {
        row["id"]
        for row in config["inbounds"]
        if row["enable"]
        and json.loads(str(row["stream_settings"] or "{}")).get("security") in ("tls", "reality")
    }
    enabled_hosts = {
        row["inbound_id"] for row in config["hosts"] if not row.get("is_disabled", False)
    }
    encrypted &= enabled_hosts
    per_client: dict[object, set[object]] = {}
    for link in links:
        per_client.setdefault(link["client_id"], set()).add(link["inbound_id"])
    for item in result:
        if item["protocol"] == "vless" and item["security"] in (None, "", "none"):
            inbound_id = next(
                row["id"] for row in config["inbounds"] if row["port"] == item["port"]
            )
            clients = [ids for ids in per_client.values() if inbound_id in ids]
            item["links_with_existing_enabled_encrypted_alternative"] = sum(
                bool(ids & encrypted) for ids in clients
            )
            item["device_compatibility_and_subscription_render_unproven"] = True
    return {
        "configuration_sha256": digest(config),
        "identities": len(config["clients"]),
        "client_links": len(links),
        "inbounds": result,
        "records_are_not_active_sessions": True,
        "production_configuration_writes": 0,
    }


def inspect(database: Path | str, state: Path | None = None) -> dict[str, object]:
    """Project the database read-only and optionally copy one evidence snapshot."""
    database = check_path(database)
    if not database.is_file():
        msg = "Database must be an existing regular file"
        raise ValueError(msg)
    # No immutable=1: include committed WAL state. Copy to one consistent snapshot.
    with (
        closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(":memory:")) as snapshot,
    ):
        source.backup(snapshot)
        if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            msg = "SQLite integrity check failed"
            raise ValueError(msg)
        config = projection(snapshot)
        if state is not None:
            directory = private_directory(state)
            if any(directory.iterdir()):
                msg = "Backup state must be empty; never overwrite evidence"
                raise ValueError(msg)
            path = directory / "x-ui-before.sqlite3"
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(path)) as backup:
                snapshot.backup(backup)
                if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    msg = "Backup integrity check failed"
                    raise ValueError(msg)
            save(directory / "inventory.json", summarize(config))
    return summarize(config)


def main() -> None:
    """Print the canonical inventory, optionally backing up one private snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/srv/x-ui-lab/db/x-ui.db"))
    parser.add_argument(
        "--backup-state",
        type=Path,
        help="Empty private directory; writes backup only, never production DB",
    )
    args = parser.parse_args()
    print(canonical(inspect(args.database, args.backup_state)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        msg = "Inventory/backup stopped; inspect private state before retrying"
        raise SystemExit(msg) from None
