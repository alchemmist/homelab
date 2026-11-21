"""One archive only, verified TLS and bearer; receiver publishes only after full SHA-256."""

import hashlib, hmac, http.client, json, os, re, ssl, sys, time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "raw-cold-copy-20261121"
SIZE = 16 * 2**20
ROOT = Path("/data")
ARCHIVE = "raw.tar.zst"


def info():
    h = (ROOT / "archive.sha256").read_text().split()
    m = (ROOT / "verified.sha256").read_text().strip()
    assert (
        len(h) == 2
        and h[1] == ARCHIVE
        and all(re.fullmatch("[0-9a-f]{64}", s) for s in (h[0], m))
    )
    return {"sha256": h[0], "size": (ROOT / ARCHIVE).stat().st_size, "manifest": m}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + os.environ["TOKEN"]
        ):
            self.send_error(403)
            return
        try:
            meta = info()
        except FileNotFoundError:
            self.send_error(503)
            return
        if self.path == "/state":
            b = json.dumps(meta).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        x = re.fullmatch(r"/part/([0-9]{1,5})", self.path)
        if not x:
            self.send_error(404)
            return
        pos = int(x[1]) * SIZE
        n = min(SIZE, meta["size"] - pos)
        if n <= 0:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        with (ROOT / ARCHIVE).open("rb") as f:
            f.seek(pos)
            while n:
                b = f.read(min(n, 2**20))
                assert b
                self.wfile.write(b)
                n -= len(b)

    def log_message(self, *args):
        pass


def receive():
    os.umask(0o077)
    ctx = ssl.create_default_context(cafile="/ca/tls.crt")
    hdr = {"Authorization": "Bearer " + os.environ["TOKEN"]}

    def get(path):
        c = http.client.HTTPSConnection(HOST, 9443, context=ctx, timeout=180)
        try:
            c.request("GET", path, headers=hdr)
            r = c.getresponse()
            assert r.status == 200, (path, r.status)
            return r.read()
        finally:
            c.close()

    for _ in range(2880):
        try:
            meta = json.loads(get("/state"))
            break
        except (OSError, AssertionError):
            time.sleep(5)
    else:
        raise TimeoutError("waiting for verified cold restore on 0")
    assert 0 < meta["size"] < 55 * 2**30
    partial = ROOT / (ARCHIVE + ".partial")
    assert not (ROOT / ARCHIVE).exists()
    with partial.open("xb+") as f:

        def part(i):
            for attempt in range(5):
                try:
                    b = get("/part/" + str(i))
                    assert len(b) == min(SIZE, meta["size"] - i * SIZE)
                    break
                except (OSError, http.client.HTTPException, AssertionError):
                    if attempt == 4:
                        raise
                    time.sleep(3 * (attempt + 1))
            assert os.pwrite(f.fileno(), b, i * SIZE) == len(b)

        with ThreadPoolExecutor(3) as pool:
            for i, _ in enumerate(
                pool.map(part, range((meta["size"] + SIZE - 1) // SIZE)), 1
            ):
                if i % 32 == 0:
                    print("copied MiB", i * SIZE // 2**20, flush=True)
        os.fsync(f.fileno())
        f.seek(0)
        assert hashlib.file_digest(f, "sha256").hexdigest() == meta["sha256"]
    assert info_remote_stable(meta, get)
    os.link(partial, ROOT / ARCHIVE)
    partial.unlink()
    (ROOT / "offload.json").write_text(json.dumps(meta))
    fd = os.open(ROOT, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)
    print("verified off-host archive", json.dumps(meta), flush=True)


def info_remote_stable(meta, get):
    return json.loads(get("/state")) == meta


if __name__ == "__main__":
    if sys.argv[1] == "receive":
        receive()
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain("/tls/tls.crt", "/tls/tls.key")
        s = ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
        s.socket = ctx.wrap_socket(s.socket, server_side=True)
        s.serve_forever()
