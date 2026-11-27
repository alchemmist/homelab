import io
import json
import os
import uuid
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image

from authwall.server import App, make_handler


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (20, 80, 40)).save(buf, format="PNG")
    return buf.getvalue()


class WallpaperTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("N8N_WEBHOOK_URL", None)
        os.environ.pop("RUSTFS_ENDPOINT", None)
        os.environ["WALLPAPER_AUTH"] = "off"
        os.environ["WALLPAPER_SQLITE"] = f"/tmp/authwall-{uuid.uuid4().hex}.sqlite"
        os.environ["WALLPAPER_DIR"] = f"/tmp/authwall-files-{threading.get_ident()}"
        self.app = App()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()

    def test_upload_optimize_toggle_and_scene(self) -> None:
        boundary = "bound"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="lake.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode() + png() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            self.base + "/wallpapers/api/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            wallpaper_id = json.load(res)["ids"][0]
        self.app.optimize(wallpaper_id)
        row = self.app.db.get(wallpaper_id)
        self.assertEqual(row["status"], "ready")
        urllib.request.urlopen(
            urllib.request.Request(
                self.base + f"/wallpapers/api/items/{wallpaper_id}/active",
                data=b'{"active": true}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        ).read()
        css = urllib.request.urlopen(self.base + "/wallpapers/scene.css?seed=login").read().decode()
        self.assertIn(wallpaper_id, css)
        self.assertIn("data:image/webp;base64,", css)
        full = urllib.request.urlopen(self.base + f"/wallpapers/media/{wallpaper_id}.webp").read()
        self.assertTrue(full.startswith(b"RIFF"))

    def test_gallery_delegation(self) -> None:
        from unittest.mock import patch

        for group, status in [("app-authwall-manager", 200), ("homelab-owner", 200), ("homelab-observer", 403)]:
            with self.subTest(group=group), patch("authwall.server.groups_from_authentik", return_value={group}):
                try:
                    with urllib.request.urlopen(self.base + "/wallpapers/api/items") as response:
                        actual = response.status
                except urllib.error.HTTPError as exc:
                    actual = exc.code
                self.assertEqual(actual, status)

    def test_gallery_requires_owner_group(self) -> None:
        os.environ["WALLPAPER_AUTH"] = "on"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(self.base + "/wallpapers/")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertIn("if/flow/default-authentication-flow", exc.headers["Location"])
        else:
            self.fail("anonymous gallery was allowed")
        css = urllib.request.urlopen(self.base + "/wallpapers/scene.css").read()
        self.assertIn(b"body::before", css)
        denied = urllib.request.Request(self.base + "/wallpapers/api/items")
        try:
            urllib.request.urlopen(denied)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 401)
        else:
            self.fail("anonymous api was allowed")
        os.environ["WALLPAPER_AUTH"] = "off"


if __name__ == "__main__":
    unittest.main()
