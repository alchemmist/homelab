"""Only expected Thanos files can enter a cold-copy release manifest."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "retired_tree",
    Path(__file__).resolve().parents[1] / "deploy/storage/thanos-retire/tree.py",
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
UID = "01M7ZQNKDF9JW6PX0TH142HGHX"


def seed(root):
    block = root / UID
    (block / "chunks").mkdir(parents=True)
    (block / "chunks/000001").write_bytes(b"fixture")
    (block / "index").write_bytes(b"index")
    (block / "meta.json").write_text(json.dumps({"ulid": UID}))
    return block


def test_every_file_is_hashed(tmp_path) -> None:
    b = seed(tmp_path)
    m = M.manifest(tmp_path)
    assert len(m["files"]) == 3
    original = M.digest(m)
    (b / "index").write_bytes(b"other")
    assert M.digest(M.manifest(tmp_path)) != original


@pytest.mark.parametrize("name", ["wal", "chunks/live-PVC", "other.json"])
def test_unexpected_files_stop_release(tmp_path, name) -> None:
    b = seed(tmp_path)
    (b / name).write_bytes(b"never unlink")
    with pytest.raises(AssertionError):
        M.shape(tmp_path)


def test_link_and_wrong_meta_refused(tmp_path) -> None:
    b = seed(tmp_path)
    link = b / "chunks/000002"
    link.symlink_to(b / "index")
    with pytest.raises(AssertionError):
        M.shape(tmp_path)
    link.unlink()
    (b / "meta.json").write_text(json.dumps({"ulid": "wrong"}))
    with pytest.raises(AssertionError):
        M.shape(tmp_path)
