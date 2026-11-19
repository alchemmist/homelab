"""Offline flow-title reconciliation keeps backups, titles, and flow identity."""

from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/authentik/files/flow_titles.py"
SPEC = importlib.util.spec_from_file_location("flow_titles", SOURCE)
assert SPEC is not None
assert SPEC.loader is not None
FLOW_TITLES: ModuleType = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FLOW_TITLES)

_ORIGINAL_TITLE = "Redirecting to %(app)s"
_RECONCILED_TITLE = "Redirecting"
_MODE_BITS = 0o777
_PRIVATE_FILE_MODE = 0o600
_EXPECTED_TITLE_PATCHES = 2


class FlowTitleTests(unittest.TestCase):
    """In-memory callbacks cover title patches, rollback, and identity refusal."""

    def test_title_only_idempotence_and_original_rollback(self) -> None:
        """PATCH titles once, keep the mode-0600 backup bytes, and restore them."""
        rows: dict[str, dict[str, str]] = {
            slug: {
                "pk": slug,
                "title": _ORIGINAL_TITLE,
                "designation": "authorization",
            }
            for slug in FLOW_TITLES.TITLES
        }
        calls: list[str] = []

        def api(method: str, path: str, value: dict[str, str] | None = None) -> dict[str, str]:
            """Accept a title-only PATCH and return a detached copy of the flow row."""
            slug = path.split("/")[2]
            if method == "PATCH":
                assert value is not None
                assert set(value) == {"title"}
                calls.append(slug)
                rows[slug].update(value)
            return copy.deepcopy(rows[slug])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assert FLOW_TITLES.reconcile(api, root)
            backup = root / "authorization-flow-titles-original.json"
            original = backup.read_bytes()
            assert (backup.stat().st_mode & _MODE_BITS) == _PRIVATE_FILE_MODE
            assert len(calls) == _EXPECTED_TITLE_PATCHES
            assert not FLOW_TITLES.reconcile(api, root)
            assert backup.read_bytes() == original
            assert all(row["title"] == _RECONCILED_TITLE for row in rows.values())
            assert FLOW_TITLES.reconcile(api, root, rollback=True)
            assert all(row["title"] == _ORIGINAL_TITLE for row in rows.values())

    def test_rollback_refuses_different_flow_identity(self) -> None:
        """Rollback refuses when a flow primary key no longer matches the backup."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows: dict[str, dict[str, str]] = {
                slug: {"pk": slug, "title": _ORIGINAL_TITLE} for slug in FLOW_TITLES.TITLES
            }

            def api(method: str, path: str, value: dict[str, str] | None = None) -> dict[str, str]:
                """Apply a truthy payload and return a detached copy of the flow row."""
                del method
                slug = path.split("/")[2]
                if value:
                    rows[slug].update(value)
                return copy.deepcopy(rows[slug])

            FLOW_TITLES.reconcile(api, root)
            rows[next(iter(rows))]["pk"] = "different"
            with pytest.raises(RuntimeError, match="identity changed"):
                FLOW_TITLES.reconcile(api, root, rollback=True)


if __name__ == "__main__":
    unittest.main()
