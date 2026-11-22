"""Regression contracts for quality evidence, provenance, and report identity."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
common = importlib.import_module("ci.quality.common")
strict_report = importlib.import_module("ci.quality.strict_report")

_FROZEN_FILE_COUNT = 17
_REVIEWED_NONSECRET_COUNT = 51
_GIT_SHA1_LENGTH = 40
_GIT_SHA256_LENGTH = 64
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_REPORT_NOTES = (
    "Full-tree check. Historical ci/quality/debt files do not decide success "
    "and cannot be regenerated. Reviewed secret false positives are exact "
    "id/path/rule matches only."
)
_COMMAND_FAILURE_DETAIL = (
    "Quality tool/setup/protocol failed. No debt baseline or approval can hide it."
)


def test_finding_identity_ignores_line_and_stays_out_of_the_payload() -> None:
    """Keep the context digest stable when only the line number changes."""
    path = "tests/test_quality_evidence_regressions.py"
    context = "same semantic context"
    first = common.finding("RULE", path, 1, "message", context)
    second = common.finding("RULE", path, 2, "message", context)
    expected = hashlib.sha256(f"RULE\0{path}\0{context}".encode()).hexdigest()
    assert first["id"] == second["id"] == expected
    assert context not in json.dumps(first)
    snapshot = dict(first)
    numbered = common.unique([first, second])
    assert first == snapshot
    assert [item["id"] for item in numbered] == [expected + ".1", expected + ".2"]


def test_escaping_finding_path_is_rejected() -> None:
    """Reject a finding path that leaves the repository."""
    with pytest.raises(ValueError, match="Unsafe finding path"):
        common.finding("RULE", "../private", 1, "message", "context")


def test_report_stdout_notes_and_failure_record_stay_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Preserve the public report line, notes, and secret-free command diagnostic."""
    item = common.finding(
        "RULE",
        "tests/test_quality_evidence_regressions.py",
        1,
        "message",
        "visible context",
    )
    output = tmp_path / "out.json"
    assert common.report("fixture", [item], 3, output) is True
    captured = capsys.readouterr()
    assert captured.out == (
        "fixture: 3 targets, 1 blocking findings, 0 reviewed non-secrets, "
        "0 historical entries ignored\n"
    )
    payload = json.loads(output.read_text())
    assert payload["notes"] == [_REPORT_NOTES]
    assert payload["failureKind"] == "quality"
    assert output.read_text().endswith("\n")
    failure_path = tmp_path / "failure.json"
    common.failure(failure_path, RuntimeError("DO NOT ECHO SECRET PAYLOAD"))
    text = failure_path.read_text()
    assert "SECRET PAYLOAD" not in text
    assert text == json.dumps(
        {
            "reportVersion": 0,
            "status": "failed",
            "failureKind": "command",
            "diagnostics": [
                {
                    "kind": "command",
                    "message": "RuntimeError",
                    "detail": _COMMAND_FAILURE_DETAIL,
                }
            ],
        }
    )


def test_command_failure_keeps_the_exit_summary() -> None:
    """Report the tool name and exit code without publishing tool output."""
    with pytest.raises(RuntimeError, match=r"false failed \(exit 1\); no fallback"):
        common.command(["/usr/bin/false"])


