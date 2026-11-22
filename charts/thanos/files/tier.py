"""Coverage-gated retention for the warm bucket only. Never remove objects directly."""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from hour_copy import HOUR, ULID, Bucket, run

DAY = 86400000
FIVE = 300000


def resolution(m):
    """Read the downsampling interval in milliseconds from Thanos block metadata."""
    return m["thanos"]["downsample"]["resolution"]


def encloses(target, source, res):
    """Require one complete successor; do not infer coverage from adjacent blocks."""
    ids = set(source["compaction"]["sources"])
    return (
        resolution(target) == res
        and target["thanos"]["labels"] == source["thanos"]["labels"]
        and target["minTime"] <= source["minTime"] < source["maxTime"] <= target["maxTime"]
        and bool(ids)
        and ids <= set(target["compaction"]["sources"])
        and target["stats"]["numSamples"] > 0
    )


def same_block(a, b):
    """Require equal ULIDs and ranges as well as mutual coverage at the same resolution."""
    return (
        a["ulid"] == b["ulid"]
        and a["minTime"] == b["minTime"]
        and a["maxTime"] == b["maxTime"]
        and encloses(a, b, resolution(b))
        and encloses(b, a, resolution(a))
    )


def get(url):
    """Return Thanos response data only for a successful reply without warnings."""
    with urlopen(url, timeout=30) as r:
        reply = json.load(r)
    if reply["status"] != "success" or reply.get("warnings"):
        msg = "incomplete Thanos response"
        raise OSError(msg)
    return reply["data"]


def loaded(store):
    """Index loaded blocks by ULID, rejecting an inventory that reports a Store error."""
    d = get("http://" + store + ":10902/api/v1/blocks?view=loaded")
    if d.get("err"):
        msg = "Store cannot load its inventory"
        raise OSError(msg)
    return {m["ulid"]: m for m in d["blocks"]}


def serves(store, block, source):
    """Probe for samples through the named Store at the source midpoint and successor resolution."""
    # A positive Store-only read supplements the exact loaded-block, range and lineage checks.
    t = (source["minTime"] + source["maxTime"]) // 2000
    q = urlencode(
        {
            "query": 'count(count_over_time(up{job="node-exporter"}[2h]))',
            "time": t,
            "max_source_resolution": str(resolution(block) // 1000) + "s",
            "partial_response": "false",
            "storeMatch[]": '{__address__="'
            + store
            + '.cattle-monitoring-system.svc.cluster.local:10901"}',
        }
    )
    data = get("http://thanos-query:9090/api/v1/query?" + q)
    return any(float(row["value"][1]) > 0 for row in data["result"])


def marker(b, uid, name, apply) -> bool:
    """Keep existing marks; in apply mode write missing marks and verify them by reading back."""
    key = uid + "/" + name + "-mark.json"
    if not ULID.fullmatch(uid) or name not in (
        "deletion",
        "no-compact",
        "no-downsample",
    ):
        msg = "invalid mark"
        raise ValueError(msg)
    if b.read(key, method="HEAD", absent=True) is not None:
        return True
    print("mark" if apply else "would mark", name, uid, flush=True)
    if not apply:
        return False
    field = {
        "deletion": "deletion_time",
        "no-compact": "no_compact_time",
        "no-downsample": "no_downsample_time",
    }[name]
    body = {
        "version": 1,
        "id": uid,
        field: int(time.time()),
        "details": "verified tier cascade",
    }
    if name != "deletion":
        body["reason"] = "manual"
    b.read(key, method="PUT", payload=json.dumps(body).encode())
    if json.loads(b.read(key)) != body:
        msg = "marker readback mismatch"
        raise OSError(msg)
    return True


def tiers(b, dest, confirmed, apply=False) -> None:
    """Evaluate warm blocks for retention marks using successor coverage and Store readbacks."""
    warm, cold = loaded("thanos-store"), loaded("thanos-store-1h")
    active = {}
    for prefix in b.listing(groups=True):
        uid = prefix.rstrip("/")
        if (
            not ULID.fullmatch(uid)
            or b.read(prefix + "deletion-mark.json", method="HEAD", absent=True) is not None
        ):
            continue
        raw = b.read(prefix + "meta.json", absent=True)
        if raw is None:
            continue
        m = json.loads(raw)
        if m["ulid"] != uid:
            msg = "unexpected block id"
            raise ValueError(msg)
        active[uid] = m

    def current(m):
        p = m["ulid"] + "/"
        return (
            b.read(p + "deletion-mark.json", method="HEAD", absent=True) is None
            and json.loads(b.read(p + "meta.json")) == m
        )

    def cold_ok(m):
        p = dest / m["ulid"]
        return (
            not (p / "deletion-mark.json").exists()
            and (p / "index").is_file()
            and (p / "meta.json").is_file()
            and same_block(json.loads((p / "meta.json").read_bytes()), m)
            and any((p / "chunks").glob("[0-9]*"))
        )

    print(
        "tier inventory warm raw/5m/1h",
        [sum(resolution(m) == r for m in active.values()) for r in (0, FIVE, HOUR)],
        "loaded cold",
        len(cold),
        "apply",
        apply,
        flush=True,
    )
    now = int(time.time() * 1000)
    for uid, m in active.items():
        res = resolution(m)
        age = now - m["maxTime"]
        if res == 0 and age >= 5 * DAY:
            for k, t in active.items():
                if (
                    encloses(t, m, FIVE)
                    and k in warm
                    and same_block(warm[k], t)
                    and current(t)
                    and serves("thanos-store", t, m)
                    and current(m)
                ):
                    marker(b, uid, "deletion", apply)
                    break
        if res not in (FIVE, HOUR):
            continue
        for k, t in cold.items():
            if not encloses(t, m, HOUR) or not cold_ok(t) or not serves("thanos-store-1h", t, m):
                continue
            # Never retire a 5m parent on the basis of an hourly file near its own expiry.
            if now - t["maxTime"] >= (730 - 2) * DAY:
                continue
            if res == FIVE and current(m):
                if age >= 90 * DAY:
                    marker(b, uid, "deletion", apply)
                else:
                    # Do not let compaction generate a fresh 5m ULID without the suppression marker.
                    marker(b, uid, "no-compact", apply)
                    marker(b, uid, "no-downsample", apply)
            receipt = dest / ".tier-receipts" / uid
            verified = uid in confirmed or (
                receipt.is_file()
                and json.loads(receipt.read_bytes())["meta_sha256"]
                == hashlib.sha256(b.read(uid + "/meta.json")).hexdigest()
            )
            if res == HOUR and verified and current(m):
                # Suppress regeneration from every still-live overlapping parent before release.
                parents = [
                    v
                    for v in active.values()
                    if resolution(v) == FIVE
                    and v["thanos"]["labels"] == m["thanos"]["labels"]
                    and v["minTime"] < m["maxTime"]
                    and m["minTime"] < v["maxTime"]
                ]
                if all(encloses(t, v, HOUR) for v in parents):
                    for v in parents:
                        if current(v):
                            marker(b, v["ulid"], "no-compact", apply)
                            marker(b, v["ulid"], "no-downsample", apply)
                    if cold_ok(t):
                        marker(b, uid, "deletion", apply)
            break


if __name__ == "__main__":
    b = Bucket(json.loads(Path("/s3/objstore.yml").read_bytes())["config"])
    dest = Path(os.environ["HOUR_DIRECTORY"])
    tiers(b, dest, run(b, dest), os.environ.get("APPLY_TIER_MARKS") == "true")
