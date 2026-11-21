"""Exercise the production hash helper without n8n, SQLite or live credentials."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "charts/n8n/files/backup.cjs"
RUNNER = r"""
const fs = require('fs');
const { sha256File } = require(process.argv[1]);
// Import must not load n8n's production sqlite dependency or run a backup.
fs.readFileSync = () => { throw new Error('whole-file read forbidden'); };
const stream = fs.createReadStream;
fs.createReadStream = (file, options) => {
  if (options.highWaterMark !== 65536) throw new Error('unbounded stream');
  return stream(file, options);
};
sha256File(process.argv[2]).then(digest => {
  console.log(JSON.stringify({digest, maxRssKiB: process.resourceUsage().maxRSS}));
}).catch(error => { console.error(error.code || error.message); process.exitCode = 1; });
"""


def run_hash(path) -> subprocess.CompletedProcess[str]:
    """Run the offline streaming hash helper against a snapshot file."""
    return subprocess.run(
        ["node", "--max-old-space-size=32", "-e", RUNNER, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        timeout=40,
    )


def _text(value: str | None) -> str:
    """Return the assert-verified non-null captured output stream."""
    assert isinstance(value, str)
    return value


@pytest.mark.parametrize("content", [b"", b"abc", bytes(range(256)) * 1024])
def test_stream_digest_matches_sha256(tmp_path, content) -> None:
    file = tmp_path / "snapshot"
    file.write_bytes(content)
    result = run_hash(file)
    assert result.returncode == 0, result.stderr
    assert json.loads(_text(result.stdout))["digest"] == hashlib.sha256(content).hexdigest()


def test_snapshot_larger_than_container_limit(tmp_path) -> None:
    file = tmp_path / "snapshot"
    # Sparse synthetic fixture, not a production DB or archive.
    with file.open("wb") as out:
        out.write(b"synthetic snapshot")
        out.seek(528 * 1024 * 1024 - 1)
        out.write(b"x")
    expected = hashlib.sha256()
    with file.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            expected.update(chunk)
    result = run_hash(file)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["digest"] == expected.hexdigest()
    assert actual["maxRssKiB"] < 160 * 1024


def test_missing_snapshot_is_failure_not_success_digest(tmp_path) -> None:
    result = run_hash(tmp_path / "missing")
    assert result.returncode != 0
    assert "ENOENT" in _text(result.stderr)
    assert not result.stdout


def test_backup_calls_stream_helper_and_preserves_safety_contract() -> None:
    source = SCRIPT.read_text()
    assert "databaseSha256: await sha256File(path.join(data, 'database.sqlite'))" in source
    assert "readFileSync" not in source
    assert "db.backup(path.join(data, 'database.sqlite'))" in source
    assert "PRAGMA integrity_check" in source
    assert "sqlite.OPEN_READONLY" in source
    assert "StrictHostKeyChecking=yes" in source
    assert "receive-n8n-backup" in source
    assert "fs.copyFileSync('/recovery/encryption-key'" in source
    assert "if (require.main === module) main().catch(fail);" in source
