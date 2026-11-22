"""Exercise the Python scope contract offline with real Git paths and pinned Ruff."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ci.quality import common, python_scopes

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = (common.ROOT / "quality/ruff.toml").read_bytes()
    directory = tmp_path / "quality/python-scopes"
    directory.mkdir(parents=True)
    (tmp_path / "quality/ruff.toml").write_bytes(config)
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "vendor_prefixes", lambda: ("tests/vendor/",))
    monkeypatch.setattr(common, "frozen_source_files", lambda: {"tests/frozen.py"})
    common.command(["git", "init", "--quiet"])
    return directory


def test_scopes_check_union_without_widening(
    registry: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = common.ROOT
    directive = "noqa: F401"
    invalid = f"import os  # {directive}\n"
    name = "tests/--odd ; name.py"
    for path in [
        name,
        "tests/nested/helper.py",
        "tests/vendor/v.py",
        "tests/frozen.py",
        "tests/log.txt",
    ]:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(invalid)
    (root / "tests/link.py").symlink_to("nested/helper.py")
    common.command(["git", "add", "tests/"])
    (root / "tests/untracked.py").write_text(invalid)
    (registry / "first.json").write_text(json.dumps({"include": ["tests/*.py"], "rules": ["F401"]}))
    (registry / "second.json").write_text(
        json.dumps({"include": ["tests/**/*.py"], "rules": ["S101"]})
    )
    assert python_scopes.main() == 1
    diagnostics = capsys.readouterr().out
    assert f"{name}:1:8: F401" in diagnostics
    (root / name).write_text("value = 1\n")
    assert python_scopes.main() == 0
    (root / "tests/nested/helper.py").write_text("assert False\n")
    assert python_scopes.main() == 1
    assert "tests/nested/helper.py:1:1: S101" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (None, "scope registry"),
        ("{", "bad.json"),
        ("[]", "exactly include and rules"),
        ('{"include":["*.py"],"rules":[]}', "nonempty list"),
        ('{"include":[],"rules":["F401"]}', "nonempty list"),
        ('{"include":"*.py","rules":["F401"]}', "nonempty list"),
        ('{"include":["*.py"],"rules":[1]}', "nonempty list"),
        ('{"include":["*.py"],"rules":["F"]}', "Unknown or removed"),
        ('{"include":["*.py"],"rules":["F999999"]}', "Unknown or removed"),
        ('{"include":["*.py","missing/*.py"],"rules":["F401"]}', "No tracked owned"),
        ('{"include":["../*.py"],"rules":["F401"]}', "repository-relative"),
        ('{"include":["/*.py"],"rules":["F401"]}', "repository-relative"),
        ('{"include":["*.py"],"rules":[],"rules":["F401"]}', "Duplicate JSON"),
        (
            '{"include":["*.py"],"exclude":[],"rules":["F401"]}',
            "exactly include and rules",
        ),
    ],
)
def test_scope_rejects_bad_contract(registry: Path, raw: str | None, error: str) -> None:
    (common.ROOT / "tracked.py").touch()
    common.command(["git", "add", "tracked.py"])
    if raw is not None:
        (registry / "bad.json").write_text(raw)
    with pytest.raises(ValueError, match=error):
        python_scopes.main()
