"""Retention must be gated by a complete, readable successor, never age alone."""

import json
import sys
from pathlib import Path

import pytest

D = Path(__file__).resolve().parents[1] / "charts/thanos/files"
sys.path.insert(0, str(D))
import tier as T

sys.path.pop(0)

IDS = ["01M7ZFFHBY4QFR15BTCFKQQ6E" + v for v in "678"]
NOW = 20000 * T.DAY


def block(i, res, age):
    end = NOW - age * T.DAY
    return {
        "ulid": IDS[i],
        "minTime": end - T.DAY,
        "maxTime": end,
        "thanos": {"labels": {"cluster": "x"}, "downsample": {"resolution": res}},
        "compaction": {"sources": [IDS[0]]},
        "stats": {"numSamples": 100},
    }


class Bucket:
    def __init__(self, ms) -> None:
        self.files = {m["ulid"] + "/meta.json": json.dumps(m).encode() for m in ms}

    def listing(self, groups):
        return [k.split("/")[0] + "/" for k in self.files if k.endswith("/meta.json")]

    def read(self, key, method="GET", absent=False, payload=None):
        if method == "PUT":
            self.files[key] = payload
        return self.files.get(key)


@pytest.mark.parametrize(
    ("age", "readable", "wrong", "expect_raw", "expect_five"),
    [
        (4, True, False, False, False),
        (5, True, False, True, False),
        (89, True, False, True, False),
        (90, True, False, True, True),
        (91, False, False, False, False),
        (91, True, True, True, False),
    ],
)
def test_windows(tmp_path, monkeypatch, age, readable, wrong, expect_raw, expect_five) -> None:
    r, f, h = [block(i, res, age) for i, res in enumerate([0, T.FIVE, T.HOUR])]
    b = Bucket([r, f, h])
    if wrong:
        h["thanos"]["labels"] = {"cluster": "other"}
    p = tmp_path / IDS[2]
    (p / "chunks").mkdir(parents=True)
    (p / "chunks/000001").write_bytes(b"chunk")
    (p / "index").write_bytes(b"index")
    (p / "meta.json").write_text(json.dumps(h))
    monkeypatch.setattr(T.time, "time", lambda: NOW / 1000)
    monkeypatch.setattr(
        T,
        "loaded",
        lambda store: {IDS[1]: f} if store == "thanos-store" else {IDS[2]: h},
    )
    monkeypatch.setattr(T, "serves", lambda *args: readable)
    T.tiers(b, tmp_path, set(), False)
    assert not any("mark.json" in k for k in b.files)
    T.tiers(b, tmp_path, set(), True)
    assert (IDS[0] + "/deletion-mark.json" in b.files) == expect_raw
    assert (IDS[1] + "/deletion-mark.json" in b.files) == expect_five
    assert IDS[2] + "/deletion-mark.json" not in b.files
    if readable and not wrong:
        T.tiers(b, tmp_path, {IDS[2]}, True)
        assert IDS[2] + "/deletion-mark.json" in b.files
        if age < 90:
            assert IDS[1] + "/no-downsample-mark.json" in b.files


def test_gaps_and_unrelated_lineage() -> None:
    a = block(0, 0, 10)
    b = block(1, T.FIVE, 10)
    b["minTime"] += 1
    assert not T.encloses(b, a, T.FIVE)
    b["minTime"] -= 1
    b["compaction"]["sources"] = [IDS[2]]
    assert not T.encloses(b, a, T.FIVE)


def test_store_refusal_is_retried_before_reading_inventory(monkeypatch):
    calls = []

    def read(url):
        calls.append(url)
        if len(calls) == 1:
            raise T.URLError(ConnectionRefusedError())
        return {"blocks": []}

    monkeypatch.setattr(T, "get", read)
    monkeypatch.setattr(T.time, "sleep", lambda _: None)
    assert T.loaded("store") == {}
    assert len(calls) == 2
