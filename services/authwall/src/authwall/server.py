"""HTTP app for the wallpaper gallery and Authentik scene CSS."""

import base64
import email
import io
from PIL import Image
import hmac
import hashlib
import json
import os
import urllib.error
import urllib.request
import threading
import time
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from authwall.db import new_id, open_db
from authwall import responsive
import re
from authwall.optimize import derivatives, full_webp
from authwall.store import notify_n8n, open_store

UI = Path(__file__).resolve().parents[2] / "ui"
PREFIX = "/wallpapers"


def source_key(wallpaper_id: str) -> str:
    return f"sources/{wallpaper_id}"


def full_key(wallpaper_id: str) -> str:
    return f"optimized/{wallpaper_id}.webp"


def thumb_key(wallpaper_id: str) -> str:
    return f"thumbs/{wallpaper_id}.webp"


class App:
    def __init__(self) -> None:
        self.db = open_db()
        self.store = open_store()

    def optimize(self, wallpaper_id: str) -> None:
        row = self.db.get(wallpaper_id)
        if row is None:
            raise KeyError(wallpaper_id)
        self.db.set_status(wallpaper_id, "processing", None, None, None)
        try:
            raw = self.store.get(source_key(wallpaper_id))
            full, thumb, width, height = derivatives(raw)
            responsive.generate(self.store, wallpaper_id, raw)
            self.store.put(full_key(wallpaper_id), full, "image/webp")
            self.store.put(thumb_key(wallpaper_id), thumb, "image/webp")
        except Exception as exc:
            self.db.set_status(wallpaper_id, "failed", None, None, str(exc))
            return
        self.db.set_status(wallpaper_id, "ready", width, height, None)

    def accept_upload(self, filename: str, raw: bytes) -> str:
        wallpaper_id = new_id()
        self.store.put(source_key(wallpaper_id), raw, "application/octet-stream")
        self.db.insert(wallpaper_id, filename or "wallpaper")
        self.db.set_status(wallpaper_id, "processing", None, None, None)
        target = self.optimize_remote if os.environ.get("N8N_WEBHOOK_URL") else self.optimize
        threading.Thread(target=target, args=(wallpaper_id,), daemon=True).start()
        return wallpaper_id

    def optimize_remote(self, wallpaper_id: str) -> None:
        source, full, thumb = source_key(wallpaper_id), full_key(wallpaper_id), thumb_key(wallpaper_id)
        try:
            with Image.open(io.BytesIO(self.store.get(source))) as image:
                if image.format not in {"JPEG", "PNG", "WEBP", "GIF"} or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Unsupported image")
                width, height = image.size
            reply = notify_n8n(wallpaper_id, self.store.job_urls(source, full, thumb))
            url = reply.get("executionUrl", "")
            if not url.startswith("https://"):
                raise ValueError("Missing workflow execution link")
            self.db.set_execution(wallpaper_id, url)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if self.store.has_webp(full) and self.store.has_webp(thumb):
                    self.db.set_status(wallpaper_id, "ready", width, height, None)
                    return
                time.sleep(2)
            raise TimeoutError("Wallpaper workflow did not produce both WebPs")
        except Exception as exc:
            self.db.set_status(wallpaper_id, "failed", None, None, type(exc).__name__ + ": wallpaper processing failed")

    def remove(self, wallpaper_id: str) -> None:
        for tag, _, _ in responsive.variants(self.store, wallpaper_id):
            self.store.delete(responsive.key(wallpaper_id, tag))
        self.store.delete(f"responsive/{wallpaper_id}/index.json")
        for key in (source_key(wallpaper_id), full_key(wallpaper_id), thumb_key(wallpaper_id)):
            try:
                self.store.delete(key)
            except Exception:
                continue
        self.db.delete(wallpaper_id)

    def scene_css(self, seed: str) -> str:
        ids = self.db.active_ready()
        if not ids:
            return "body::before{background:#68776f}\n"
        digest = hashlib.sha256(seed.encode()).digest() if seed else os.urandom(8)
        chosen = ids[int.from_bytes(digest[:4], "big") % len(ids)]
        thumb = base64.b64encode(self.store.get(thumb_key(chosen))).decode()
        full = f"{PREFIX}/media/{chosen}.webp"
        return (
            "body::before{background-size:cover!important;background-position:center!important;"
            f"--wp-photo:url('{full}');background-image:var(--wp-photo),url('data:image/webp;base64,{thumb}')!important;}}\n"
            + responsive.rules(chosen, responsive.variants(self.store, chosen))
        )


