"""Offline contracts for the one-node runtime cold cutover; never SSH or migrate."""

import ast
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/socrat5-runtime-boot-migrate.py"


class RuntimeBootMigrationTest(unittest.TestCase):
    """Validate the runtime boot migration script stays valid."""
    def test_python_parses(self) -> None:
        ast.parse(SCRIPT.read_text())

    def test_cold_mode_requires_a_different_boot(self) -> None:
        text = SCRIPT.read_text()
        assert "assert boot_id() != x[\"original_boot_id\"]" in text
        assert '["pgrep", "-x", "containerd"]' in text
        assert '["pgrep", "-x", "k3s-server"]' in text

    def test_copy_is_checked_before_original_rename(self) -> None:
        text = SCRIPT.read_text()
        assert text.index("assert not v.stdout.strip()") < text.index("S.rename(old)")
        assert '"--numeric-ids"' in text
        assert '"cold-verify"' in text

    def test_no_original_removal_or_pvc_relocation(self) -> None:
        text = SCRIPT.read_text()
        assert "rmtree" not in text
        assert "k3s/storage" not in text
        assert "ssd-retained-boot-20261120" in text


if __name__ == "__main__":
    unittest.main()
