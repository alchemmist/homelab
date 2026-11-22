"""Seed immutable workshop objects from a read-only mount; never delete or replace."""

import hashlib
import http.client
import json
import ssl
import time
from pathlib import Path
from typing import TypedDict

ROOT = Path("/source")
HOST = "thanos-warm-api:9000"
CHUNK = 2**20
RATE = 24 * 2**20
CTX = ssl.create_default_context(cafile="/trust/ca.crt")


class Capability(TypedDict):
    """Expected size and per-method signed paths for one object."""

    bytes: int
    HEAD: str
    GET: str
    PUT: str


def digest_local(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def transfer(key: str, spec: Capability) -> str:
    path = ROOT / key
    if path.resolve() != path or not path.is_file() or path.stat().st_size != spec["bytes"]:
        raise RuntimeError("source changed: " + key)
    n = spec["bytes"]
    started = time.monotonic()
    conn = http.client.HTTPSConnection(HOST, context=CTX, timeout=240)
    try:
        conn.request("HEAD", spec["HEAD"])
        res = conn.getresponse()
        status = res.status
        res.read()
        if status == 404:
            conn.putrequest("PUT", spec["PUT"])
            conn.putheader("Content-Length", str(n))
            conn.putheader("If-None-Match", "*")
            conn.endheaders()
            h = hashlib.sha256()
            sent = 0
            with path.open("rb") as f:
                while b := f.read(CHUNK):
                    h.update(b)
                    conn.send(b)
                    sent += len(b)
                    time.sleep(max(0, sent / RATE - (time.monotonic() - started)))
            res = conn.getresponse()
            status = res.status
            res.read()
            assert status == 200 and sent == n, (key, "PUT", status)
            source_hash = h.hexdigest()
        elif status == 200:
            source_hash = digest_local(path)
        else:
            raise RuntimeError((key, "HEAD", status))
        conn.request("GET", spec["GET"])
        res = conn.getresponse()
        assert res.status == 200, (key, "GET", res.status)
        h = hashlib.sha256()
        read = 0
        while b := res.read(CHUNK):
            h.update(b)
            read += len(b)
        assert read == n and h.hexdigest() == source_hash, (key, "readback mismatch")
        return source_hash
    finally:
        conn.close()


def main() -> None:
    batch: dict[str, Capability] = json.loads(Path("/caps/keys.json").read_text())
    for spec in batch.values():
        if not Capability.__required_keys__.issubset(spec):
            msg = "incomplete transfer capability"
            raise ValueError(msg)
    block = None
    manifest = {}
    total = 0
    for key, spec in batch.items():
        ident = key.split("/")[0]
        if ident != block:
            print("starting", ident, flush=True)
            block = ident
        if key != ident + "/deletion-mark.json" and (ROOT / ident / "deletion-mark.json").exists():
            raise RuntimeError("source now marked: " + ident)
        manifest[key] = transfer(key, spec)
        total += spec["bytes"]
        if key.endswith("/meta.json"):
            print("verified block", ident, "cumulative bytes", total, flush=True)
    encoded = json.dumps(manifest, sort_keys=True).encode()
    print(
        "all files verified",
        len(manifest),
        "bytes",
        total,
        "sha256(manifest)",
        hashlib.sha256(encoded).hexdigest(),
        flush=True,
    )


if __name__ == "__main__":
    main()
