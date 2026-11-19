# Pytest idiom checkpoint — eight contract modules

This is not a clean test tree and not production acceptance. Eight owned
modules now use pytest asserts and `pytest.raises`. No quality config,
baseline, suppression, skip, xfail, or dependency pin was changed. Nothing
was pushed or merged. Production sources were not edited.

## Ownership

Edited:

- `tests/test_alert_graph_panel_ids.py`
- `tests/test_gateway_readonly.py`
- `tests/test_target_placement_ownership.py`
- `tests/test_source_pointers.py`
- `tests/test_operational_entrypoints.py`
- `tests/test_vendor_contracts.py`
- `tests/test_deployment_ownership.py`
- `tests/test_spi_execution_links.py`
- `docs/quality/checkpoints/pytest-next.md`

Not edited: `tests/test_quality_system.py`, quality helpers, evidence
writers, and shell scripts. `tests/__init__.py` was not added.

## What changed

The eight classes still subclass `unittest.TestCase`. None of them override
`setUp`, `tearDown`, `failureException`, or an assertion method, so the
unittest calls were the stock ones. `subTest` stays, and so do the class and
test method names, `unittest.main` where it already existed, and the public
helpers (`rule`, `owner`, `fixture`, `write`, `save`,
`_assert_retired_grafana_source`).

`assertEqual` / `assertTrue` / `assertFalse` / `assertIn` / `assertNotIn` /
`assertIsNone` / `assertIsNotNone` / `assertGreater` are regular asserts.
Both sides are still evaluated before the comparison. `assertFalse` became
`assert not ...` (truthiness, not `is False`). `assertIsNone` became
`is None`.

`assertRaises` and `assertRaisesRegex` became `pytest.raises`. Existing
regexes are unchanged (`Missing local values`, `Missing`, `Undefined`,
`escapes`, `Unclassified`, `Missing operational source owner`,
`symlink escapes`, `added=.*unreviewed-hook`, `Symlink`, `Duplicate`,
`alias`). The deployment drift pattern is now an explicit raw f-string,
`rf"{mode}=.*deployment\.yaml"`, which still matches the vendor drift text.
Bare `ValueError` checks, which PT011 rejects without `match`, now use
`re.escape` of the message the checker actually raises for that scenario.
`RuntimeError` and `SystemExit` are outside PT011's default match list, so
those tests still constrain the failure by call counts, empty request logs,
and the CLI leak checks rather than a new message regex.

The CLI test reads `str(error.value)`. Pytest's `ExceptionInfo` stores the
same `SystemExit` instance unittest exposed as `exception`. `self.fail` in
the gateway opener is unchanged: it raises `AssertionError`, and this Ruff
does not treat `fail` as PT009. `pytest.fail` would raise `Failed`, a
`BaseException`, which is a different class.

Loop-local gateway runners are still defined and called inside the same
`subTest` iteration. They were not rebound as default arguments.

## Commands and actual results

Locked tools, after `uv sync --frozen --only-dev`: uv 0.12.23, ruff 0.15.12,
pytest 9.0.3, CPython 3.13.16. Later commands used `uv run --frozen --no-sync`.
The host Ruff was not used.

```text
uv run --frozen --no-sync ruff check --config quality/ruff.toml \
  tests/test_alert_graph_panel_ids.py \
  tests/test_gateway_readonly.py \
  tests/test_target_placement_ownership.py \
  tests/test_source_pointers.py \
  tests/test_operational_entrypoints.py \
  tests/test_vendor_contracts.py \
  tests/test_deployment_ownership.py \
  tests/test_spi_execution_links.py
uv run --frozen --no-sync ruff format --check --config quality/ruff.toml <same eight>
uv run --frozen --no-sync python -m pytest -q <same eight>
```

Before any edit:

- Ruff exit 1, 340 findings. PT009 96, PT027 25, RUF059 21, ANN201 59,
  D102 56, ANN001 18, D101 10, INP001 8, I001 7, B023 7, D100 5, ANN202 5,
  ANN003 5, ARG001 4, D103 3, E501 2, PLC0415 2, and one each of ANN204,
  D107, S106, E731, RET503, S104, SIM117.
- Pytest exit 0: 58 passed, 60 subtests passed.

After the edit, same commands:

- Ruff exit 1, 182 findings. No PT009, PT027, PT011, or other `PT` rule.
  Cleared with the assertions: RUF059 21, I001 7, ARG001 4, E501 2,
  PLC0415 2, SIM117 1. No new rule code was introduced.
- `ruff format --check` exit 0.
- Pytest exit 0: 58 passed, 60 subtests passed. `--collect-only` reports
  58 tests. Subtests are not separate collection nodes.

## Remaining findings

| Count | Rule | Why it remains |
| ---: | --- | --- |
| 59 | ANN201 | Public tests and helpers are still unannotated. Adding annotations was not part of the assertion conversion. |
| 56 | D102 | Those same methods have no docstrings. |
| 18 | ANN001 | Arguments on those helpers and nested runners. |
| 10 | D101 | Test classes have no docstrings. |
| 8 | INP001 | `tests/__init__.py` would change the implicit-namespace import identity and is outside this ownership. |
| 7 | B023 | Gateway `failed` and `bad` close over the subtest loop. Each is called before the next iteration, and the tests assert that iteration's read count. |
| 5 | D100 | Five modules have no module docstring. |
| 5 | ANN202 | Private nested runners have no return annotation. |
| 5 | ANN003 | Those runners accept `**kwargs` so the production caller can pass timeout and env. |
| 3 | D103 | `rule`, `owner`, and `fixture` have no docstrings. |
| 1 | ANN204 | `Response.__init__`. |
| 1 | D107 | `Response.__init__`. |
| 1 | S106 | `secret="litellm-monitoring"` is the production argument the fixture must supply. The value is synthetic. |
| 1 | E731 | The gateway fixture encodes bytes with a one-line lambda. |
| 1 | RET503 | The opener ends in `self.fail`, which Ruff does not treat as `NoReturn`. |
| 1 | S104 | `"0.0.0.0"` is one address that must be rejected before credentials are sent. Removing it would weaken that case. |

These are open findings, not accepted debt. No noqa, type-ignore, skip, or
xfail was added.

## What this commit does not do

No full-tree Ruff or pytest run, curated-suite edit, Kind cluster, native
report, SSH, kubeconfig, VPN, backup, or credential inspection. The gateway
and placement tests patch their runners; they do not contact a cluster.
