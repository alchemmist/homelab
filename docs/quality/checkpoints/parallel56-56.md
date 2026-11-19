# Lane 56 checkpoint

Parent base 03bb16146e5d23ddb083aa170bdce1cc18c779d6. Allocation source
72419ef6. Worktree HEAD at start 3274cb0628152046185f8f4f5488391bfd52d3ed.
Exclusive file: scripts/quality/lint.py. Kind: dependency auditor.

## Repair

lockfileVersion 3 package-lock.json and npm-shrinkwrap.json are now audited
without npm, installation, lifecycle scripts, npmrc, netrc, proxies or
credential environment. The lock is validated locally first. Exact registry
distributions are then posted over direct TLS to api.osv.dev/v1/querybatch.
A short, malformed or failed response is a protocol failure, not a clean
audit. Duplicate advisory identities collapse only for the same name and
version. Other ecosystems, non-v3 npm documents and unpaired package.json
files stay blocking coverage findings.

Python requirement validation, pip-audit arguments and exit/report binding
are unchanged. Twenty-five pre-existing linter functions keep the same
executable AST under the pinned CPython 3.13 parser.

## Commands

Pinned tools from the parent .venv, cwd this worktree, local quality configs.
Ruff and mypy exit 1 are retained diagnostics.

- Baseline ruff check scripts/quality/lint.py: exit 1, 87 findings.
- Baseline mypy scripts/quality/lint.py: exit 1, 55 errors.
- Post-change ruff check scripts/quality/lint.py: exit 1, 87 findings.
  Codes unchanged: INP001 1, ANN201 20, D103 18, ANN001 27, PLC0415 4,
  PLR2004 1, TRY003 5, EM101 5, C901 1, PLR0911 1, PLR0912 1, PLR0915 1,
  BLE001 1, T201 1.
- Post-change mypy scripts/quality/lint.py: exit 1, 55 errors.
- ruff format --check on the edited Python files: exit 0.
- ruff check tests/test_quality_p56_56_node_lock.py: exit 0.
- pytest tests/test_quality_p56_56_node_lock.py: exit 0, 38 passed.
- pytest tests/test_quality_dependency_coverage.py: exit 0, 24 passed.

No live advisory request was made. The owned lock parses to 128 unique
distributions, including both direct pins, and the mocked batch submits all
of them. Private counts are outside Git.

## Remaining blockers

The rest of lint.py is still untyped and over the complexity limits above.
INP001 remains because this lane must not add __init__.py. poetry, Pipfile,
pnpm, yarn, bun, pylock, extra uv.lock, requirements.in and npm lockfileVersion
other than 3 stay blocking. The live OSV response is fail-closed if it does
not match the positional batch contract; this lane did not call the feed.
