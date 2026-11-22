"""Tests for the Thanos compaction cascade."""

import importlib.util
import json
import unittest
from pathlib import Path
from typing import TypedDict

SOURCE = Path(__file__).resolve().parents[1] / "charts/thanos/files/cascade.py"
SPEC = importlib.util.spec_from_file_location("cascade", SOURCE)
CASCADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CASCADE)

DAY = 86400000
FIVE = CASCADE.FIVE_RESOLUTION
HOUR = CASCADE.HOUR_RESOLUTION
FLOOR = CASCADE.DISK_FLOOR_BYTES


class _Plan(TypedDict):
    """Result shape of the cascade planner."""

    markRaw: list[str]
    copyFive: list[str]
    markFiveSource: list[str]
    markFiveShelf: list[str]
    copyHour: list[str]
    markHourSource: list[str]


def block(ulid, start, end, resolution=0, deletion=False, size=None) -> dict[str, object]:
    item = {
        "ulid": ulid,
        "minTime": start,
        "maxTime": end,
        "resolution": resolution,
        "deletionMark": deletion,
    }
    if size is not None:
        item["bytes"] = size
    return item


def call(raw, five=None, hour=None, now=100 * DAY, disk=None, five_up=True, hour_up=True) -> _Plan:
    result: _Plan = CASCADE.plan(raw, five or [], hour or [], now, disk, five_up, hour_up)
    return result


