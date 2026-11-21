"""Fail-closed and scope checks for the production S3 to hourly shelf copy."""

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "hour_copy",
    Path(__file__).resolve().parents[1] / "charts/thanos/files/hour_copy.py",
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
UID = "01M7ZFFHBY4QFR15BTCFKQQ6E6"


class Bucket:
    def __init__(self, res=3600000):
        self.meta = {
            "ulid": UID,
            "minTime": 0,
            "maxTime": int(time.time() * 1000),
            "compaction": {"sources": [UID]},
            "thanos": {
                "labels": {"fixture": "test"},
                "downsample": {"resolution": res},
            },
        }
        self.obj = {
            "meta.json": json.dumps(self.meta).encode(),
            "index": b"index",
            "chunks/000001": b"payload",
        }

    def listing(self, prefix="", groups=False):
        if groups:
            return {UID + "/": 0}
        return {prefix + k: len(v) for k, v in self.obj.items()}

    def read(self, key, *, sink=None, method="GET", absent=False):
        assert method in ("GET", "HEAD")
        v = self.obj.get(key.split("/", 1)[1])
        if v is None:
            assert absent
            return None
        if sink is None:
            return v
        sink.write(v)
        return len(v), hashlib.sha256(v).hexdigest()


def test_reader_skips_wrong_resolution_and_marked_input(tmp_path):
    MOD.run(Bucket(300000), tmp_path)
    b = Bucket()
    b.obj["deletion-mark.json"] = b"{}"
    MOD.run(b, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_reader_never_replaces_different_existing_hour(tmp_path, monkeypatch):
    from collections import namedtuple

    monkeypatch.setattr(
        MOD.shutil, "disk_usage", lambda _: namedtuple("Space", "free")(100 * 2**30)
    )
    b = Bucket()
    p = tmp_path / UID
    p.mkdir()
    (p / "meta.json").write_bytes(b.obj["meta.json"])
    (p / "index").write_bytes(b"original")
    with pytest.raises(IOError, match="refusing replacement"):
        MOD.run(b, tmp_path)
    assert (p / "index").read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [p]


def test_covered_successor_requires_resolution_labels_and_lineage():
    a = Bucket().meta
    assert MOD.covers(a, a)
    for mutated in [
        dict(a, compaction={"sources": ["other"]}),
        dict(a, thanos={"labels": {}, "downsample": {"resolution": 3600000}}),
        dict(a, minTime=1),
        Bucket(300000).meta,
    ]:
        assert not MOD.covers(mutated, a)
