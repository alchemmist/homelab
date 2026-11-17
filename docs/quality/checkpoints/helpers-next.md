# Helper typing checkpoint

Partial strict typing of the quality report helpers. This is not a clean-tree
claim, not a full audit, and not production acceptance. No quality config,
baseline, suppression, budget, or dependency pin was changed. `types-pyyaml`
remains `6.0.12.20261113`. Nothing was pushed or merged.

## Source

- `scripts/quality/common.py` and `scripts/quality/strict_report.py` now have
  explicit annotations, docstrings, and typed JSON narrowing. Public parameter
  names, report text, finding ids, reviewed non-secret matching, and the frozen
  compatibility values (17 files, 64-character SHA-256, the existing manifest
  path and canonical repository) are unchanged.
- Evidence publication is still atomic, mode `0600`, under mode `0700`
  directories. Symlinks, invalid commits, dirty or changed snapshots, and an
  interrupted `fsync` still refuse or keep the previous bytes.
- `tests/test_quality_evidence_regressions.py` locks those contracts. It is not
  listed in `quality/test-suites.json` because that catalog is outside this
  ownership boundary. The tests were run directly. They are not part of the
  curated suite until a parent adds them.

## Commands and actual results

Tools were the locked worktree versions: mypy `2.4.1`, ruff `0.15.12`,
CPython `3.13.16`. Host ruff `0.16` was not used.

- `MYPYPATH=scripts/quality mypy --config-file quality/mypy.ini --no-error-summary --no-pretty --no-color-output --hide-error-context --show-error-codes --follow-imports=silent --no-incremental scripts/quality/common.py scripts/quality/strict_report.py`
  - exit `1`
  - `common.py`: 0 errors
  - `strict_report.py`: 5 errors, all `[no-untyped-call]`
    - line 198 `partition`
    - line 277 `lint.check`
    - line 286 `charts.check`
    - line 365 `verify_configuration`
    - line 382 `suppression_hits`
- `ruff check --config quality/ruff.toml scripts/quality/common.py scripts/quality/strict_report.py`
  - exit `1`, 3 errors
  - `INP001` on both files
  - `S603` on `common.command` (`subprocess.run` of a non-literal argv)
- `ruff format --check --config quality/ruff.toml` on both helpers and the new test: exit `0`
- `ruff check --config quality/ruff.toml tests/test_quality_evidence_regressions.py`
  - exit `1`, 1 error: `INP001`
- `.venv/bin/python -m pytest -q tests/test_quality_evidence_regressions.py tests/test_quality_system.py`
  - exit `0`, 90 passed in 18.34s
  - 22 collected from the new module, 68 from `tests/test_quality_system.py`

## Remaining blockers

- `INP001` asks for `scripts/quality/__init__.py` and `tests/__init__.py`.
  These modules are imported as top-level names (`import common`, `import lint`).
  Adding a package init would change that import identity. The finding is not
  ignored.
- `S603` remains on the shared `command` wrapper because its argv is a
  parameter. A literal argument list is not flagged. Removing the wrapper or
  adding a suppression would change the safety boundary or hide the finding.
- The five `no-untyped-call` errors are calls into `scripts/quality/lint.py`,
  `charts.py`, and `strict_guard.py`. Those files are outside this ownership
  boundary. The results are validated after the call. The calls were not cast
  to `Any` and were not silenced with `type: ignore`.
- No current-head full strict report, curated-suite registration, hosted
  aggregate, or Kind acceptance is claimed.