def _files(body: bytes, content_type: str) -> list[tuple[str, bytes]]:
    message = email.message_from_bytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
        policy=policy.default,
    )
    found = []
    for part in message.iter_parts():
        name = part.get_filename() or "wallpaper"
        payload = part.get_payload(decode=True) or b""
        if payload:
            found.append((name, payload))
    return found


PUBLIC_PREFIXES = (PREFIX + "/scene.css", PREFIX + "/media/", PREFIX + "/internal/")
_AUTH_CACHE: dict[str, tuple[float, set[str]]] = {}
GALLERY_GROUPS = frozenset({"homelab-owner", "homelab-owners", "app-authwall-manager"})


def _public(path: str) -> bool:
    return path == "/healthz" or any(path.startswith(item) for item in PUBLIC_PREFIXES)


def _group_names(payload: dict) -> set[str]:
    user = payload.get("user", payload)
    names = set()
    for group in user.get("groups") or []:
        if isinstance(group, str):
            names.add(group)
        elif isinstance(group, dict) and group.get("name"):
            names.add(str(group["name"]))
    return names


def groups_from_authentik(headers, original_url: str) -> set[str] | None:
    """Read the browser session from Authentik. None means the API is unreachable."""
    del original_url
    if os.environ.get("WALLPAPER_AUTH", "on") == "off":
        return set(GALLERY_GROUPS)
    cookies = headers.get_all("Cookie") if hasattr(headers, "get_all") else [headers.get("Cookie")]
    cookies = [item for item in (cookies or []) if item]
    if len(cookies) != 1 or len(cookies[0]) > 8192 or "\r" in cookies[0] or "\n" in cookies[0]:
        return set()
    token = hashlib.sha256(cookies[0].encode()).hexdigest()
    cached = _AUTH_CACHE.get(token)
    if cached and cached[0] > time.time():
        return set(cached[1])
    request = urllib.request.Request(
        os.environ.get(
            "WALLPAPER_AUTH_URL",
            "http://authentik-server.identity.svc.cluster.local/api/v3/core/users/me/",
        ),
        headers={"Cookie": cookies[0], "Accept": "application/json"},
    )
    last = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read().decode() or "{}")
            names = _group_names(payload if isinstance(payload, dict) else {})
            _AUTH_CACHE[token] = (time.time() + 60, names)
            return set(names)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                return set()
            last = exc
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last = exc
    del last
    return None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if not extra or "Cache-Control" not in extra:
                self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _gate(self, path: str) -> bool:
            if _public(path):
                return True
            origin = os.environ.get("WALLPAPER_ORIGIN", "https://auth.socrat.alchemmist.xyz")
            groups = groups_from_authentik(self.headers, origin + self.path)
            if groups is None:
                self._json(503, {"error": "auth unavailable"})
                return False
            if not (groups & GALLERY_GROUPS):
                if not groups and self.command == "GET" and path in {PREFIX, PREFIX + "/"}:
                    target = origin + "/if/flow/default-authentication-flow/?next=" + quote(PREFIX + "/")
                    self._send(302, b"", "text/plain", {"Location": target})
                    return False
                self._json(403 if groups else 401, {"error": "forbidden" if groups else "unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/healthz":
                self._json(200, {"ok": True})
                return
            if not self._gate(path):
                return
            if path in {PREFIX, PREFIX + "/"}:
                self._send(200, (UI / "index.html").read_bytes(), "text/html; charset=utf-8")
                return
            if path == PREFIX + "/app.js":
                self._send(200, (UI / "app.js").read_bytes(), "text/javascript; charset=utf-8")
                return
            if path == PREFIX + "/style.css":
                self._send(200, (UI / "style.css").read_bytes(), "text/css; charset=utf-8")
                return
            if path == PREFIX + "/favicon.svg":
                self._send(200, (UI / "favicon.svg").read_bytes(), "image/svg+xml")
                return
            if path == PREFIX + "/scene.css":
                seed = parse_qs(urlparse(self.path).query).get("seed", [""])[0]
                self._send(200, app.scene_css(seed).encode(), "text/css; charset=utf-8")
                return
            if path == PREFIX + "/api/items":
                self._json(200, {"items": app.db.list_all()})
                return
            if path.startswith(PREFIX + "/media/"):
                name = path.removeprefix(PREFIX + "/media/")
                blur = name.endswith("-blur.webp")
                wallpaper_id = name.removesuffix("-blur.webp").removesuffix(".webp")
                key = thumb_key(wallpaper_id) if blur else full_key(wallpaper_id)
                match = re.fullmatch(r"([a-f0-9]+)-([ws]\d+)\.webp", name)
                if match:
                    key = responsive.key(*match.groups())
                try:
                    stream, size = app.store.open_media(key)
                except Exception:
                    self._json(404, {"error": "missing"})
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/webp")
                    self.send_header("Content-Length", str(size))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    while chunk := stream.read(65536):
                        self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    stream.close()
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            # Stable internal callback used by the active n8n workflow.
            if path == "/authwall/internal/lossless":
                path = PREFIX + "/internal/lossless"
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if not self._gate(path):
                return
            if path == PREFIX + "/internal/lossless":
                token = os.environ.get("WALLPAPER_JOB_TOKEN", "")
                if not token or not hmac.compare_digest(self.headers.get("X-Wallpaper-Token", ""), token):
                    self._json(401, {"error": "unauthorized"})
                    return
                wallpaper_id = json.loads(body).get("id", "")
                if app.db.get(wallpaper_id) is None:
                    self._json(404, {"error": "missing"})
                    return
                raw = app.store.get(source_key(wallpaper_id))
                responsive.generate(app.store, wallpaper_id, raw)
                self._send(200, full_webp(raw), "image/webp")
                return
            if path in {PREFIX + "/internal/optimize", PREFIX + "/internal/execution"}:
                token = os.environ.get("WALLPAPER_JOB_TOKEN", "")
                if token and self.headers.get("X-Wallpaper-Token") != token:
                    self._json(401, {"error": "unauthorized"})
                    return
            if path == PREFIX + "/internal/execution":
                payload = json.loads(body.decode() or "{}")
                wallpaper_id = str(payload.get("id") or "")
                url = str(payload.get("executionUrl") or "")
                if app.db.get(wallpaper_id) is None or not url.startswith("https://"):
                    self._json(400, {"error": "bad execution"})
                    return
                app.db.set_execution(wallpaper_id, url)
                self._json(200, {"ok": True})
                return
            if path == PREFIX + "/internal/optimize":
                wallpaper_id = json.loads(body.decode() or "{}").get("id", "")
                if app.db.get(wallpaper_id) is None:
                    self._json(404, {"error": "missing"})
                    return
                app.optimize(wallpaper_id)
                self._json(200, app.db.get(wallpaper_id))
                return
            if path == PREFIX + "/api/upload":
                files = _files(body, self.headers.get("Content-Type", ""))
                if not files:
                    self._json(400, {"error": "empty"})
                    return
                ids = [app.accept_upload(name, raw) for name, raw in files]
                self._json(202, {"ids": ids})
                return
            marker = PREFIX + "/api/items/"
            if path.startswith(marker) and path.endswith("/delete"):
                wallpaper_id = path[len(marker) : -len("/delete")]
                if app.db.get(wallpaper_id) is None:
                    self._json(404, {"error": "missing"})
                    return
                app.remove(wallpaper_id)
                self._json(200, {"ok": True})
                return
            if path.startswith(marker) and path.endswith("/active"):
                wallpaper_id = path[len(marker) : -len("/active")]
                if app.db.get(wallpaper_id) is None:
                    self._json(404, {"error": "missing"})
                    return
                active = bool(json.loads(body.decode() or "{}").get("active"))
                app.db.set_active(wallpaper_id, active)
                self._json(200, app.db.get(wallpaper_id))
                return
            self._json(404, {"error": "not found"})

    return Handler


def serve(app: App | None = None) -> None:
    host = os.environ.get("WALLPAPER_HOST", "0.0.0.0")
    port = int(os.environ.get("WALLPAPER_PORT", "8080"))
    ThreadingHTTPServer((host, port), make_handler(app or App())).serve_forever()


if __name__ == "__main__":
    serve()