class CascadePlanTests(unittest.TestCase):
    """Tests for CascadePlanTests."""

    def test_raw_is_not_marked_without_five_minute_coverage(self) -> None:
        raw = [block("raw-old", 0, 2 * DAY)]
        result = call(raw, now=10 * DAY)
        assert result["markRaw"] == []

    def test_raw_older_than_five_days_is_marked_when_covered(self) -> None:
        raw = [
            block("raw-old", 0, 2 * DAY),
            block("five", 0, 2 * DAY, FIVE),
        ]
        result = call(raw, now=8 * DAY)
        assert result["markRaw"] == ["raw-old"]

    def test_raw_younger_than_five_days_is_not_marked(self) -> None:
        raw = [
            block("raw-new", 6 * DAY, 8 * DAY),
            block("five", 6 * DAY, 8 * DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        assert result["markRaw"] == []

    def test_five_minute_blocks_wait_for_an_hourly_block(self) -> None:
        raw = [block("five", 0, DAY, FIVE)]
        result = call(raw)
        assert result["copyFive"] == []
        assert result["markFiveSource"] == []

    def test_covered_five_minute_block_is_copied_when_the_shelf_does_not_have_it(
        self,
    ) -> None:
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        result = call(raw)
        assert result["copyFive"] == ["five"]
        assert result["markFiveSource"] == []

    def test_second_plan_marks_the_source_after_the_shelf_has_the_block(self) -> None:
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        shelf = [block("five", 0, DAY, FIVE)]
        result = call(raw, shelf)
        assert result["copyFive"] == []
        assert result["markFiveSource"] == ["five"]

    def test_marked_source_is_not_marked_again(self) -> None:
        raw = [
            block("five", 0, DAY, FIVE, deletion=True),
            block("hour", 0, DAY, HOUR),
        ]
        shelf = [block("five", 0, DAY, FIVE)]
        result = call(raw, shelf)
        assert result["copyFive"] == []
        assert result["markFiveSource"] == []

    def test_shelf_five_minute_block_is_kept_without_an_hour_on_the_hour_shelf(
        self,
    ) -> None:
        shelf = [block("five", 0, DAY, FIVE)]
        result = call([], shelf, [], now=40 * DAY)
        assert result["markFiveShelf"] == []

    def test_old_shelf_block_is_marked_only_when_its_hour_is_present(self) -> None:
        shelf = [block("five", 0, DAY, FIVE)]
        hours = [block("hour", 0, DAY, HOUR)]
        missing = call([], shelf, [], now=40 * DAY)
        present = call([], shelf, hours, now=40 * DAY)
        assert missing["markFiveShelf"] == []
        assert present["markFiveShelf"] == ["five"]

    def test_unreachable_hour_shelf_copies_and_marks_nothing_hourly(self) -> None:
        raw = [block("hour", 0, DAY, HOUR)]
        shelf = [block("five", 0, DAY, FIVE)]
        hours = [block("hour", 0, DAY, HOUR)]
        result = call(raw, shelf, hours, now=40 * DAY, hour_up=False)
        assert result["copyHour"] == []
        assert result["markHourSource"] == []
        assert result["markFiveShelf"] == []

    def test_unreachable_five_shelf_does_not_copy_or_mark_sources(self) -> None:
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        result = call(raw, [block("five", 0, DAY, FIVE)], five_up=False)
        assert result["copyFive"] == []
        assert result["markFiveSource"] == []

    def test_unknown_disk_does_not_mark_young_shelf_blocks(self) -> None:
        shelf = [block("five", 20 * DAY, 21 * DAY, FIVE, size=1024)]
        hours = [block("hour", 20 * DAY, 21 * DAY, HOUR)]
        result = call([], shelf, hours, now=25 * DAY, disk=None)
        assert result["markFiveShelf"] == []

    def test_low_disk_marks_oldest_covered_blocks_until_the_deficit_is_covered(
        self,
    ) -> None:
        shelf = [
            block("young", 20 * DAY, 21 * DAY, FIVE, size=100),
            block("older", 10 * DAY, 11 * DAY, FIVE, size=70),
            block("oldest", 1 * DAY, 2 * DAY, FIVE, size=50),
        ]
        hours = [
            block("h1", 20 * DAY, 21 * DAY, HOUR),
            block("h2", 10 * DAY, 11 * DAY, HOUR),
            block("h3", 1 * DAY, 2 * DAY, HOUR),
        ]
        result = call([], shelf, hours, now=25 * DAY, disk=FLOOR - 100)
        assert result["markFiveShelf"] == ["older", "oldest"]

    def test_disk_pressure_never_marks_an_uncovered_shelf_block(self) -> None:
        shelf = [block("open", 1 * DAY, 2 * DAY, FIVE, size=10**12)]
        result = call([], shelf, [], now=3 * DAY, disk=0)
        assert result["markFiveShelf"] == []

    def test_hourly_shelf_blocks_are_never_deleted_by_the_planner(self) -> None:
        hours = [block("hour", 0, DAY, HOUR)]
        result = call([], [], hours, now=800 * DAY, disk=0)
        assert result["markFiveShelf"] == []
        assert result["markHourSource"] == []
        assert "hour" not in result["markRaw"]

    def test_hour_is_copied_then_marked_on_the_source(self) -> None:
        raw = [block("hour", 0, DAY, HOUR)]
        first = call(raw, hour=[])
        second = call(raw, hour=[block("hour", 0, DAY, HOUR)])
        assert first["copyHour"] == ["hour"]
        assert second["copyHour"] == []
        assert second["markHourSource"] == ["hour"]

    def test_partial_cover_does_not_count(self) -> None:
        raw = [
            block("raw", 0, 2 * DAY),
            block("five", 0, DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        assert result["markRaw"] == []

    def test_adjacent_covers_count(self) -> None:
        raw = [
            block("raw", 0, 2 * DAY),
            block("a", 0, DAY, FIVE),
            block("b", DAY, 2 * DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        assert result["markRaw"] == ["raw"]


class ParseTests(unittest.TestCase):
    """Tests for ParseTests."""

    def test_parse_ls_reads_concatenated_meta_and_resolutions(self) -> None:
        text = json.dumps(
            {
                "ulid": "A",
                "minTime": 1,
                "maxTime": 2,
                "thanos": {"downsample": {"resolution": 0}},
            },
            indent="\t",
        ) + json.dumps(
            {
                "ulid": "B",
                "minTime": 3,
                "maxTime": 4,
                "thanos": {"downsample": {"resolution": 300000}},
            },
            indent="\t",
        )
        parsed = CASCADE.parse_ls(text)
        assert [item["ulid"] for item in parsed] == ["A", "B"]
        assert [item["resolution"] for item in parsed] == [0, 300000]
        CASCADE.apply_deletion_marks(parsed, ["B"])
        assert parsed[0]["deletionMark"]
        assert not parsed[1]["deletionMark"]


if __name__ == "__main__":
    unittest.main()


def test_shared_pressure_reads_only_one_fresh_bucket_sample(monkeypatch):
    from io import BytesIO
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setenv("FIVE_SHARED", "1")
    rows = [{"value": [0, "123"]}]

    def fetch(url, timeout):
        query = parse_qs(urlparse(url).query)["query"][0]
        assert 'socrat_five_bucket_available_bytes{backing_node="socrat-0"}' in query
        assert "timestamp(" in query and "node_filesystem" not in query
        return BytesIO(json.dumps({"status": "success", "data": {"result": rows}}).encode())

    monkeypatch.setattr(CASCADE.urllib.request, "urlopen", fetch)
    assert CASCADE.disk_free_bytes("http://prom") == 123
    rows *= 2
    assert CASCADE.disk_free_bytes("http://prom") is None
    rows.clear()
    assert CASCADE.disk_free_bytes("http://prom") is None