def test_reviewed_nonsecret_ids_round_trip_and_path_drift_blocks() -> None:
    """Match reviewed non-secrets only on the exact suffixed id, path, and rule."""
    index = common.reviewed_secret_index()
    raw = json.loads((ROOT / "ci/quality/secret-false-positives.json").read_text())
    assert len(raw["findings"]) == len(index) == _REVIEWED_NONSECRET_COUNT
    counts: dict[str, int] = {}
    synthetic = []
    expected_ids: list[str] = []
    for stored_id, item in index.items():
        base, dot, suffix = stored_id.rpartition(".")
        assert dot == "."
        counts[base] = counts.get(base, 0) + 1
        assert suffix == str(counts[base])
        synthetic.append(
            {
                "id": base,
                "ruleId": item["rule"],
                "severity": "error",
                "message": "reviewed",
                "location": {"path": item["path"], "startLine": 1, "endLine": 1},
            }
        )
        expected_ids.append(stored_id)
    blocking, reviewed = common.classify("secrets", synthetic)
    assert blocking == []
    assert [item["id"] for item in reviewed] == expected_ids
    first_id = expected_ids[0]
    base = first_id.rpartition(".")[0]
    drifted = {
        "id": base,
        "ruleId": index[first_id]["rule"],
        "severity": "error",
        "message": "reviewed",
        "location": {"path": "not-the-reviewed-path", "startLine": 1, "endLine": 1},
    }
    drifted_blocking, drifted_reviewed = common.classify("secrets", [drifted])
    assert drifted_reviewed == []
    assert [item["id"] for item in drifted_blocking] == [base + ".1"]
    plain_blocking, plain_reviewed = common.classify("python", [drifted])
    assert plain_reviewed == []
    assert len(plain_blocking) == 1


