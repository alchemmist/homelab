"""Inventory experimental source without importing or running its provider machinery."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.quality import common

with patch.dict(sys.modules, {"common": common}):
    from scripts.quality import boundaries

    with patch.dict(sys.modules, {"boundaries": boundaries}):
        from scripts.quality import contracts, lint

ROOT = Path(__file__).resolve().parents[1]


def test_experimental_test_names_require_explicit_classification() -> None:
    """An experimental test must not disappear from the coverage inventory."""
    names = [
        "tests/test_existing.py",
        "experiments/venice-autonomy/test_controller_faults.py",
        "experiments/future/test_future.py",
        "experiments/future/runner.py",
        "docs/test_example.py",
        "tests/test_not_python.txt",
    ]
    assert contracts.owned_test_files(names) == set(names[:3])


def test_new_lab_tests_are_visible_but_not_execution_authorized() -> None:
    """All actual lab tests stay explicit deferred entries, never auto-collected in CI."""
    inventory = json.loads((ROOT / "quality/test-suites.json").read_text())
    experimental = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "experiments/venice-autonomy").glob("test_*.py")
    }
    assert experimental
    assert experimental <= set(inventory["notScheduled"])
    scheduled = {path for paths in inventory["suites"].values() for path in paths}
    assert not experimental & scheduled
    assert all(path.startswith("tests/") for path in scheduled)


def test_unhashed_alternate_requirements_block_without_source_transport(tmp_path: Path) -> None:
    """Worker dependency metadata cannot silently bypass lock admission."""
    name = "experiments/fixture/worker-requirements.txt"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("fixture-package==1.0\n")
    with (
        patch.object(lint, "ROOT", tmp_path),
        patch.object(lint, "_audit_python_source", return_value=([], 0)) as audit,
    ):
        findings, count = lint.check_dependencies([name])
    assert count == 0
    assert len(findings) == 1
    assert findings[0]["ruleId"] == "DEPENDENCY_LOCK_INVALID"
    assert findings[0]["location"]["path"] == name
    audit.assert_called_once_with(
        ["pip-audit", "--local", "--strict", "--format", "json"], "uv.lock"
    )


def test_hashed_alternate_requirements_retain_full_audit_flags(tmp_path: Path) -> None:
    """Valid alternate filenames use the same no-install hash-bound source audit."""
    name = "experiments/fixture/worker-requirements.txt"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("fixture-package==1.0\n    --hash=sha256:" + "a" * 64 + "\n")
    with (
        patch.object(lint, "ROOT", tmp_path),
        patch.object(lint, "_audit_python_source", side_effect=[([], 0), ([], 1)]) as audit,
    ):
        findings, count = lint.check_dependencies([name])
    assert findings == []
    assert count == 1
    expected_calls = 2
    assert audit.call_count == expected_calls
    assert audit.call_args.args == (
        [
            "pip-audit",
            "--strict",
            "--disable-pip",
            "--no-deps",
            "--require-hashes",
            "--requirement",
            name,
            "--format",
            "json",
        ],
        name,
    )


def test_alternate_requirement_symlink_is_refused(tmp_path: Path) -> None:
    """Filename coverage must not weaken regular-file and repository-path guards."""
    source = tmp_path / "source.txt"
    source.write_text("fixture-package==1.0\n")
    name = "worker-requirements.txt"
    (tmp_path / name).symlink_to(source)
    with (
        patch.object(lint, "ROOT", tmp_path),
        patch.object(lint, "_audit_python_source", return_value=([], 0)),
        pytest.raises(ValueError, match="tracked regular repository file"),
    ):
        lint.check_dependencies([name])


def test_canonical_invalid_lock_keeps_existing_failure_contract(tmp_path: Path) -> None:
    """Existing canonical lock validation still refuses invalid data, without fallback."""
    (tmp_path / "requirements.txt").write_text("fixture-package==1.0\n")
    with (
        patch.object(lint, "ROOT", tmp_path),
        patch.object(lint, "_audit_python_source", return_value=([], 0)),
        pytest.raises(ValueError, match="unsupported or unsafe source directives"),
    ):
        lint.check_dependencies(["requirements.txt"])


@pytest.mark.parametrize("missing_hash_first", [False, True])
def test_every_requirement_needs_its_own_hash(tmp_path: Path, *, missing_hash_first: bool) -> None:
    """One package hash must never authorize a different package before transport."""
    hashed = "hashed-fixture==1.0\n    --hash=sha256:" + "a" * 64 + "\n"
    unhashed = "unhashed-fixture==1.0\n"
    path = tmp_path / "worker-requirements.txt"
    path.write_text(unhashed + hashed if missing_hash_first else hashed + unhashed)
    with pytest.raises(ValueError, match="unsupported or unsafe source directives"):
        lint.validate_requirement_hashes(path)


def test_auditor_and_transport_fixtures_share_stdlib_module() -> None:
    """Do not remove a newly imported HTTP module with the temporary common alias."""
    assert sys.modules["http.client"] is http.client


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("services/fixture/Dockerfile", True),
        ("experiments/fixture/worker.Dockerfile", True),
        ("services/fixture/Dockerfile.worker", True),
        ("services/fixture/dockerfile", True),
        ("services/fixture/WORKER.DOCKERFILE", True),
        ("Dockerfile/not_a_build.py", False),
        ("docs/worker.Dockerfile.md", False),
    ],
)
def test_docker_filename_variants_are_admitted(name: str, *, expected: bool) -> None:
    """Filename variants are source inputs, never Docker build invocations."""
    assert lint.docker_targets([name]) == ([name] if expected else [])


def test_docker_adapter_transports_each_source_and_keeps_findings() -> None:
    """The owning adapter sends old and new paths to hadolint with no build effects."""
    sources = [
        "services/spi-tokenizer/Dockerfile",
        "experiments/venice-autonomy/worker.Dockerfile",
    ]
    names = [*sources, "docs/not_a_dockerfile.md"]
    payload = [{"code": "DL3013", "line": 1, "message": "synthetic source diagnostic"}]
    process = subprocess.CompletedProcess(["hadolint"], 1, stdout=json.dumps(payload), stderr="")
    with (
        patch.object(lint, "use_project_tools"),
        patch.object(lint, "tracked", return_value=names),
        patch.object(lint, "owned", return_value=names),
        patch.object(lint, "command", return_value=process) as command,
    ):
        findings, checked = lint.check("docker")
    assert checked == len(sources)
    assert [row["location"]["path"] for row in findings] == sources
    assert [row["ruleId"] for row in findings] == ["DL3013"] * len(sources)
    assert [item.args[0] for item in command.call_args_list] == [
        ["hadolint", "--config", "quality/hadolint.yaml", "--format", "json", source]
        for source in sources
    ]
    assert all(item.kwargs == {"allowed": (0, 1)} for item in command.call_args_list)
