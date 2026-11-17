"""Dependency gates retain source-lock vulnerabilities and refuse unsupported coverage."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.quality import common

if TYPE_CHECKING:
    from pathlib import Path

with patch.dict(sys.modules, {"common": common}):
    from scripts.quality import lint


_LOCAL_AUDIT = ["pip-audit", "--local", "--strict", "--format", "json"]


def _lock(path: Path, text: str | None = None) -> None:
    """Write a synthetic hashed lock, never install its deliberately fake package."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        text = "fixture-package==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
    path.write_text(text)


def test_environment_audit_cannot_hide_service_lock_vulnerabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same advisory in two ownership scopes must remain two source findings."""
    source = "services/fixture/requirements.txt"
    _lock(tmp_path / source)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def audit(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert kwargs == {"allowed": (0, 1), "timeout": 300}
        payload = {
            "dependencies": [
                {
                    "name": "fixture-package",
                    "version": "1.0",
                    "vulns": [{"id": "GHSA-fixture"}, {"id": "GHSA-fixture"}],
                }
            ]
        }
        return subprocess.CompletedProcess(argv, 1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(lint, "command", audit)
    findings, count = lint.check_dependencies(["uv.lock", source])
    expected_sources = {"uv.lock", source}
    assert {finding["location"]["path"] for finding in findings} == expected_sources
    assert len(findings) == len(expected_sources)
    assert len({finding["id"] for finding in findings}) == len(expected_sources)
    assert count == len(expected_sources)
    assert calls == [
        _LOCAL_AUDIT,
        [
            "pip-audit",
            "--strict",
            "--disable-pip",
            "--no-deps",
            "--require-hashes",
            "--requirement",
            source,
            "--format",
            "json",
        ],
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        False,
        {},
        {"dependencies": []},
        {"dependencies": "not-a-list"},
        {"dependencies": [None]},
        {
            "dependencies": [
                {"name": "fixture", "version": "1", "vulns": [], "skip_reason": "uncollected"}
            ]
        },
        {"dependencies": [{"name": "fixture", "version": "1", "vulns": None}]},
        {"dependencies": [{"name": "fixture", "version": "1", "vulns": [{}]}]},
        {"dependencies": [{"name": "fixture", "version": "1", "vulns": [{"id": ""}]}]},
    ],
)
def test_incomplete_dependency_protocol_never_means_clean(payload: object) -> None:
    """Empty, skipped and malformed results cannot produce a successful audit."""
    with pytest.raises((TypeError, ValueError), match="malformed, empty, or skipped"):
        lint.dependency_report(payload, "uv.lock")


@pytest.mark.parametrize(
    "text",
    [
        "-r /not-an-allowed-source\n",
        "--index-url https://example.invalid/simple\n",
        "fixture @ https://example.invalid/package.whl\n",
        "fixture==1\n",
        "# no audited distributions\n",
        "fixture==1 \\\n    --hash=sha256:not-a-digest\n",
    ],
)
def test_requirement_directives_are_rejected_before_external_auditing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    """Unsafe source options cannot direct the collector outside the repository."""
    source = "services/fixture/requirements.txt"
    _lock(tmp_path / source, text)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    calls: list[list[str]] = []

    def audit(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = {"dependencies": [{"name": "fixture", "version": "1", "vulns": []}]}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(lint, "command", audit)
    with pytest.raises(ValueError, match="unsupported or unsafe source directives"):
        lint.check_dependencies([source])
    assert calls == [_LOCAL_AUDIT]


@pytest.mark.parametrize(
    ("metadata", "expected_rule"),
    [
        ("tools/fixture/package-lock.json", "DEPENDENCY_LOCK_UNAUDITED"),
        ("tools/fixture/package.json", "DEPENDENCY_LOCK_MISSING"),
        ("services/fixture/requirements.in", "DEPENDENCY_LOCK_MISSING"),
    ],
)
def test_unknown_or_missing_lock_auditing_remains_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: str, expected_rule: str
) -> None:
    """Unsupported source ecosystems are findings, not inferred clean dependencies."""
    path = tmp_path / metadata
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    payload = {"dependencies": [{"name": "fixture", "version": "1", "vulns": []}]}
    with patch.object(
        lint,
        "command",
        return_value=subprocess.CompletedProcess(
            _LOCAL_AUDIT,
            0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    ) as audit:
        findings, count = lint.check_dependencies([metadata])
    assert [finding["ruleId"] for finding in findings] == [expected_rule]
    assert findings[0]["location"]["path"] == metadata
    expected_distributions = 1
    assert count == expected_distributions
    audit.assert_called_once()


def test_requirement_symlink_refuses_before_external_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a repository-local symlink is not accepted as a regular source lock."""
    actual = tmp_path / "fixture.txt"
    _lock(actual)
    (tmp_path / "requirements.txt").symlink_to(actual)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    payload = {"dependencies": [{"name": "fixture", "version": "1", "vulns": []}]}
    with (
        patch.object(
            lint,
            "command",
            return_value=subprocess.CompletedProcess(
                _LOCAL_AUDIT,
                0,
                stdout=json.dumps(payload),
                stderr="",
            ),
        ) as audit,
        pytest.raises(ValueError, match="tracked regular repository file"),
    ):
        lint.check_dependencies(["requirements.txt"])
    audit.assert_called_once()


def test_distinct_versions_of_one_dependency_are_not_deduplicated() -> None:
    """Different locked versions retain their distinct vulnerable source contexts."""
    versions = ("1.0", "2.0")
    payload = {
        "dependencies": [
            {"name": "fixture", "version": version, "vulns": [{"id": "GHSA-fixture"}]}
            for version in versions
        ]
    }
    findings, count = lint.dependency_report(payload, "uv.lock")
    assert count == len(versions)
    assert len(findings) == len(versions)
    assert len({finding["id"] for finding in findings}) == len(versions)


@pytest.mark.parametrize(
    ("exit_code", "vulnerabilities"),
    [
        (1, []),
        (0, [{"id": "GHSA-fixture"}]),
    ],
)
def test_dependency_exit_status_cannot_contradict_report(
    exit_code: int,
    vulnerabilities: list[dict[str, str]],
) -> None:
    """A failed collector with a clean-looking JSON body is not source acceptance."""
    payload = {
        "dependencies": [
            {
                "name": "fixture",
                "version": "1",
                "vulns": vulnerabilities,
            }
        ]
    }
    with (
        patch.object(
            lint,
            "command",
            return_value=subprocess.CompletedProcess(
                _LOCAL_AUDIT,
                exit_code,
                stdout=json.dumps(payload),
                stderr="",
            ),
        ),
        pytest.raises(ValueError, match="malformed, empty, or skipped"),
    ):
        lint.check_dependencies([])
