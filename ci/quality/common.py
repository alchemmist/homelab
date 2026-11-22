"""Data-only reports, tracked ownership inventory and strict success decisions."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
FROZEN_COMPATIBILITY_COUNT = 17
SHA256_HEX_LENGTH = 64
MAX_FROZEN_MANIFEST_BYTES = 1_048_576
_COMMAND_FAILURE_DETAIL = (
    "Quality tool/setup/protocol failed. " + "No debt baseline or approval can hide it."
)


class FindingLocation(TypedDict):
    """Byte-free source location stored in a native quality report."""

    path: str
    startLine: int
    endLine: int


class Finding(TypedDict):
    """One blocking or reviewed quality finding with a context-derived identity."""

    id: str
    ruleId: str
    severity: str
    message: str
    location: FindingLocation


class ReviewedSecret(TypedDict):
    """Exact reviewed non-secret identity. The reason is not part of the match."""

    id: str
    path: str
    rule: str
    reason: NotRequired[str]


def use_project_tools() -> None:
    """Prefer this worktree's pinned virtualenv and checksum-locked tool binaries."""
    prefix = os.pathsep.join((str(ROOT / ".venv/bin"), str(ROOT / ".quality-tools/bin")))
    current = os.environ.get("PATH", "")
    if current.split(os.pathsep)[:2] != prefix.split(os.pathsep):
        os.environ["PATH"] = prefix + (os.pathsep + current if current else "")


def command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    stdin: str | None = None,
    allowed: Collection[int] = (0,),
    timeout: float | None = 120,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded source tool with explicit cwd; never expose failure output."""
    process = subprocess.run(
        argv,
        input=stdin,
        text=True,
        capture_output=True,
        cwd=ROOT if cwd is None else cwd,
        timeout=timeout,
        check=False,
    )
    if process.returncode not in allowed:
        # Never publish arbitrary tool stdout/stderr: it can contain Secret values.
        message = f"{Path(argv[0]).name} failed (exit {process.returncode}); no fallback"
        raise RuntimeError(message)
    return process


def tracked() -> list[str]:
    """Return sorted regular files tracked by git, rejecting paths outside the repository."""
    names = command(["git", "ls-files", "-z"]).stdout.split("\0")
    result: list[str] = []
    for name in names:
        if not name:
            continue
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT):
            message = "Tracked path escapes the repository"
            raise ValueError(message)
        if path.is_file() and not path.is_symlink():
            result.append(name)
    return sorted(set(result))


def vendor_prefixes() -> tuple[str, ...]:
    """Return slash-terminated vendor roots from the reviewed provenance contract."""
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    prefixes: list[str] = []
    for tree in vendors["trees"]:
        path = str(tree["path"]).strip("/")
        if not path or path == "." or ".." in Path(path).parts:
            message = "Unsafe vendor path"
            raise ValueError(message)
        prefixes.append(path + "/")
    return tuple(prefixes)


def frozen_source_files() -> frozenset[str]:
    """Verify exact preexisting third-party compatibility inputs before exclusion.

    No unlisted path or whole directory becomes exempt. Any manifest, path or
    frozen-byte drift is an error rather than an opportunity to hide new code.
    """
    policy = json.loads((ROOT / "ci/quality/strict-policy.json").read_text())
    record = policy.get("frozenCompatibility")
    if not isinstance(record, dict) or set(record) != {
        "manifest",
        "sha256",
        "canonicalRepository",
        "directory",
        "count",
    }:
        message = "Frozen compatibility ownership contract missing or malformed"
        raise ValueError(message)
    if (
        record["manifest"] != "charts/spi-triage/LEGACY-SOURCE-MANIFEST.json"
        or record["directory"] != "charts/spi-triage/files"
        or record["canonicalRepository"] != "https://github.com/alchemmist/spi-triage"
        or record["count"] != FROZEN_COMPATIBILITY_COUNT
        or not isinstance(record["sha256"], str)
        or len(record["sha256"]) != SHA256_HEX_LENGTH
    ):
        message = "Frozen compatibility ownership scope drift"
        raise ValueError(message)
    manifest_path = ROOT / record["manifest"]
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or not manifest_path.resolve().is_relative_to(ROOT.resolve())
        or manifest_path.stat().st_size > MAX_FROZEN_MANIFEST_BYTES
    ):
        message = "Unsafe frozen compatibility manifest path"
        raise ValueError(message)
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        message = "Frozen compatibility manifest drift; reviewed source update required"
        raise ValueError(message)
    manifest = json.loads(raw)
    if manifest.get("canonical_repository") != record["canonicalRepository"]:
        message = "Frozen compatibility canonical repository drift"
        raise ValueError(message)
    files = manifest.get("backend_sha256")
    if not isinstance(files, dict) or len(files) != record["count"]:
        message = "Frozen compatibility input count drift"
        raise ValueError(message)
    verified: set[str] = set()
    for name, expected in files.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".py")
            or name in {".py", "..py"}
            or not isinstance(expected, str)
            or len(expected) != SHA256_HEX_LENGTH
        ):
            message = "Unsafe frozen compatibility input"
            raise ValueError(message)
        relative = record["directory"] + "/" + name
        path = ROOT / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(ROOT.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            message = "Frozen compatibility bytes drift: " + relative
            raise ValueError(message)
        verified.add(relative)
    # Verify the whole compatibility snapshot, but lint our locally patched modules.
    return frozenset(verified) - {
        "charts/spi-triage/files/telegram_delivery.py",
        "charts/spi-triage/files/telegram_links.py",
    }


def owned(names: Iterable[str]) -> list[str]:
    """Select owned inputs only after immutable third-party provenance is checked."""
    prefixes = vendor_prefixes()
    frozen = frozen_source_files()
    return [
        path
        for path in names
        if path not in frozen and not any(path.startswith(prefix) for prefix in prefixes)
    ]


def digest(value: str) -> str:
    """Return the SHA-256 hex digest of a Unicode string."""
    return hashlib.sha256(value.encode()).hexdigest()


def finding(
    rule: str,
    path: str | Path,
    line: int,
    message: str,
    context: str | None = None,
) -> Finding:
    """Build one stable finding identity from the rule, path, and source context."""
    relative = Path(path)
    if relative.is_absolute():
        relative = relative.relative_to(ROOT)
    if ".." in relative.parts:
        error = "Unsafe finding path"
        raise ValueError(error)
    name = relative.as_posix()
    if context is None:
        lines = (ROOT / relative).read_text().splitlines()
        context = lines[line - 1].strip() if line <= len(lines) else ""
    location: FindingLocation = {
        "path": name,
        "startLine": max(1, line),
        "endLine": max(1, line),
    }
    return {
        "id": digest(f"{rule}\0{name}\0{context}"),
        "ruleId": rule,
        "severity": "error",
        "message": message[:1000],
        "location": location,
    }


def unique(findings: Iterable[Finding]) -> list[Finding]:
    """Keep repeated finding identities distinct without using the line number."""
    # Repeated identical contexts remain separate findings, without line-number identity.
    counts: Counter[str] = Counter()
    result: list[Finding] = []
    for item in findings:
        base = item["id"]
        counts[base] += 1
        copied = item.copy()
        copied["id"] = f"{base}.{counts[base]}"
        result.append(copied)
    return result


def historical_debt_count(check: str) -> int:
    """Count historical entries that stay visible and cannot decide success."""
    path = ROOT / "ci/quality/debt" / f"{check}.json"
    if not path.is_file():
        return 0
    data = json.loads(path.read_text())
    if data.get("acceptance") is not False:
        message = "Historical debt file is not marked non-accepting"
        raise ValueError(message)
    findings = data.get("findings", [])
    return len(findings)


def _reviewed_secret(item: object) -> ReviewedSecret:
    """Copy the id, path, and rule used for an exact non-secret match."""
    if not isinstance(item, dict):
        message = "Reviewed non-secret entry must be an object"
        raise TypeError(message)
    identity = item["id"]
    entry_path = item["path"]
    rule = item["rule"]
    if (
        not isinstance(identity, str)
        or not isinstance(entry_path, str)
        or not isinstance(rule, str)
    ):
        message = "Reviewed non-secret identity must be strings"
        raise TypeError(message)
    entry: ReviewedSecret = {"id": identity, "path": entry_path, "rule": rule}
    reason = item.get("reason")
    if isinstance(reason, str):
        entry["reason"] = reason
    return entry


def reviewed_secret_index() -> dict[str, ReviewedSecret]:
    """Index exact reviewed non-secret identities by id, path, and rule."""
    path = ROOT / "ci/quality/secret-false-positives.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    index: dict[str, ReviewedSecret] = {}
    for item in data["findings"]:
        entry = _reviewed_secret(item)
        if entry["id"] in index:
            message = "Duplicate secret false-positive identity"
            raise ValueError(message)
        index[entry["id"]] = entry
    return index


def classify(check: str, findings: Iterable[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split secret findings into blocking and exact reviewed non-secret matches."""
    numbered = unique(findings)
    if check != "secrets":
        return numbered, []
    index = reviewed_secret_index()
    blocking: list[Finding] = []
    reviewed: list[Finding] = []
    for item in numbered:
        prior = index.get(item["id"])
        if prior and prior["path"] == item["location"]["path"] and prior["rule"] == item["ruleId"]:
            reviewed.append(item)
        else:
            blocking.append(item)
    return blocking, reviewed


