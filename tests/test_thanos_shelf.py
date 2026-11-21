"""Tests for the Thanos shelf configuration."""

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative) -> ModuleType:
    source = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SHELF = load("shelf_server", "charts/thanos/files/shelf.py")
CASCADE = load("cascade_shelf", "charts/thanos/files/cascade.py")
ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SHELF_RESOLUTION_MS = 300000


class ShelfTransferTest(unittest.TestCase):
    """Upload, list, and mark one shelf block without leaving the temp root."""

    def test_upload_lists_and_marks_without_path_escape(self) -> None:
        """Store one block, mark it deleted, and reject a path escape."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "raw" / ULID
            (source / "chunks").mkdir(parents=True)
            meta = {
                "ulid": ULID,
                "minTime": 1,
                "maxTime": 2,
                "thanos": {"downsample": {"resolution": 300000}},
            }
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
                assert ok
                assert listed[0]["ulid"] == ULID
                assert listed[0]["resolution"] == SHELF_RESOLUTION_MS
                assert not listed[0]["deletionMark"]
                CASCADE.mark_shelf(base, "token", [ULID])
                listed, ok = CASCADE.fetch_shelf(base, "token")
                assert listed[0]["deletionMark"]
                assert (shelf_dir / ULID / "chunks" / "000001").read_bytes() == b"abc"
                with self.assertRaises(ValueError):
                    SHELF.write_file(str(shelf_dir), ULID, "../escape", [b"no"])
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
