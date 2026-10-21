import importlib.util
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "charts/thanos/files/cascade.py"
SPEC = importlib.util.spec_from_file_location("cascade", SOURCE)
CASCADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CASCADE)

DAY = 86400000
FIVE = CASCADE.FIVE_RESOLUTION
HOUR = CASCADE.HOUR_RESOLUTION
FLOOR = CASCADE.DISK_FLOOR_BYTES


def block(ulid, start, end, resolution=0, deletion=False, size=None):
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


def call(raw, five=None, hour=None, now=100 * DAY, disk=None, five_up=True, hour_up=True):
    return CASCADE.plan(raw, five or [], hour or [], now, disk, five_up, hour_up)


class CascadePlanTests(unittest.TestCase):
    def test_raw_is_not_marked_without_five_minute_coverage(self):
        raw = [block("raw-old", 0, 2 * DAY)]
        result = call(raw, now=10 * DAY)
        self.assertEqual(result["markRaw"], [])

    def test_raw_older_than_five_days_is_marked_when_covered(self):
        raw = [
            block("raw-old", 0, 2 * DAY),
            block("five", 0, 2 * DAY, FIVE),
        ]
        result = call(raw, now=8 * DAY)
        self.assertEqual(result["markRaw"], ["raw-old"])

    def test_raw_younger_than_five_days_is_not_marked(self):
        raw = [
            block("raw-new", 6 * DAY, 8 * DAY),
            block("five", 6 * DAY, 8 * DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        self.assertEqual(result["markRaw"], [])

    def test_five_minute_blocks_wait_for_an_hourly_block(self):
        raw = [block("five", 0, DAY, FIVE)]
        result = call(raw)
        self.assertEqual(result["copyFive"], [])
        self.assertEqual(result["markFiveSource"], [])

    def test_covered_five_minute_block_is_copied_when_the_shelf_does_not_have_it(self):
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        result = call(raw)
        self.assertEqual(result["copyFive"], ["five"])
        self.assertEqual(result["markFiveSource"], [])

    def test_second_plan_marks_the_source_after_the_shelf_has_the_block(self):
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        shelf = [block("five", 0, DAY, FIVE)]
        result = call(raw, shelf)
        self.assertEqual(result["copyFive"], [])
        self.assertEqual(result["markFiveSource"], ["five"])

    def test_marked_source_is_not_marked_again(self):
        raw = [
            block("five", 0, DAY, FIVE, deletion=True),
            block("hour", 0, DAY, HOUR),
        ]
        shelf = [block("five", 0, DAY, FIVE)]
        result = call(raw, shelf)
        self.assertEqual(result["copyFive"], [])
        self.assertEqual(result["markFiveSource"], [])

    def test_shelf_five_minute_block_is_kept_without_an_hour_on_the_hour_shelf(self):
        shelf = [block("five", 0, DAY, FIVE)]
        result = call([], shelf, [], now=40 * DAY)
        self.assertEqual(result["markFiveShelf"], [])

    def test_old_shelf_block_is_marked_only_when_its_hour_is_present(self):
        shelf = [block("five", 0, DAY, FIVE)]
        hours = [block("hour", 0, DAY, HOUR)]
        missing = call([], shelf, [], now=40 * DAY)
        present = call([], shelf, hours, now=40 * DAY)
        self.assertEqual(missing["markFiveShelf"], [])
        self.assertEqual(present["markFiveShelf"], ["five"])

    def test_unreachable_hour_shelf_copies_and_marks_nothing_hourly(self):
        raw = [block("hour", 0, DAY, HOUR)]
        shelf = [block("five", 0, DAY, FIVE)]
        hours = [block("hour", 0, DAY, HOUR)]
        result = call(raw, shelf, hours, now=40 * DAY, hour_up=False)
        self.assertEqual(result["copyHour"], [])
        self.assertEqual(result["markHourSource"], [])
        self.assertEqual(result["markFiveShelf"], [])

    def test_unreachable_five_shelf_does_not_copy_or_mark_sources(self):
        raw = [
            block("five", 0, DAY, FIVE),
            block("hour", 0, DAY, HOUR),
        ]
        result = call(raw, [block("five", 0, DAY, FIVE)], five_up=False)
        self.assertEqual(result["copyFive"], [])
        self.assertEqual(result["markFiveSource"], [])

    def test_unknown_disk_does_not_mark_young_shelf_blocks(self):
        shelf = [block("five", 20 * DAY, 21 * DAY, FIVE, size=1024)]
        hours = [block("hour", 20 * DAY, 21 * DAY, HOUR)]
        result = call([], shelf, hours, now=25 * DAY, disk=None)
        self.assertEqual(result["markFiveShelf"], [])

    def test_low_disk_marks_oldest_covered_blocks_until_the_deficit_is_covered(self):
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
        self.assertEqual(result["markFiveShelf"], ["older", "oldest"])

    def test_disk_pressure_never_marks_an_uncovered_shelf_block(self):
        shelf = [block("open", 1 * DAY, 2 * DAY, FIVE, size=10 ** 12)]
        result = call([], shelf, [], now=3 * DAY, disk=0)
        self.assertEqual(result["markFiveShelf"], [])

    def test_hourly_shelf_blocks_are_never_deleted_by_the_planner(self):
        hours = [block("hour", 0, DAY, HOUR)]
        result = call([], [], hours, now=800 * DAY, disk=0)
        self.assertEqual(result["markFiveShelf"], [])
        self.assertEqual(result["markHourSource"], [])
        self.assertNotIn("hour", result["markRaw"])

    def test_hour_is_copied_then_marked_on_the_source(self):
        raw = [block("hour", 0, DAY, HOUR)]
        first = call(raw, hour=[])
        second = call(raw, hour=[block("hour", 0, DAY, HOUR)])
        self.assertEqual(first["copyHour"], ["hour"])
        self.assertEqual(second["copyHour"], [])
        self.assertEqual(second["markHourSource"], ["hour"])

    def test_partial_cover_does_not_count(self):
        raw = [
            block("raw", 0, 2 * DAY),
            block("five", 0, DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        self.assertEqual(result["markRaw"], [])

    def test_adjacent_covers_count(self):
        raw = [
            block("raw", 0, 2 * DAY),
            block("a", 0, DAY, FIVE),
            block("b", DAY, 2 * DAY, FIVE),
        ]
        result = call(raw, now=10 * DAY)
        self.assertEqual(result["markRaw"], ["raw"])


class ParseTests(unittest.TestCase):
    def test_parse_ls_reads_concatenated_meta_and_resolutions(self):
        text = json.dumps({
            "ulid": "A",
            "minTime": 1,
            "maxTime": 2,
            "thanos": {"downsample": {"resolution": 0}},
        }, indent="\t") + json.dumps({
            "ulid": "B",
            "minTime": 3,
            "maxTime": 4,
            "thanos": {"downsample": {"resolution": 300000}},
        }, indent="\t")
        parsed = CASCADE.parse_ls(text)
        self.assertEqual([item["ulid"] for item in parsed], ["A", "B"])
        self.assertEqual([item["resolution"] for item in parsed], [0, 300000])
        CASCADE.apply_deletion_marks(parsed, ["B"])
        self.assertTrue(parsed[0]["deletionMark"])
        self.assertFalse(parsed[1]["deletionMark"])


if __name__ == "__main__":
    unittest.main()
