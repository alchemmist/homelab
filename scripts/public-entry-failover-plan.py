#!/usr/bin/env python3
"""OFFLINE prototype: deterministic shared DNS decision, never apply/publish.

Needs independent non-local backend-aware observations for every required vantage.
Partitioned, stale or missing observations HOLD the previous publication and demand
operator review. No claim that DNS solves client-specific filtering. Deployment,
trusted collector transport, leadership and consumer leases remain separate gates.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

ENTRIES = ("home", "vps")


def initial(published):
    if not published or not set(published) <= set(ENTRIES):
        msg = "Nonempty known publication required"
        raise ValueError(msg)
    return {
        "published": sorted(set(published)),
        "last_round": -1,
        "last_fingerprint": None,
        "streaks": {entry: {"up": 0, "down": 0} for entry in ENTRIES},
        "watermarks": {},
    }


def plan(state, batch, required, now, max_age=90, threshold=3):
    # The exact same accepted result must be distributed to ALL authorities;
    # neither local loopback nor independent per-authority rendering is consensus.
    if type(now) is not int or threshold < 2 or max_age < 1:
        msg = "Invalid policy"
        raise ValueError(msg)
    if set(required) != set(ENTRIES):
        msg = "Complete entry policy required"
        raise ValueError(msg)
    if not state.get("published") or not set(state["published"]) <= set(ENTRIES):
        msg = "Invalid previous publication"
        raise ValueError(msg)
    for entry in ENTRIES:
        if not isinstance(required[entry], list) or not all(
            isinstance(v, str) and 0 < len(v) <= 64 for v in required[entry]
        ):
            msg = "Invalid vantage registry"
            raise ValueError(msg)
        if len(set(required[entry])) < 2:
            msg = "Two distinct configured vantage IDs required; independence must be attested separately"
            raise ValueError(
                msg
            )
    if type(batch.get("round")) is not int or len(batch.get("observations", [])) > 32:
        msg = "Invalid bounded round"
        raise ValueError(msg)
    fingerprint = hashlib.sha256(
        json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if batch["round"] < state["last_round"]:
        msg = "Out-of-order round"
        raise ValueError(msg)
    if batch["round"] == state["last_round"]:
        if fingerprint != state["last_fingerprint"]:
            msg = "Same round changed payload"
            raise ValueError(msg)
        return {
            "state": copy.deepcopy(state),
            "writes": False,
            "duplicate": True,
            "decision": "hold_duplicate",
            "ready_to_publish": False,
        }
    nxt = copy.deepcopy(state)
    nxt["last_round"] = batch["round"]
    nxt["last_fingerprint"] = fingerprint
    rows = {}
    for o in batch["observations"]:
        if o.get("entry") not in ENTRIES or not isinstance(o.get("vantage"), str):
            msg = "Unknown observation"
            raise ValueError(msg)
        key = (o["entry"], o["vantage"])
        if key in rows:
            msg = "Duplicate vantage for entry"
            raise ValueError(msg)
        if (
            type(o.get("checked_at")) is not int
            or type(o.get("backend_ok")) is not bool
            or type(o.get("local_only")) is not bool
        ):
            msg = "Malformed evidence"
            raise ValueError(msg)
        rows[key] = o
    status = {}
    hold = False
    for entry in ENTRIES:
        candidates = [rows.get((entry, v)) for v in required[entry]]
        fresh = all(
            o and not o["local_only"] and 0 <= now - o["checked_at"] <= max_age for o in candidates
        )
        if not fresh:
            status[entry] = "missing_stale_or_local"
            hold = True
            nxt["streaks"][entry] = {"up": 0, "down": 0}
            continue
        # Every required vantage must contribute a NEW timestamp, not reused samples.
        if any(
            o["checked_at"] <= state["watermarks"].get(entry + "|" + o["vantage"], -1)
            for o in candidates
        ):
            status[entry] = "reused_evidence"
            hold = True
            nxt["streaks"][entry] = {"up": 0, "down": 0}
            continue
        for o in candidates:
            nxt["watermarks"][entry + "|" + o["vantage"]] = o["checked_at"]
        passed = [o["backend_ok"] for o in candidates]
        if any(passed) and not all(passed):
            status[entry] = "partitioned"
            hold = True
            nxt["streaks"][entry] = {"up": 0, "down": 0}
            continue
        kind = "up" if all(passed) else "down"
        status[entry] = kind
        nxt["streaks"][entry][kind] += 1
        nxt["streaks"][entry]["down" if kind == "up" else "up"] = 0
    proposed = set(state["published"])
    if not hold:
        for entry in ENTRIES:
            if nxt["streaks"][entry]["up"] >= threshold:
                proposed.add(entry)
            if nxt["streaks"][entry]["down"] >= threshold:
                proposed.discard(entry)
        if not proposed:
            hold = True
            status["publication"] = "would_be_empty"
    if not hold:
        nxt["published"] = sorted(proposed)
    return {
        "state": nxt,
        "writes": False,
        "decision": "hold_review"
        if hold
        else (
            "candidate_change"
            if nxt["published"] != state["published"]
            else "hold_hysteresis_or_stable"
        ),
        "observations": status,
        "ready_to_publish": False,
        "gate": "OFFLINE ONLY; publisher/leadership/leases and partition policy not approved",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    args = p.parse_args()
    assert args.input.stat().st_size <= 65536
    data = json.loads(args.input.read_text())
    print(
        json.dumps(
            plan(data["state"], data["batch"], data["required"], data["now"]), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
