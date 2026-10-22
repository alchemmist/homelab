import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    source = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SHELF = load("shelf_server", "charts/thanos/files/shelf.py")
CASCADE = load("cascade_shelf", "charts/thanos/files/cascade.py")
ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class ShelfTransferTest(unittest.TestCase):
    def test_upload_lists_and_marks_without_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "raw" / ULID
            (source / "chunks").mkdir(parents=True)
            meta = {"ulid": ULID, "minTime": 1, "maxTime": 2, "thanos": {"downsample": {"resolution": 300000}}}
            (source / "meta.json").write_text(json.dumps(meta))
            (source / "chunks" / "000001").write_bytes(b"abc")
            shelf_dir = Path(tmp) / "shelf"
            shelf_dir.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), SHELF.handler(str(shelf_dir), "token"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = "http://127.0.0.1:%d" % server.server_address[1]
                CASCADE.upload_block(base, "token", str(Path(tmp) / "raw"), ULID)
                listed, ok = CASCADE.fetch_shelf(base, "token")
                self.assertTrue(ok)
                self.assertEqual(listed[0]["ulid"], ULID)
                self.assertEqual(listed[0]["resolution"], 300000)
                self.assertFalse(listed[0]["deletionMark"])
                CASCADE.mark_shelf(base, "token", [ULID])
                listed, ok = CASCADE.fetch_shelf(base, "token")
                self.assertTrue(listed[0]["deletionMark"])
                self.assertTrue((shelf_dir / ULID / "chunks" / "000001").read_bytes() == b"abc")
                with self.assertRaises(ValueError):
                    SHELF.write_file(str(shelf_dir), ULID, "../escape", [b"no"])
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