def test_duplicate_reviewed_identity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a repeated reviewed identity instead of collapsing the match."""
    source = json.loads((ROOT / "ci/quality/secret-false-positives.json").read_text())
    source["findings"] = [source["findings"][0], dict(source["findings"][0])]
    root = tmp_path / "repo"
    target = root / "ci/quality/secret-false-positives.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(source))
    monkeypatch.setattr(common, "ROOT", root)
    with pytest.raises(ValueError, match="Duplicate secret false-positive identity"):
        common.reviewed_secret_index()


def test_baseline_regeneration_stays_forbidden(tmp_path: Path) -> None:
    """Refuse the removed debt-recording switch before any report is written."""
    output = tmp_path / "out.json"
    with pytest.raises(ValueError, match="Baseline regeneration is forbidden"):
        common.report("fixture", [], 1, output, record_reason="A reviewed reason")
    assert not output.exists()


def test_frozen_provenance_is_the_exact_reviewed_file_set() -> None:
    """Check all 17 digests without exempting locally patched modules from lint."""
    policy = json.loads((ROOT / "ci/quality/strict-policy.json").read_text())
    record = policy["frozenCompatibility"]
    manifest = json.loads((ROOT / record["manifest"]).read_text())
    expected = {record["directory"] + "/" + name for name in manifest["backend_sha256"]}
    frozen = common.frozen_source_files()
    patched = [
        "charts/spi-triage/files/telegram_delivery.py",
        "charts/spi-triage/files/telegram_links.py",
    ]
    assert common.owned(patched) == patched
    assert frozen == expected - set(patched)
    assert len(expected) == _FROZEN_FILE_COUNT
    assert record["count"] == _FROZEN_FILE_COUNT
    assert record["canonicalRepository"] == "https://github.com/alchemmist/spi-triage"
    assert record["directory"] == "charts/spi-triage/files"
    neighbour = "charts/spi-triage/files/new_owned.py"
    assert common.owned([*sorted(frozen), neighbour]) == [neighbour]


def test_vendor_prefixes_follow_the_reviewed_contract() -> None:
    """Keep slash-terminated vendor roots equal to the provenance contract."""
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    assert [item.rstrip("/") for item in common.vendor_prefixes()] == [
        tree["path"] for tree in vendors["trees"]
    ]


@pytest.mark.parametrize(
    ("first_state", "last_state", "head_relation", "expected"),
    [
        ("clean", "clean", "same", "stable"),
        ("dirty", "clean", "same", "unstable"),
        ("clean", "dirty", "same", "unstable"),
        ("clean", "clean", "changed", "unstable"),
    ],
)
def test_snapshot_requires_the_same_clean_source(
    first_state: str, last_state: str, head_relation: str, expected: str
) -> None:
    """Admit evidence only when both boundaries name one clean commit."""
    head = "a" * _GIT_SHA1_LENGTH
    last_head = head if head_relation == "same" else "b" * _GIT_SHA1_LENGTH
    stable = strict_report.snapshot_is_stable(
        (head, first_state == "clean"), (last_head, last_state == "clean")
    )
    assert stable is (expected == "stable")


def test_private_evidence_permissions_and_separate_runs(tmp_path: Path) -> None:
    """Create mode 0700 runs and mode 0600 files without replacing an earlier run."""
    previous = os.umask(0)
    try:
        base = tmp_path / "private"
        first = strict_report.create_evidence_directory(base, "a" * _GIT_SHA1_LENGTH)
        strict_report.write_private(first / "summary.json", "previous run")
        second = strict_report.create_evidence_directory(base, "ab" * (_GIT_SHA256_LENGTH // 2))
        assert first != second
        assert (first / "summary.json").read_text() == "previous run"
        assert not (second / "summary.json").exists()
        assert stat.S_IMODE((first / "summary.json").stat().st_mode) == _PRIVATE_FILE_MODE
        for directory in (base, base / "runs", first, second):
            assert stat.S_IMODE(directory.stat().st_mode) == _PRIVATE_DIRECTORY_MODE
        assert list(first.glob(".strict-evidence-*")) == []
    finally:
        os.umask(previous)


def test_interrupted_evidence_write_keeps_previous_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave the previous file in place when publication is interrupted."""
    target = tmp_path / "summary.json"
    target.write_text("previous")

    def interrupt(_descriptor: int) -> None:
        message = "interrupted"
        raise OSError(message)

    monkeypatch.setattr(os, "fsync", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        strict_report.write_private(target, "replacement")
    assert target.read_text() == "previous"
    assert list(tmp_path.glob(".strict-evidence-*")) == []


@pytest.mark.parametrize("kind", ["file", "parent"])
def test_symlink_evidence_is_refused_before_write(tmp_path: Path, kind: str) -> None:
    """Refuse a symlinked evidence file or parent before writing the target."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "evidence.json"
    victim.write_text("untouched")
    if kind == "file":
        destination = tmp_path / "evidence.json"
        destination.symlink_to(victim)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        destination = alias / "evidence.json"
    with pytest.raises(ValueError, match="symlink"):
        strict_report.write_private(destination, "must not be written")
    assert victim.read_text() == "untouched"
    assert list(outside.iterdir()) == [victim]


@pytest.mark.parametrize("head", ["", "../escape", "g" * _GIT_SHA1_LENGTH])
def test_invalid_commit_creates_no_evidence_directory(tmp_path: Path, head: str) -> None:
    """Reject an unvalidated commit before creating a private directory."""
    base = tmp_path / "private"
    with pytest.raises(ValueError, match="Invalid source commit"):
        strict_report.create_evidence_directory(base, head)
    assert not base.exists()


@pytest.mark.parametrize("link_at", ["base", "runs"])
def test_symlinked_evidence_directory_is_not_mutated(tmp_path: Path, link_at: str) -> None:
    """Do not chmod or populate a symlinked private evidence directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("untouched")
    before = outside.stat().st_mode
    base = tmp_path / "private"
    if link_at == "base":
        base.symlink_to(outside, target_is_directory=True)
    else:
        base.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
        (base / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        strict_report.create_evidence_directory(base, "a" * _GIT_SHA1_LENGTH)
    assert outside.stat().st_mode == before
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_text() == "untouched"


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_partition_provider_runtime_violation_cannot_pass(
    value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Annotations must not remove runtime rejection of a broken provider."""
    monkeypatch.setattr(strict_report, "partition", lambda _path: value)
    with pytest.raises(TypeError, match="Finding partition must be a non-empty string"):
        strict_report.summarize(
            "fixture",
            {
                "findings": [
                    common.finding(
                        "RULE",
                        "tests/test_quality_evidence_regressions.py",
                        1,
                        "runtime classification boundary",
                        "synthetic boundary",
                    )
                ]
            },
        )
