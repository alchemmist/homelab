"""Offline refusal checks for the dedicated SPI writer Secret renderer."""

import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "writer_helper",
    Path(__file__).resolve().parents[1] / "scripts/rustfs/spi_writer_secret.py",
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

WRITER_SECRET_FILE_MODE = 0o600


class WriterSecret(unittest.TestCase):
    """Prove unsafe writer-secret inputs are refused and a valid render is idempotent."""

    def test_malformed_storage_is_refused(self) -> None:
        """Reject malformed containers and fields before rendering anything."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            source = d / "storage.json"
            for malformed in (
                [],
                {},
                {"root": []},
                {"root": {}},
                {"root": {"access": []}},
            ):
                with self.subTest(storage=malformed):
                    source.write_text(json.dumps(malformed))
                    source.chmod(0o600)
                    with pytest.raises(ValueError, match="^SPI_WRITER_SECRET_PREPARATION_REFUSED$"):
                        helper.render(d)
                    assert not (d / "spi-evidence-writer.secret.json").exists()

    def test_offline_and_refusals(self) -> None:
        """Render a mode-0600 writer Secret only when the journal matches storage."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            storage = {
                r: {"access": r + "-access", "secret": r + "-secret"}
                for r in ("root", "reader", "writer")
            }

            def put(name, obj) -> None:
                p = d / name
                p.write_text(json.dumps(obj))
                p.chmod(0o600)

            put("storage.json", storage)
            with pytest.raises(ValueError):
                helper.render(d)
            journal = {
                storage[r]["access"]: hashlib.sha256(storage[r]["secret"].encode()).hexdigest()
                for r in ("reader", "writer")
            }
            put("bootstrap-journal.json", journal)
            helper.render(d)
            helper.render(d)
            p = d / "spi-evidence-writer.secret.json"
            doc = json.loads(p.read_text())
            assert p.stat().st_mode & 0o777 == WRITER_SECRET_FILE_MODE
            assert doc["metadata"] == {
                "name": "spi-evidence-writer",
                "namespace": "automation",
            }
            assert (
                json.loads(base64.b64decode(doc["data"]["credentials.json"])) == storage["writer"]
            )
            put("bootstrap-journal.json", {})
            with pytest.raises(ValueError):
                helper.render(d)
            put("bootstrap-journal.json", journal)
            put(p.name, {})
            with pytest.raises(ValueError):
                helper.render(d)
            storage["writer"] = storage["root"]
            put("storage.json", storage)
            with pytest.raises(ValueError):
                helper.render(d)
