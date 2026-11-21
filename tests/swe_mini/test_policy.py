"""Tests for the swe-mini policy module."""

import base64
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "policy", Path(__file__).resolve().parents[2] / "services/swe-mini/policy.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublicationPolicy(unittest.TestCase):
    """Tests for the swe-mini publication policy."""

    def item(self, path="server/app/test.py", mode="100644", content=b"hello\n") -> dict[str, str]:
        """Return a change item with sensible defaults for assertions."""


        return {"path": path, "mode": mode, "content": base64.b64encode(content).decode()}

    def test_safe_patch(self) -> None:
        """Accept a single conventional source file change."""

        assert len(p.validate_changes([self.item()])) == 1

    def test_protected_paths(self) -> None:
        """Reject paths outside the allowed server/app source tree."""

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

    def test_dependency_repair_boundary(self) -> None:
        """Permit version bumps but reject script or package-list changes."""

        original = {"scripts": {"build": "vite build"}, "dependencies": {"@mantine/core": "^9.5.2"}}
        updated = json.loads(json.dumps(original))
        updated["dependencies"]["@mantine/core"] = "^9.6.0"

        def changes() -> list[dict[str, str]]:
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

    def test_modes(self) -> None:
        """Reject symlink, submodule, and executable file modes."""

        for mode in ["120000", "160000", "100755"]:
            with self.assertRaises(ValueError):
                p.validate_changes([self.item(mode=mode)])

    def test_binary_and_size(self) -> None:
        """Reject binary content and payloads above the size limit."""

        for content in [b"\x00", b"x" * (p.MAX_BYTES + 1)]:
            with self.assertRaises(ValueError):
                p.validate_changes([self.item(content=content)])

    def test_empty_duplicates_many(self) -> None:
        """Reject empty, duplicate, or oversized change sets."""

        for items in [
            [],
            [self.item(), self.item()],
            [self.item(f"common/a{i}") for i in range(21)],
        ]:
            with self.assertRaises(ValueError):
                p.validate_changes(items)

    def test_result_roundtrip(self) -> None:
        """Encode and decode a result marker without loss."""

        result = {"phase": "work", "checks": {"backend": 0}}
        assert p.decode_result(p.encode_result(result)) == result

    def test_result_authentication(self) -> None:
        """Enforce the phase key when decoding result markers."""

        marker = p.encode_result({"checks": {"backend": 0}}, "parent-only-key")
        assert p.decode_result(marker, "parent-only-key")["checks"]["backend"] == 0
        with self.assertRaises(ValueError):
            p.decode_result(marker, "wrong-key")
        with self.assertRaises(ValueError):
            p.decode_result(p.encode_result({}), "parent-only-key")

    def test_missing_ambiguous_result(self) -> None:
        """Reject missing markers and duplicated marker text."""

        marker = p.encode_result({})
        for text in ["", marker + "\n" + marker]:
            with self.assertRaises(ValueError):
                p.decode_result(text)

    def test_result_decompression_limit(self) -> None:
        """Reject markers whose decompressed payload exceeds the cap."""

        import gzip

        marker = "SWE_RESULT:" + base64.b64encode(gzip.compress(b"x" * 900_001)).decode()
        with self.assertRaises(ValueError):
            p.decode_result(marker)


if __name__ == "__main__":
    unittest.main()
