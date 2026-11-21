"""HTTP service that stores and manages Thanos blocks on the shelf."""
import json
import os
import re
import shutil
import time
from collections.abc import Iterator
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
    downsample = (meta.get("thanos") or {}).get("downsample") or {}
    return {
        "ulid": meta.get("ulid") or ulid,
        "minTime": int(meta["minTime"]),
        "maxTime": int(meta["maxTime"]),
        "resolution": int(downsample.get("resolution") or 0),
        "deletionMark": os.path.isfile(
            os.path.join(block_path(directory, ulid), "deletion-mark.json")
        ),
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
        handle.writelines(chunks)
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
    body = json.dumps(
        {
            "id": ulid,
            "version": 1,
            "details": details,
            "deletion_time": int(time.time()),
        }
    )
    target = os.path.join(root, "deletion-mark.json")
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(temporary, target)


def _authorized(handler: BaseHTTPRequestHandler, token: str) -> bool:
    header = handler.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    if len(supplied) != len(token) or supplied != token:
        handler.send_error(401)
        return False
    return True


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _route_parts(path: str) -> tuple[str, list[str]] | None:
    parts = [part for part in path.split("?", 1)[0].split("/") if part]
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "blocks":
        return None
    return parts[2], parts[3:]


def _read_chunks(handler: BaseHTTPRequestHandler) -> Iterator[bytes]:
    remaining = int(handler.headers.get("Content-Length", "0"))
    while remaining:
        chunk = handler.rfile.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk


def _serve_get(handler: BaseHTTPRequestHandler, directory: str, token: str) -> None:
    if handler.path == "/healthz":
        _send_json(handler, 200, {"ok": True})
        return
    if not _authorized(handler, token):
        return
    if handler.path.split("?", 1)[0] == "/v1/blocks":
        _send_json(handler, 200, list_blocks(directory))
        return
    handler.send_error(404)


def _serve_post(handler: BaseHTTPRequestHandler, directory: str, token: str) -> None:
    if not _authorized(handler, token):
        return
    route = _route_parts(handler.path)
    if route is None:
        handler.send_error(404)
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
            handler.send_error(404)
            return
    except FileNotFoundError:
        handler.send_error(404)
        return
    except (ValueError, OSError, json.JSONDecodeError):
        handler.send_error(400)
        return
    _send_json(handler, 200, {"ok": True})


def _serve_put(handler: BaseHTTPRequestHandler, directory: str, token: str) -> None:
    if not _authorized(handler, token):
        return
    route = _route_parts(handler.path)
    if route is None or len(route[1]) < 2 or route[1][0] != "files":
        handler.send_error(404)
        return
    ulid, rest = route
    try:
        write_file(directory, ulid, "/".join(rest[1:]), _read_chunks(handler))
    except FileNotFoundError:
        handler.send_error(404)
        return
    except (ValueError, OSError):
        handler.send_error(400)
        return
    _send_json(handler, 200, {"ok": True})


def handler(directory, token):
    class ShelfHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def authorized(self):
            return _authorized(self, token)

        def read_chunks(self):
            return _read_chunks(self)

        def send_json(self, status, payload):
            return _send_json(self, status, payload)

        def do_GET(self):
            return _serve_get(self, directory, token)

        def route(self):
            return _route_parts(self.path)

        def do_POST(self):
            return _serve_post(self, directory, token)

        def do_PUT(self):
            return _serve_put(self, directory, token)

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
