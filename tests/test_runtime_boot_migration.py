"""Offline contracts for the one-node runtime cold cutover; never SSH or migrate."""
import ast
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/socrat5-runtime-boot-migrate.py"


class RuntimeBootMigrationTest(unittest.TestCase):
    def test_python_parses(self):
        ast.parse(SCRIPT.read_text())

    def test_cold_mode_requires_a_different_boot(self):
        text = SCRIPT.read_text()
        self.assertIn("assert boot_id()!=x['original_boot_id']", text)
        self.assertIn("'pgrep','-x','containerd'", text)
        self.assertIn("'pgrep','-x','k3s-server'", text)

    def test_copy_is_checked_before_original_rename(self):
        text = SCRIPT.read_text()
        self.assertLess(text.index("assert not v.stdout.strip()"), text.index("S.rename(old)"))
        self.assertIn("'--numeric-ids'", text)
        self.assertIn("'cold-verify'", text)

    def test_no_original_removal_or_pvc_relocation(self):
        text = SCRIPT.read_text()
        self.assertNotIn("rmtree", text)
        self.assertNotIn("k3s/storage", text)
        self.assertIn("ssd-retained-boot-20261120", text)


if __name__ == "__main__":
    unittest.main()
