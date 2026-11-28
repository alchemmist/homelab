"""One archive only, verified TLS and bearer; receiver publishes only after full SHA-256."""

import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import IO, TYPE_CHECKING, TypedDict, override

HOST = "raw-cold-copy-20261121"
SIZE = 16 * 2**20
ROOT = Path("/data")
ARCHIVE = "raw.tar.zst"
if TYPE_CHECKING:
    from collections.abc import Callable

HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_UNAVAILABLE = 503
SHA_LINE_PARTS = 2
SHA256_HEX = "[0-9a-f]{64}"
MAX_ARCHIVE_BYTES = 55 * 2**30
PART_PARALLELISM = 3
RETRY_ATTEMPTS = 5
STATE_ATTEMPTS = 2880
STATE_RETRY_SECONDS = 5
PART_RETRY_BASE_SECONDS = 3


class ArchiveInfo(TypedDict):
    """The verified archive identity published by the cold-copy sender."""

    sha256: str
    size: int
    manifest: str


def info() -> ArchiveInfo:
    """Read and validate the sender's archive identity files."""
    h = (ROOT / "archive.sha256").read_text().split()
    m = (ROOT / "verified.sha256").read_text().strip()
    if len(h) != SHA_LINE_PARTS:
        msg = "archive.sha256 must carry exactly the digest and the reviewed name"
        raise RuntimeError(msg)
    if h[1] != ARCHIVE:
        msg = "archive.sha256 names an unreviewed archive"
        raise RuntimeError(msg)
    if not all(re.fullmatch(SHA256_HEX, s) for s in (h[0], m)):
        msg = "archive digests must be lowercase SHA-256 hex"
        raise RuntimeError(msg)
    return {"sha256": h[0], "size": (ROOT / ARCHIVE).stat().st_size, "manifest": m}


class Handler(BaseHTTPRequestHandler):
    """Serve the single reviewed archive over verified bearer TLS."""

    def do_GET(self) -> None:
        """Serve /state or a bounded /part slice to the verified bearer."""
        if not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + os.environ["TOKEN"]
        ):
            self.send_error(HTTP_FORBIDDEN)
            return
        try:
            meta = info()
        except FileNotFoundError:
            self.send_error(HTTP_UNAVAILABLE)
            return
        if self.path == "/state":
            b = json.dumps(meta).encode()
            self.send_response(HTTP_OK)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        x = re.fullmatch(r"/part/([0-9]{1,5})", self.path)
        if not x:
            self.send_error(HTTP_NOT_FOUND)
            return
        pos = int(x[1]) * SIZE
        n = min(SIZE, meta["size"] - pos)
        if n <= 0:
            self.send_error(HTTP_NOT_FOUND)
            return
        self.send_response(HTTP_OK)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        with (ROOT / ARCHIVE).open("rb") as f:
            f.seek(pos)
            while n:
                b = f.read(min(n, 2**20))
                self.wfile.write(b)
                n -= len(b)
                if not b:
                    msg = "archive truncated while serving part"
                    raise RuntimeError(msg)

    @override
    def log_message(self, *args: object) -> None:
        """Keep the private archive size and timing off the logs."""


def _require_remote_meta(meta: ArchiveInfo) -> None:
    """Require the reviewed bounded archive size before copying."""
    if not 0 < meta["size"] < MAX_ARCHIVE_BYTES:
        msg = "remote archive size outside the reviewed bound"
        raise RuntimeError(msg)


def _verify_remote_stable(meta: ArchiveInfo, get: "Callable[[str], bytes]") -> None:
    """Re-read the sender state and require it unchanged after the copy."""
    current: ArchiveInfo = json.loads(get("/state"))
    if current != meta:
        msg = "remote archive changed during transfer"
        raise RuntimeError(msg)


def _copy_part(out: "IO[bytes]", meta: ArchiveInfo, get: "Callable[[str], bytes]", i: int) -> None:
    """Copy one archive part with the reviewed bounded exponential retry."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            b = get("/part/" + str(i))
        except (OSError, http.client.HTTPException, RuntimeError):
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(PART_RETRY_BASE_SECONDS * (attempt + 1))
        else:
            expected = min(SIZE, meta["size"] - i * SIZE)
            if len(b) != expected:
                msg = "part " + str(i) + " length mismatch"
                raise RuntimeError(msg)
            if os.pwrite(out.fileno(), b, i * SIZE) != len(b):
                msg = "part " + str(i) + " short write"
                raise RuntimeError(msg)
            return


def _copy_parts(partial: Path, meta: ArchiveInfo, get: "Callable[[str], bytes]") -> None:
    """Copy every archive part in a bounded parallel retry loop."""
    f = partial.open("xb+")
    with f:

        def part(i: int) -> None:
            _copy_part(f, meta, get, i)

        with ThreadPoolExecutor(PART_PARALLELISM) as pool:
            for i, _result in enumerate(
                pool.map(part, range((meta["size"] + SIZE - 1) // SIZE)), 1
            ):
                if i % 32 == 0:
                    print("copied MiB", i * SIZE // 2**20, flush=True)
        os.fsync(f.fileno())
        f.seek(0)
        if hashlib.file_digest(f, "sha256").hexdigest() != meta["sha256"]:
            msg = "downloaded archive digest differs from the verified cold copy"
            raise RuntimeError(msg)


def _wait_for_state(get: "Callable[[str], bytes]") -> ArchiveInfo:
    """Wait for the sender to publish its verified cold restore."""
    for _ in range(STATE_ATTEMPTS):
        try:
            meta: ArchiveInfo = json.loads(get("/state"))
            break
        except (OSError, RuntimeError):
            time.sleep(STATE_RETRY_SECONDS)
    else:
        msg = "waiting for verified cold restore on 0"
        raise TimeoutError(msg)
    return meta


def receive() -> None:
    """Copy the single reviewed archive, verify its digest, then publish it."""
    os.umask(0o077)
    ctx = ssl.create_default_context(cafile="/ca/tls.crt")
    hdr = {"Authorization": "Bearer " + os.environ["TOKEN"]}

    def get(path: str) -> bytes:
        c = http.client.HTTPSConnection(HOST, 9443, context=ctx, timeout=180)
        try:
            c.request("GET", path, headers=hdr)
            r = c.getresponse()
            if r.status != HTTP_OK:
                raise RuntimeError(path, r.status)
            return r.read()
        finally:
            c.close()

    meta = _wait_for_state(get)
    _require_remote_meta(meta)
    partial = ROOT / (ARCHIVE + ".partial")
    if (ROOT / ARCHIVE).exists():
        msg = "archive already published; refusing to replay the copy"
        raise RuntimeError(msg)
    _copy_parts(partial, meta, get)
    _verify_remote_stable(meta, get)
    os.link(partial, ROOT / ARCHIVE)
    partial.unlink()
    (ROOT / "offload.json").write_text(json.dumps(meta))
    fd = os.open(ROOT, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)
    print("verified off-host archive", json.dumps(meta), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "receive":
        receive()
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain("/tls/tls.crt", "/tls/tls.key")
        s = ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
        s.socket = ctx.wrap_socket(s.socket, server_side=True)
        s.serve_forever()
