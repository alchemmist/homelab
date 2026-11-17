import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vendor_contracts", ROOT / "scripts/check_vendor_contracts.py"
)
vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor)


class VendorContracts(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        (root / "chart/templates").mkdir(parents=True)
        (root / "chart/templates/deployment.yaml").write_text("accepted template\n")
        tree = {
            "path": "chart",
            "basis": "reviewed-git-baseline",
            "reviewedCommit": "fixture",
            "provenanceNote": "Test baseline only, not upstream provenance.",
            "files": vendor.inventory(root, "chart"),
        }
        (root / "deploy/contracts").mkdir(parents=True)
        (root / "deploy/contracts/vendors.json").write_text(
            json.dumps({"schemaVersion": 1, "trees": [tree]})
        )
        return root

    def test_registered_real_trees(self):
        registered_trees = 4
        assert vendor.check(ROOT) == registered_trees

    def test_baseline_is_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            assert vendor.check(root) == 1
            assert before == {p: p.read_bytes() for p in before}

    def test_added_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            (root / "chart/templates/unreviewed-hook.yaml").write_text("hook")
            with pytest.raises(ValueError, match=r"added=.*unreviewed-hook"):
                vendor.check(root)

    def test_removed_or_changed_file_is_rejected(self):
        for mode in ["removed", "changed"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root = self.fixture(d)
                p = root / "chart/templates/deployment.yaml"
                if mode == "removed":
                    p.unlink()
                else:
                    p.write_text("different template")
                with pytest.raises(ValueError, match=rf"{mode}=.*deployment\.yaml"):
                    vendor.check(root)

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            (root / "chart/escape").symlink_to(root / "deploy", target_is_directory=True)
            with pytest.raises(ValueError, match="Symlink"):
                vendor.check(root)

    def test_duplicate_tree_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root / "deploy/contracts/vendors.json"
            c = json.loads(p.read_text())
            c["trees"] *= 2
            p.write_text(json.dumps(c))
            with pytest.raises(ValueError, match="Duplicate"):
                vendor.check(root)

    def test_registered_alias_cannot_be_retargeted_or_copied(self):
        for mode in ["retarget", "copy", "missing", "extra"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root = self.fixture(d)
                link = root / "aliases/component.tgz"
                link.parent.mkdir()
                target = root / "chart/templates/deployment.yaml"
                link.symlink_to(target)
                p = root / "deploy/contracts/vendors.json"
                c = json.loads(p.read_text())
                c["linkInventoryGlobs"] = ["aliases/*.tgz"]
                c["links"] = {"aliases/component.tgz": "chart/templates/deployment.yaml"}
                p.write_text(json.dumps(c))
                assert vendor.check(root) == 1
                if mode == "extra":
                    (link.parent / "unknown.tgz").symlink_to(target)
                else:
                    link.unlink()
                    if mode == "retarget":
                        link.symlink_to(root / "deploy/contracts/vendors.json")
                    elif mode == "copy":
                        link.write_bytes(target.read_bytes())
                with pytest.raises(ValueError, match="alias"):
                    vendor.check(root)


if __name__ == "__main__":
    unittest.main()