def report(
    check: str,
    findings: Iterable[Finding],
    files: int,
    output: Path,
    *,
    record_reason: str | None = None,
) -> bool:
    """Write the native report. Historical debt cannot decide success or be regenerated."""
    if record_reason is not None:
        message = "Baseline regeneration is forbidden. Historical debt cannot decide success."
        raise ValueError(message)
    blocking, reviewed = classify(check, findings)
    historical = historical_debt_count(check)
    payload: dict[str, object] = {
        "reportVersion": 0,
        "status": "failed" if blocking else "passed",
        "metrics": [
            {"label": "Files / targets checked", "value": str(files)},
            {"label": "Blocking findings", "value": str(len(blocking))},
            {"label": "Reviewed non-secret matches", "value": str(len(reviewed))},
            {
                "label": "Historical debt entries ignored for success",
                "value": str(historical),
            },
        ],
        "findings": blocking,
        "notes": [
            "Full-tree check. Historical ci/quality/debt files do not decide success "
            "and cannot be regenerated. Reviewed secret false positives are exact "
            "id/path/rule matches only."
        ],
    }
    if blocking:
        payload["failureKind"] = "quality"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    sys.stdout.write(
        f"{check}: {files} targets, {len(blocking)} blocking findings, "
        f"{len(reviewed)} reviewed non-secrets, {historical} historical entries ignored\n"
    )
    return bool(blocking)


def failure(output: Path, error: BaseException) -> None:
    """Record a command failure without echoing the exception value."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "reportVersion": 0,
                "status": "failed",
                "failureKind": "command",
                "diagnostics": [
                    {
                        "kind": "command",
                        "message": type(error).__name__,
                        "detail": _COMMAND_FAILURE_DETAIL,
                    }
                ],
            }
        )
    )
