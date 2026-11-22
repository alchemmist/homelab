"""Exercise the repository's Python lint policy without collecting operational tests."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.quality import common, python_inputs

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


def test_script_docstring_needs_triple_quotes_even_with_double_quote_character() -> None:
    result = common.command(
        [
            common.ROOT / ".venv/bin/ruff",
            "check",
            "--config",
            "quality/ruff.toml",
            "--select",
            "D300,Q002",
            "--ignore-noqa",
            "--output-format=json",
            "--stdin-filename",
            "scripts/example.py",
            "-",
        ],
        stdin='"Existing module documentation."\n',
        allowed=(1,),
    )
    assert [item["code"] for item in json.loads(result.stdout)] == ["D300"]


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


@pytest.mark.parametrize(
    "roots",
    [
        ["scripts/quality/"],
        ["scripts/"],
        ["scripts/", "tests/"],
        ["ansible/", "deploy/", "scripts/", "tests/"],
    ],
)
def test_python_inputs_module_emits_exact_nul_delimited_inventory(roots: list[str]) -> None:
    expected = [
        name
        for name in common.owned(common.tracked())
        if name.startswith(tuple(roots)) and name.endswith(".py")
    ]
    assert expected
    result = common.command([sys.executable, "-m", "scripts.quality.python_inputs", *roots])
    assert result.stdout.split("\0") == [*expected, ""]


def test_python_inputs_use_owned_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = ["scripts/a.py", "scripts/deep/with space.py"]
    tests = ["tests/test_a.py", "tests/nested/helper.py"]
    names = [*scripts, *tests, "tests/vendor/v.py", "tests/readme.md", "services/a.py"]
    monkeypatch.setattr(python_inputs, "tracked", lambda: names)

    def owned(paths: list[str]) -> list[str]:
        assert paths == names
        return [name for name in paths if name != "tests/vendor/v.py"]

    monkeypatch.setattr(python_inputs, "owned", owned)
    assert python_inputs.python_inputs(["scripts/", "tests/"]) == scripts + tests
    assert python_inputs.python_inputs(["tests/", "scripts/", "tests/"]) == tests + scripts


@pytest.mark.parametrize(
    ("names", "roots", "missing"),
    [
        (
            ["scripts/other.py", "scripts/quality/README.md"],
            ["scripts/quality/"],
            "scripts/quality/",
        ),
        (["tests/helper.py", "scripts/README.md"], ["scripts/"], "scripts/"),
        ([], ["scripts/", "tests/"], "scripts/"),
        (["scripts/a.py"], ["scripts/", "tests/"], "tests/"),
        (["tests/a.py"], ["scripts/", "tests/"], "scripts/"),
        (["deploy/a.py", "ansible/a.md"], ["ansible/", "deploy/"], "ansible/"),
        (["ansible/a.py", "deploy/a.md"], ["ansible/", "deploy/"], "deploy/"),
        (
            ["ansible/a.py", "deploy/a.py", "scripts/a.md"],
            ["ansible/", "deploy/", "scripts/"],
            "scripts/",
        ),
        (
            ["ansible/a.py", "deploy/a.py", "scripts/a.py", "tests/a.md"],
            ["ansible/", "deploy/", "scripts/", "tests/"],
            "tests/",
        ),
    ],
)
def test_python_inputs_reject_incomplete_inventory(
    names: list[str], roots: list[str], missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(python_inputs, "tracked", lambda: names)
    monkeypatch.setattr(python_inputs, "owned", list)
    with pytest.raises(ValueError, match=rf"^No tracked owned Python inputs in {missing}$"):
        python_inputs.python_inputs(roots)
