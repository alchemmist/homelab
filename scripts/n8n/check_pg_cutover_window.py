#!/usr/bin/env python3
"""Bounded, read-only observation. Never pauses workflows or triggers a cutover."""
import argparse
import json
import runpy
import sys
import time
from pathlib import Path

from sync import api


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=int, default=0, choices=range(86401), metavar="0..86400")
    args = parser.parse_args()
    idle = runpy.run_path(str(Path(__file__).resolve().parents[1] / "vm105-spi-idle-handoff.py"))["idle_state"]
    end = time.monotonic() + args.wait_seconds
    while True:
        state = idle()
        # One result suffices to veto. Never enumerate execution data or credentials.
        for status in ("running", "waiting"):
            state["n8n_" + status] = bool(api("GET", f"executions?status={status}&limit=1")["data"])
        print(json.dumps(state), flush=True)
        if not any(state.values()):
            return 0  # A snapshot, not a lock. Recheck immediately before rollout.
        remaining = end - time.monotonic()
        if remaining <= 0:
            return 1
        time.sleep(min(30, remaining))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, OSError, RuntimeError, ValueError, TimeoutError):
        sys.exit("Drain observation failed. Do not restart n8n.")
