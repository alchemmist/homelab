"""Stage a rate-limited logical warm inventory. Not a cutover or a consistent snapshot."""

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

class LimitedWriter:
    def __init__(self, stream):
        self.stream = stream
        self.started = time.monotonic()
        self.size = 0

    def write(self, data):
        self.stream.write(data)
        self.size += len(data)
        time.sleep(max(0, self.started + self.size / (12 * 2**20) - time.monotonic()))


def retry_connection(call):
    for attempt in range(6):
        try:
            return call()
        except (ConnectionError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2**attempt)


def main():
    sys.path.insert(0, "/scripts")
    from hour_copy import Bucket

    dest = Path("/candidate") / ("precopy-" + os.environ["HOSTNAME"])
    dest.mkdir(exist_ok=False)  # never replace a prior attempt
    bucket = Bucket(json.loads(Path("/s3/objstore.yml").read_bytes())["config"])
    objects = retry_connection(bucket.listing)
    fs = os.statvfs(dest)
    if fs.f_bavail * fs.f_frsize < sum(objects.values()) + 100 * 2**30:
        raise OSError("insufficient disk reserve")
    copied = missing = 0
    tree = dest / "objects"
    with (dest / "verified.jsonl").open("x") as journal:
        for key, size in sorted(objects.items()):
            if any(part in {"", ".", ".."} for part in key.split("/")):
                raise ValueError("unsafe object key")
            target = tree / key
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent) as temp:
                def transfer():
                    temp.seek(0)
                    temp.truncate()
                    return bucket.read(key, sink=LimitedWriter(temp), absent=True)

                proof = retry_connection(transfer)
                if proof is None:
                    missing += 1  # concurrent expiry; report, never propagate deletion
                    continue
                temp.flush()
                os.fsync(temp.fileno())
                with open(temp.name, "rb") as verify:
                    digest = hashlib.file_digest(verify, "sha256").hexdigest()
                if proof != (size, digest):
                    raise ValueError("object changed or failed readback: " + key)
                os.link(temp.name, target)
            journal.write(json.dumps([key, *proof]) + "\n")
            journal.flush()
            copied += size
        os.fsync(journal.fileno())
    print("verified bytes", copied, "disappeared since listing", missing, flush=True)


if __name__ == "__main__":
    main()
