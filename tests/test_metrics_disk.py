"""Check allocated metrics bytes using only temporary and synthetic filesystem data."""

import importlib.util
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "charts/thanos/files/disk.py"
SPEC = importlib.util.spec_from_file_location("metrics_disk", SOURCE)
assert SPEC is not None
assert SPEC.loader is not None
DISK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISK)

PROMETHEUS_FILE_BYTES = 1000
EXCLUDED_VOLUME_BYTES = 5000
RAW_FILE_BYTES = 200
SHELF_FILE_BYTES = 300
ALLOCATION_BLOCK_BYTES = 512
FIXTURE_BLOCKS = 8


def _fixture_tree_allocated_bytes(directory: Path) -> int:
    """Independently sum native stat blocks on this owned, nonsymlink fixture tree."""
    return sum(
        path.lstat().st_blocks * ALLOCATION_BLOCK_BYTES
        for path in [directory, *directory.rglob("*")]
    )


class MetricsDiskTest(unittest.TestCase):
    """Temporary-directory checks for Prometheus, raw, and shelf bytes."""

    def test_counts_prometheus_raw_and_shelf_without_other_volumes(self) -> None:
        """Count Prometheus, raw, and shelf bytes without other volumes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prom = (
                root
                / "rancher/k3s/storage"
                / ("pvc-1_cattle-monitoring-system_" + DISK.PROMETHEUS_MARKER + "-0")
            )
            other = root / "rancher/k3s/storage/pvc-2_other"
            raw = root / "socrat-thanos"
            shelf = root / "socrat-thanos-5m"
            for directory in (prom, other, raw, shelf):
                directory.mkdir(parents=True)
            (prom / "block").write_bytes(b"a" * PROMETHEUS_FILE_BYTES)
            (other / "secret").write_bytes(b"b" * EXCLUDED_VOLUME_BYTES)
            (raw / "meta.json").write_bytes(b"c" * RAW_FILE_BYTES)
            (shelf / "thanos").write_bytes(b"d" * SHELF_FILE_BYTES)

            original_rows = DISK.rows(str(root))
            found = {role: (path, size) for role, path, size in original_rows}
            assert set(found) == {"prometheus", "raw", "shelf"}
            assert found["prometheus"][0] == "/var/lib/prometheus"
            assert found["prometheus"][1] >= PROMETHEUS_FILE_BYTES
            assert found["prometheus"][1] == _fixture_tree_allocated_bytes(prom)
            assert found["raw"][0] == "/var/lib/socrat-thanos"
            assert found["shelf"][0] == "/var/lib/socrat-thanos-5m"
            assert found["raw"][1] == _fixture_tree_allocated_bytes(raw)
            assert found["shelf"][1] == _fixture_tree_allocated_bytes(shelf)

            body = DISK.render("socrat-0", DISK.rows(str(root)))
            assert 'node="socrat-0"' in body
            assert 'role="raw"' in body
            assert 'path="/var/lib/socrat-thanos"' in body
            assert "secret" not in body

            (other / "secret").write_bytes(b"b" * EXCLUDED_VOLUME_BYTES * 2)
            (other / "new-file").write_bytes(b"new unrelated data")
            assert DISK.rows(str(root)) == original_rows


@dataclass(frozen=True)
class AllocationStat:
    """Only the two real stat fields read by allocated(), with no signature fiction."""

    st_blocks: int | None
    st_size: int


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (FIXTURE_BLOCKS, FIXTURE_BLOCKS * ALLOCATION_BLOCK_BYTES),
        (0, 0),
        (None, PROMETHEUS_FILE_BYTES),
    ],
)
def test_allocated_uses_blocks_and_explicit_logical_fallback(
    blocks: int | None, expected: int
) -> None:
    """Preserve allocated-block, sparse-zero and unavailable-block fallback semantics."""
    stat = AllocationStat(blocks, PROMETHEUS_FILE_BYTES)
    with patch.object(DISK.os, "lstat", return_value=stat):
        actual = DISK.allocated("/synthetic-not-read")
    assert actual == expected


def test_allocation_overhead_invalidates_foreign_logical_size_threshold() -> None:
    """A legitimate directory plus file can exceed5000without counting another volume."""
    stat = AllocationStat(FIXTURE_BLOCKS, PROMETHEUS_FILE_BYTES)
    with (
        patch.object(DISK.os, "lstat", return_value=stat),
        patch.object(DISK.os, "walk", return_value=[("/synthetic", [], ["block"])]),
    ):
        size = DISK.directory_bytes("/synthetic")
    assert size == 2 * FIXTURE_BLOCKS * ALLOCATION_BLOCK_BYTES
    assert size >= EXCLUDED_VOLUME_BYTES


if __name__ == "__main__":
    unittest.main()


def test_warm_workshop_distinguishes_retained_tree_from_active_and_excludes_seeds(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("WARM_WORKSHOP", "1")
    pvc = (
        tmp_path
        / "rancher/k3s/storage/pvc-fixture_cattle-monitoring-system_thanos-warm-s1-candidate"
    )
    warm = pvc / "workshop-s3"
    warm.mkdir(parents=True)
    (warm / "blob").write_bytes(b"warm")
    (pvc / "seed-ignored").write_bytes(b"seed")
    (tmp_path / "socrat-thanos").mkdir()
    entries = {role: size for role, _, size in DISK.rows(str(tmp_path))}
    assert set(entries) == {"warm", "retained"}
    assert entries["warm"] == _fixture_tree_allocated_bytes(warm)
