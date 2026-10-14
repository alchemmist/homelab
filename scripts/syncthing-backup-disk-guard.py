import argparse
import json
import os
from pathlib import Path
import urllib.request

FOLDER_ID = "pg-mdb-backups"
BACKUP_PATH = "/srv/syncthing/pg_mdb_encrypted_backups"
API = "http://127.0.0.1:8384"


def should_pause(free_bytes, threshold_bytes, paused):
    return free_bytes <= threshold_bytes and not paused


def request(key, method="GET", data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        API + "/rest/config/folders/" + FOLDER_ID,
        data=body,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        content = response.read()
        return json.loads(content) if content else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--threshold-gib", type=float, default=15)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.threshold_gib <= 0:
        parser.error("--threshold-gib must be positive")
    stat = os.statvfs(BACKUP_PATH)
    free = stat.f_bavail * stat.f_frsize
    key = args.key_file.read_text().strip()
    folder = request(key)
    paused = folder["paused"]
    if not args.status and should_pause(free, args.threshold_gib * 2**30, paused):
        request(key, "PATCH", {"paused": True})
        paused = request(key)["paused"]
        if not paused:
            raise RuntimeError("Syncthing did not confirm folder pause")
        action = "paused"
    else:
        action = "unchanged"
    print(json.dumps({
        "folder": FOLDER_ID,
        "free_gib": round(free / 2**30, 3),
        "threshold_gib": args.threshold_gib,
        "paused": paused,
        "action": action,
    }))


if __name__ == "__main__":
    main()
