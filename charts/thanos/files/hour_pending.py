"""Read-only estimate of hourly data awaiting confirmed release from warm storage."""

import json
import os
import time
from pathlib import Path

from hour_copy import HOUR, ULID, Bucket


def sample(bucket, now):
    """Measure eligible warm bytes; copied but not yet released blocks count conservatively."""
    inventory = bucket.listing()
    total = oldest = 0
    for key in inventory:
        uid, _, name = key.partition("/")
        if (
            name != "meta.json"
            or not ULID.fullmatch(uid)
            or uid + "/deletion-mark.json" in inventory
        ):
            continue
        raw = bucket.read(key, absent=True)
        if raw is None:
            continue
        meta = json.loads(raw)
        if (
            meta["thanos"]["downsample"]["resolution"] != HOUR
            or meta["maxTime"] < (now - 730 * 86400) * 1000
        ):
            continue
        if meta["ulid"] != uid:
            raise ValueError("hourly block identity mismatch")
        prefix = uid + "/"
        files = bucket.listing(prefix)
        if prefix + "deletion-mark.json" in files or key not in files:
            continue
        # ULID creation time, not the (possibly much older) observation window.
        stamp = 0
        for char in uid[:10]:
            stamp = stamp * 32 + "0123456789ABCDEFGHJKMNPQRSTVWXYZ".index(char)
        oldest = max(oldest, int(now - stamp / 1000))
        total += sum(files.values())
    return total, oldest


if __name__ == "__main__":
    now = time.time()
    size, age = sample(
        Bucket(json.loads(Path("/s3/objstore.yml").read_bytes())["config"]), now
    )
    tmp = Path("/textfile/.warm-hour-pending.tmp")
    tmp.write_text(
        f"socrat_warm_hour_pending_upper_bytes {size}\nsocrat_warm_hour_oldest_upper_seconds {age}\nsocrat_warm_hour_inventory_timestamp_seconds {int(now)}\n"
    )
    os.replace(tmp, "/textfile/socrat-warm-hour.prom")
