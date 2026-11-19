# Lane 16 checkpoint

Parent base `03bb16146e5d23ddb083aa170bdce1cc18c779d6`. First committed repair is `tests/test_otel_socrat4_cpu_tuning.py`.

## Pinned checks

Commands used the worker cwd with `quality/ruff.toml` and `quality/mypy.ini`. Parent tools were prepended on `PATH`. Exit codes are the raw tool statuses.

| Check | Before | After this repair |
| --- | --- | --- |
| `ruff check` on the eight lane files | exit 1, 413 findings | exit 1, 400 findings |
| `mypy` on the eight lane files | exit 1, 168 errors | exit 1, 164 errors |
| `ruff check` on the repaired file | 13 findings | exit 0, 0 findings |
| `ruff format --check` on the repaired file | not separately baselined | exit 0 |
| `mypy` on the repaired file | 4 `no-untyped-def` | exit 0, 0 errors |
| `pytest -q` on the repaired file | not run before the edit | exit 0, 4 passed |

The file is unscheduled. Inspection shows only local reads of committed playbooks and the override fragment, so the pytest run is an offline check.

## Preservation

Executable AST matches the original after expanding the single `and` assertion into two asserts and substituting `PROTECTED_FILE_COUNT = 3` and `HEALTHY_AGENT_STATUS = 200`. Function names, parameters, and decorators are unchanged. Both constants remain literal assignments.

## Still open on this lane

400 Ruff findings and 164 mypy errors remain on the other seven allocated tests. Security diagnostics (`S106`, `S603`, `S607`, `S314`) stay visible and were not rewritten.
