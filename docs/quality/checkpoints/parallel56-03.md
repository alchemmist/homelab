# Parallel 56 lane 03 checkpoint

Commit repairs `tests/test_vpn_native_refresh.py` only. Parent HEAD at start
was `03bb16146e5d23ddb083aa170bdce1cc18c779d6`. Allocation source head
`72419ef6` lists this lane's seven test modules and 578 initial findings.

## Repair

Public tests gained return annotations and docstrings. The import block is
sorted. The restart/stop absence check is two asserts with the same predicates.
The receipt-parent open count still compares equal to 2, now via
`RECEIPT_PARENT_DIRECTORY_OPENS`. Containment literals are unchanged.

AST proof against `HEAD` before the edit: the three function names match; all
20 assertion string literals match; expanding the original `and` assert into its
two comparisons and folding the new constant back to `2` yields 20 identical
predicates. The constant literal-evaluates to `2`.

## Commands

Worker cwd, parent pinned `ruff`/`mypy`/`python`, local `quality/ruff.toml` and
`quality/mypy.ini`. `subprocess.run(check=False)`.

| Check | Before | After |
| --- | --- | --- |
| `ruff check` on the seven lane files | exit 1, 449 findings | exit 1, 439 findings |
| `mypy` on the seven lane files | exit 1, 129 errors | exit 1, 126 errors |
| `ruff format --check tests/test_vpn_native_refresh.py` | not a baseline gate | exit 0 |
| Inspected pytest, plugin autoload off, no cache | exit 1, 2 failed, 4 passed | exit 1, 2 failed, 4 passed |

This file's ruff findings went from 10 to 0 (`ANN201` 3, `D103` 3, `D100` 1,
`I001` 1, `PT018` 1, `PLR2004` 1). Its mypy `no-untyped-def` errors went from 3
to 0. No other lane file's counts changed.

Pytest modules: `tests/test_vpn_native_refresh.py` (read-only source reads and
`yaml.safe_load`; unscheduled, side effects inspected) and scheduled offline
`tests/test_socrat5_app_placement.py`. The same two predicates fail before and
after: promotion still requires `fcntl.LOCK_EX|fcntl.LOCK_NB`, and smoke still
requires `source.as_uri() + '?mode=ro'`. Placement's three tests passed both times.

## Remaining blockers

Those two failures pre-exist. Formatted sources still contain the same
operations with spaces and double quotes (`fcntl.LOCK_EX | fcntl.LOCK_NB`,
`proof["cleanup_verified"]`, `core == running_core()`, two spaced
`os.open(RECEIPT.parent, os.O_DIRECTORY)` calls, `"state": "intent"`,
`source.as_uri() + "?mode=ro"`, and a double-quoted isolated receipt path).
Rewriting the literals would change assertion bytes and pass/fail, so they were
left in place.

Lane remainder: 439 ruff findings and 126 mypy errors across the other six
files. `tests/spi_triage/` `INP001` stays; this lane must not add `__init__`
files. Those modules also have `import-not-found` for `test_triage`, `core`,
`integrations`, and `local_token_counter`. `tests/test_vpn_failover.py` still
has `name-defined` on `MODULE.Watchdog` and six `method-assign` errors.
`PT009` (175) remains; converting unittest asserts is a separate equivalence
pass, not this commit.
