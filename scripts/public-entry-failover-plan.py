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
    """Execute initial."""
    if not published or not set(published) <= set(ENTRIES):
        raise ValueError("Nonempty known publication required")
    return {
        "published": sorted(set(published)),
        "last_round": -1,
        "last_fingerprint": None,
        "streaks": {entry: {"up": 0, "down": 0} for entry in ENTRIES},
        "watermarks": {},
    }


def require_valid_policy(now, max_age, threshold) -> None:
    """Fail on malformed clocks or out-of-range freshness/streak policy."""
    if type(now) is not int or threshold < 2 or max_age < 1:
        raise ValueError("Invalid policy")


def require_valid_inputs(state, required) -> None:
    """Fail unless the publication state and required vantage registry are sane."""
    if set(required) != set(ENTRIES):
        raise ValueError("Complete entry policy required")
    if not state.get("published") or not set(state["published"]) <= set(ENTRIES):
        raise ValueError("Invalid previous publication")
    for entry in ENTRIES:
        if not isinstance(required[entry], list) or not all(
            isinstance(v, str) and 0 < len(v) <= 64 for v in required[entry]
        ):
            raise ValueError("Invalid vantage registry")
        if len(set(required[entry])) < 2:
            raise ValueError(
                "Two distinct configured vantage IDs required; independence must be attested separately"
            )


def collect_rows(observations) -> dict:
    """Index bounded round observations by (entry, vantage), validating shape."""
    rows = {}
    for o in observations:
        if o.get("entry") not in ENTRIES or not isinstance(o.get("vantage"), str):
            raise ValueError("Unknown observation")
        key = (o["entry"], o["vantage"])
        if key in rows:
            raise ValueError("Duplicate vantage for entry")
        if (
            type(o.get("checked_at")) is not int
            or type(o.get("backend_ok")) is not bool
            or type(o.get("local_only")) is not bool
        ):
            raise ValueError("Malformed evidence")
        rows[key] = o
    return rows


def fresh_evidence(candidates, now, max_age) -> bool:
    """Return True if all required vantages are fresh, backend and non-local."""
    return all(
        o and not o["local_only"] and 0 <= now - o["checked_at"] <= max_age for o in candidates
    )


def has_reused_evidence(entry, candidates, state) -> bool:
    """Return True if any vantage presented a timestamp at or before its watermark."""
    return any(
        o["checked_at"] <= state["watermarks"].get(entry + "|" + o["vantage"], -1)
        for o in candidates
    )


def reset_streak(nxt, entry) -> None:
    """Clear an entry's up/down streak counters after a holding outcome."""
    nxt["streaks"][entry] = {"up": 0, "down": 0}


def entry_status(entry, candidates, state, nxt, now, max_age) -> str:
    """Return the outcome for one entry, updating watermarks and streaks."""
    if not fresh_evidence(candidates, now, max_age):
        reset_streak(nxt, entry)
        return "missing_stale_or_local"
    # Every required vantage must contribute a NEW timestamp, not reused samples.
    if has_reused_evidence(entry, candidates, state):
        reset_streak(nxt, entry)
        return "reused_evidence"
    for o in candidates:
        nxt["watermarks"][entry + "|" + o["vantage"]] = o["checked_at"]
    passed = [o["backend_ok"] for o in candidates]
    if any(passed) and not all(passed):
        reset_streak(nxt, entry)
        return "partitioned"
    kind = "up" if all(passed) else "down"
    nxt["streaks"][entry][kind] += 1
    nxt["streaks"][entry]["down" if kind == "up" else "up"] = 0
    return kind


def propose_publication(state, nxt, threshold):
    """Add/drop entries once their up/down streaks cross the threshold."""
    proposed = set(state["published"])
    for entry in ENTRIES:
        if nxt["streaks"][entry]["up"] >= threshold:
            proposed.add(entry)
        if nxt["streaks"][entry]["down"] >= threshold:
            proposed.discard(entry)
    return proposed


def decision_of(hold: bool, nxt, state) -> str:
    """Translate the hold flag and proposed publication into a decision."""
    if hold:
        return "hold_review"
    if nxt["published"] != state["published"]:
        return "candidate_change"
    return "hold_hysteresis_or_stable"


def plan(state, batch, required, now, max_age=90, threshold=3):
    # The exact same accepted result must be distributed to ALL authorities;
    # neither local loopback nor independent per-authority rendering is consensus.
    """Execute plan."""
    require_valid_policy(now, max_age, threshold)
    require_valid_inputs(state, required)
    if type(batch.get("round")) is not int or len(batch.get("observations", [])) > 32:
        raise ValueError("Invalid bounded round")
    fingerprint = hashlib.sha256(
        json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if batch["round"] < state["last_round"]:
        raise ValueError("Out-of-order round")
    if batch["round"] == state["last_round"]:
        if fingerprint != state["last_fingerprint"]:
            raise ValueError("Same round changed payload")
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
    rows = collect_rows(batch["observations"])
    status = {}
    hold = False
    for entry in ENTRIES:
        candidates = [rows.get((entry, v)) for v in required[entry]]
        status[entry] = entry_status(entry, candidates, state, nxt, now, max_age)
        hold = hold or status[entry] not in ("up", "down")
    proposed = set(state["published"])
    if not hold:
        proposed = propose_publication(state, nxt, threshold)
        if not proposed:
            hold = True
            status["publication"] = "would_be_empty"
    if not hold:
        nxt["published"] = sorted(proposed)
    return {
        "state": nxt,
        "writes": False,
        "decision": decision_of(hold, nxt, state),
        "observations": status,
        "ready_to_publish": False,
        "gate": "OFFLINE ONLY; publisher/leadership/leases and partition policy not approved",
    }


def main():
    """Execute main."""
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
