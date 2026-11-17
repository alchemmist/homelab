# Parallel 56 lane 27

One allocated test repair is committed on this branch. The other seven allocated files are unchanged.

## Repair

- File: `tests/test_otel_bootstrap_command_output.py`
- The three original test names remain. Comparisons stay `is None`, call count `== 1`, `RuntimeError` match `sensitive response omitted`, and parsed object `== {"kind": "Pod"}`.
- `subprocess.run` stays patched. The bootstrap module is still loaded with `importlib` and its `__main__` guard is not invoked.
- The loader now raises `RuntimeError` when `spec_from_file_location` returns no spec or loader. The existing file still loads, which the passing tests exercise.

## Commands and counts

Pinned tools from the parent `.venv`, worker cwd, `quality/ruff.toml` and `quality/mypy.ini`.

| Check | Before | After |
| --- | --- | --- |
| `ruff check` on this file | exit 1, 16 findings | exit 0, 0 findings |
| `ruff format --check` on this file | exit 0 | exit 0 |
| `mypy --follow-imports=silent` on this file | exit 1, 10 errors | exit 0, 0 errors |
| `pytest -q` on this file | not run before the edit | exit 0, 3 passed |
| `ruff check` on all 8 allocated files | exit 1, 414 findings | exit 1, 398 findings |

## Remaining blockers

398 Ruff findings remain on the other allocated tests. `tests/spi_triage/test_local_token_counter.py` still reports `INP001`; this lane must not add `__init__.py`. Those files were not edited.
