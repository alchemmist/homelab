#!/usr/bin/env python3
"""Import the pilot graph as an inactive n8n workflow for review."""

import json
from pathlib import Path

from sync import api

ROOT = Path(__file__).resolve().parents[2]


def main():
    body = json.loads((ROOT / "docs/n8n/lms-certify/workflow.json").read_text())
    matches = [w for w in api("GET", "workflows?limit=250")["data"] if w["name"] == body["name"]]
    if matches:
        raise SystemExit("Pilot already exists; refusing to overwrite live configuration")
    result = api("POST", "workflows", body)
    print(result["id"], "active=" + str(result["active"]))


if __name__ == "__main__":
    main()
