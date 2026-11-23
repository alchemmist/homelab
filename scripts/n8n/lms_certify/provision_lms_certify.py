#!/usr/bin/env python3
"""Import the pilot graph as an inactive n8n workflow for review."""

import json
from pathlib import Path

from scripts.n8n.sync import api

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    body = json.loads((ROOT / "docs/n8n/lms-certify/workflow.json").read_text())
    matches = [w for w in api("GET", "workflows?limit=250")["data"] if w["name"] == body["name"]]
    if matches:
        msg = "Pilot already exists; refusing to overwrite live configuration"
        raise SystemExit(msg)
    result = api("POST", "workflows", body)
    print(result["id"], "active=" + str(result["active"]))


if __name__ == "__main__":
    main()
