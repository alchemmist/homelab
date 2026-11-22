"""Exercise the repository's Python lint policy without collecting operational tests."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.quality import common

if TYPE_CHECKING:
    from pathlib import Path

with patch.dict(sys.modules, {"common": common}):
    from scripts.quality import strict_guard

SAMPLE = """\
def test_behavior() -> None:
    assert True


class TestBehavior:
    def test_method(self) -> None:
        pass
"""
DOC_RULES = {"D100", "D101", "D102", "D103", "S101"}


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("tests/test_quality_system.py", {"D100", "D101"}),
        ("tests/kubernetes/test_cluster.py", {"D100", "D101"}),
        ("experiments/venice-autonomy/test_continue.py", {"D100", "D101", "D103", "S101"}),
        ("tests/public_entry_contract.py", DOC_RULES - {"S101"}),
        ("scripts/quality/tests.py", DOC_RULES),
        ("ansible/roles/vpn_failover/files/smoke_test.py", DOC_RULES),
        ("experiments/venice-autonomy/protocol_regression.py", DOC_RULES),
    ],
)
def test_ruff_missing_docstrings_follow_module_scope(filename: str, expected: set[str]) -> None:
    result = common.command(
        [
            common.ROOT / ".venv/bin/ruff",
            "check",
            "--config",
            "quality/ruff.toml",
            "--output-format=json",
            "--stdin-filename",
            filename,
            "-",
        ],
        stdin=SAMPLE,
        allowed=(1,),
    )
    assert {item["code"] for item in json.loads(result.stdout)} & DOC_RULES == expected


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("[lint]\n", '[lint]\nextend-ignore = ["D103"]\n'),
        ("[lint]\n", '[lint]\nextend-per-file-ignores = { "scripts/*.py" = ["D102"] }\n'),
        ("\nignore =", "\n# ignore ="),
        ("[lint.per-file-ignores]", "[unused]"),
    ],
)
def test_ruff_ignore_drift_fails_configuration(
    original: str, replacement: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = (common.ROOT / "quality/ruff.toml").read_text()
    policy = json.loads((common.ROOT / "quality/strict-policy.json").read_bytes())
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/ruff.toml").write_text(config.replace(original, replacement))
    monkeypatch.setattr(strict_guard, "ROOT", tmp_path)
    with pytest.raises(ValueError, match=r"Ruff (ignore list|per-file ignores) drifted"):
        strict_guard.verify_ruff_policy(policy)


@pytest.mark.parametrize(
    ("prefix", "directive"),
    [
        ("value = 1  ", "noqa: D102"),
        ("value = 1  ", "type: ignore[arg-type]"),
        ("", "type: ignore"),
        ("", "ruff: NOQA"),
        ("", "flake8: noqa"),
        ("", "ruff: disable[D103]"),
    ],
)
def test_suppression_blocks_owned_source(
    prefix: str,
    directive: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "owned.py"
    source.write_text(f"{prefix}# {directive}\n")
    monkeypatch.setattr(strict_guard, "ROOT", tmp_path)
    monkeypatch.setattr(strict_guard, "tracked", lambda: [source.name])
    monkeypatch.setattr(strict_guard, "verify_configuration", lambda: None)
    assert strict_guard.main() == 1
    assert capsys.readouterr().out.splitlines() == ["suppressions=1", "owned.py:1"]
    source.write_text("value = 1\n")
    assert strict_guard.main() == 0
