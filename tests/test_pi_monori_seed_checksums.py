"""Regression coverage for checksum data passed into remote judge shells."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seed_checksums_remain_positional_shell_data() -> None:
    """Digest values must not be interpolated into remote shell source."""
    census = (ROOT / "services/pi-monori/seed-census.sh").read_text(encoding="utf-8")
    seed = (ROOT / "services/pi-monori/seed.sh").read_text(encoding="utf-8")

    assert 'echo \\\"\\$1  census-seed.tmp\\\"|sha256sum -c -' in census
    assert ' sh "$sha" </dev/null' in census
    assert 'echo \\\"\\$1  /scratch/incoming.tmp\\\" | sha256sum -c -' in seed
    assert ' sh "$expected" </dev/null' in seed
    assert "echo '$sha  census-seed.tmp'" not in census
    assert "echo '$expected  /scratch/incoming.tmp'" not in seed
