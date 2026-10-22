import json
import os
import re
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ULID = re.compile(r"^[0-9A-Z]{26}$")


def safe_relative(path):
    if not path or path.startswith("/") or "\\" in path:
        raise ValueError("bad path")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("bad path")
    return parts


def staging_path(directory, ulid):
    return os.path.join(directory, "." + ulid + ".incoming")


def block_path(directory, ulid):
    return os.path.join(directory, ulid)


def read_block(directory, ulid):
    meta_path = os.path.join(block_path(directory, ulid), "meta.json")
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    downsample = ((meta.get("thanos") or {}).get("downsample") or {})
    return {
        "ulid": meta.get("ulid") or ulid,
        "minTime": int(meta["minTime"]),
        "maxTime": int(meta["maxTime"]),
        "resolution": int(downsample.get("resolution") or 0),
        "deletionMark": os.path.isfile(os.path.join(block_path(directory, ulid), "deletion-mark.json")),
    }


def list_blocks(directory):
    if not os.path.isdir(directory):
        return []
    blocks = []
    for name in sorted(os.listdir(directory)):
        if not ULID.match(name):
            continue
        meta_path = os.path.join(directory, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        blocks.append(read_block(directory, name))
    return blocks


def begin(directory, ulid):
    if not ULID.match(ulid):
        raise ValueError("bad ulid")
    path = staging_path(directory, ulid)
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, mode=0o775)


def write_file(directory, ulid, relative, chunks):
    if not ULID.match(ulid):
        raise ValueError("bad ulid")
    parts = safe_relative(relative)
    root = staging_path(directory, ulid)
    if not os.path.isdir(root):
        raise FileNotFoundError(ulid)
    destination = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(destination), mode=0o775, exist_ok=True)
    temporary = destination + ".tmp"
    with open(temporary, "wb") as handle:
        for chunk in chunks:
            handle.write(chunk)
    os.replace(temporary, destination)


def commit(directory, ulid):
    if not ULID.match(ulid):
        raise ValueError("bad ulid")
    staged = staging_path(directory, ulid)
    with open(os.path.join(staged, "meta.json"), encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("ulid") != ulid:
        raise ValueError("ulid mismatch")
    final = block_path(directory, ulid)
    if os.path.isdir(final):
        previous = final + ".previous"
        if os.path.isdir(previous):
            shutil.rmtree(previous)
        os.rename(final, previous)
        os.rename(staged, final)
        shutil.rmtree(previous)
        return
    os.rename(staged, final)


def mark_deleted(directory, ulid, details="cascade"):
    if not ULID.match(ulid):
        raise ValueError("bad ulid")
    root = block_path(directory, ulid)
    if not os.path.isdir(root):
        raise FileNotFoundError(ulid)
    body = json.dumps({
        "id": ulid,
        "version": 1,
        "details": details,
        "deletion_time": int(time.time()),
    })
    target = os.path.join(root, "deletion-mark.json")
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(temporary, target)


def handler(directory, token):
    class ShelfHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def authorized(self):
            header = self.headers.get("Authorization", "")
            supplied = header[7:] if header.startswith("Bearer ") else ""
            if len(supplied) != len(token) or supplied != token:
                self.send_error(401)
                return False
            return True

        def read_chunks(self):
            remaining = int(self.headers.get("Content-Length", "0"))
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                self.send_json(200, {"ok": True})
                return
            if not self.authorized():
                return
            if self.path.split("?", 1)[0] == "/v1/blocks":
                self.send_json(200, list_blocks(directory))
                return
            self.send_error(404)

        def route(self):
            parts = [part for part in self.path.split("?", 1)[0].split("/") if part]
            if len(parts) < 3 or parts[0] != "v1" or parts[1] != "blocks":
                return None
            return parts[2], parts[3:]

        def do_POST(self):
            if not self.authorized():
                return
            route = self.route()
            if route is None:
                self.send_error(404)
                return
            ulid, rest = route
            try:
                if rest == []:
                    begin(directory, ulid)
                elif rest == ["commit"]:
                    commit(directory, ulid)
                elif rest == ["deletion-mark"]:
                    mark_deleted(directory, ulid)
                else:
                    self.send_error(404)
                    return
            except FileNotFoundError:
                self.send_error(404)
                return
            except (ValueError, OSError, json.JSONDecodeError):
                self.send_error(400)
                return
            self.send_json(200, {"ok": True})

        def do_PUT(self):
            if not self.authorized():
                return
            route = self.route()
            if route is None or len(route[1]) < 2 or route[1][0] != "files":
                self.send_error(404)
                return
            ulid, rest = route
            try:
                write_file(directory, ulid, "/".join(rest[1:]), self.read_chunks())
            except FileNotFoundError:
                self.send_error(404)
                return
            except (ValueError, OSError):
                self.send_error(400)
                return
            self.send_json(200, {"ok": True})

    return ShelfHandler


def serve(directory, token, port=8080):
    server = ThreadingHTTPServer(("0.0.0.0", port), handler(directory, token))
    server.serve_forever()


def main():
    directory = os.environ["SHELF_DIRECTORY"]
    token = os.environ.get("SHELF_TOKEN")
    if not token:
        token = open(os.environ["SHELF_TOKEN_FILE"], encoding="utf-8").read().strip()
    port = int(os.environ.get("SHELF_PORT", "8080"))
    os.makedirs(directory, mode=0o775, exist_ok=True)
    serve(directory, token, port)


if __name__ == "__main__":
    main()
