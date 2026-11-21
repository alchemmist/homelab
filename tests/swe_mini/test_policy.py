import base64
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "policy", Path(__file__).resolve().parents[2] / "services/swe-mini/policy.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublicationPolicy(unittest.TestCase):
    """Tests for the swe-mini publication policy."""

    def item(self, path="server/app/test.py", mode="100644", content=b"hello\n"):
        return {"path": path, "mode": mode, "content": base64.b64encode(content).decode()}

    def test_safe_patch(self):
        self.assertEqual(len(p.validate_changes([self.item()])), 1)

    def test_protected_paths(self):
        for path in [
            ".github/workflows/run.yml",
            "deploy/x",
            "scripts/x.py",
            "web/package.json",
            "server/migrations/a.py",
            "/etc/passwd",
            "server/app/../../x",
            "common/.env",
            "common/AGENTS.md",
            "server/app//a.py",
            "server/app/./a.py",
            "server/app/a\\b",
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                p.validate_changes([self.item(path)])

    def test_dependency_repair_boundary(self):
        original = {"scripts": {"build": "vite build"}, "dependencies": {"@mantine/core": "^9.5.2"}}
        updated = json.loads(json.dumps(original))
        updated["dependencies"]["@mantine/core"] = "^9.6.0"

        def changes():
            return [
                self.item("web/package.json", content=json.dumps(updated).encode()),
                self.item("web/package-lock.json", content=b'{"lockfileVersion":3,"packages":{}}'),
            ]

        p.validate_dependency_update(p.validate_changes(changes()), original)
        updated["scripts"]["build"] = "true"
        with self.assertRaises(ValueError):
            p.validate_dependency_update(changes(), original)
        updated["scripts"]["build"] = "vite build"
        updated["dependencies"]["new-package"] = "1.0.0"
        with self.assertRaises(ValueError):
            p.validate_dependency_update(changes(), original)
        with self.assertRaises(ValueError):
            p.validate_changes(changes() + [self.item()])

    def test_modes(self):
        for mode in ["120000", "160000", "100755"]:
            with self.assertRaises(ValueError):
                p.validate_changes([self.item(mode=mode)])

    def test_binary_and_size(self):
        for content in [b"\x00", b"x" * (p.MAX_BYTES + 1)]:
            with self.assertRaises(ValueError):
                p.validate_changes([self.item(content=content)])

    def test_empty_duplicates_many(self):
        for items in [
            [],
            [self.item(), self.item()],
            [self.item(f"common/a{i}") for i in range(21)],
        ]:
            with self.assertRaises(ValueError):
                p.validate_changes(items)

    def test_result_roundtrip(self):
        result = {"phase": "work", "checks": {"backend": 0}}
        self.assertEqual(p.decode_result(p.encode_result(result)), result)

    def test_result_authentication(self):
        marker = p.encode_result({"checks": {"backend": 0}}, "parent-only-key")
        self.assertEqual(p.decode_result(marker, "parent-only-key")["checks"]["backend"], 0)
        with self.assertRaises(ValueError):
            p.decode_result(marker, "wrong-key")
        with self.assertRaises(ValueError):
            p.decode_result(p.encode_result({}), "parent-only-key")

    def test_missing_ambiguous_result(self):
        marker = p.encode_result({})
        for text in ["", marker + "\n" + marker]:
            with self.assertRaises(ValueError):
                p.decode_result(text)

    def test_result_decompression_limit(self):
        import gzip

        marker = "SWE_RESULT:" + base64.b64encode(gzip.compress(b"x" * 900_001)).decode()
        with self.assertRaises(ValueError):
            p.decode_result(marker)


if __name__ == "__main__":
    unittest.main()
