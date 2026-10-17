import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit


HOSTNAME = "rancher.socrat.alchemmist.xyz"
DESIRED = {
    "type": "keyword",
    "url": f"https://{HOSTNAME}/ping",
    "keyword": "pong",
    "method": "GET",
    "accepted_statuscodes_json": '["200"]',
    "ignore_tls": 0,
    "invert_keyword": 0,
    "upside_down": 0,
    "maxredirects": 0,
}


def configure(db_path, check=False):
    db_path = Path(db_path).resolve()
    mode = "ro" if check else "rw"
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode={mode}", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("PRAGMA table_info(monitor)")}
        if not {"id", *DESIRED}.issubset(columns):
            raise ValueError("Unsupported monitor schema: required columns are missing")
        matches = []
        for row in connection.execute("SELECT id, url FROM monitor"):
            try:
                hostname = urlsplit(row["url"] or "").hostname
            except ValueError:
                continue
            if hostname == HOSTNAME:
                matches.append(row["id"])
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one Rancher monitor; found {len(matches)}")
        monitor_id = matches[0]
        selection = ", ".join(f'"{name}"' for name in DESIRED)
        current = connection.execute(
            f"SELECT {selection} FROM monitor WHERE id = ?", (monitor_id,)
        ).fetchone()
        changed = any(current[name] != value for name, value in DESIRED.items())
        result = {"changed": changed, "monitor_id": monitor_id}
        if check or not changed:
            return result
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        backup_dir.chmod(0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        fd, backup_path = tempfile.mkstemp(
            prefix=f"rancher-monitor-{timestamp}-", suffix=".db", dir=backup_dir
        )
        os.fchmod(fd, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)
        assignments = ", ".join(f'"{name}" = ?' for name in DESIRED)
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            f"UPDATE monitor SET {assignments} WHERE id = ?",
            (*DESIRED.values(), monitor_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Rancher monitor changed during migration")
        connection.commit()
        result["backup"] = backup_path
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = configure(args.db, args.check)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
