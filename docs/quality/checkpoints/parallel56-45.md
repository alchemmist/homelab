# Parallel 56 lane 45 checkpoint

Lane kind `yaml-semantic`. Exclusive file:
`tests/service-availability.test.yml`. Allocation source head `72419ef6`
recorded 2131 initial findings. Parent HEAD at task start was
`03bb16146e5d23ddb083aa170bdce1cc18c779d6`. This worktree started at
`40b8b53ab0fedd0442d06e214e1ad4531dc21007`.

## Repair

Every single-quoted scalar in the unit file was one of two tokens:
`'{}'` (321) or `'0x20'` (37). Both must stay YAML strings: bare `{}` is a
flow mapping, and bare `0x20` is a YAML 1.1 integer, while promtool reads
those scalars as an empty label set and a repeated sample. They are now
`"{}"` and `"0x20"`. No other character changed. Line lengths are unchanged.
There are no YAML anchors. Alias-node count stayed 0.

`yaml.compose` with `SafeLoader` and with `Loader` produced the same
tag/value/flow-style graph before and after. The only style deltas are
`{}` and `0x20` moving from single quotes to double quotes.
`yaml.safe_load` values are equal. `yaml.unsafe_load` was not used.

## Commands

Worker cwd. Parent pinned tools on `PATH`. `subprocess.run(check=False)`
for yamllint. Config: `quality/yamllint.yaml`.

| Check | Before | After |
| --- | --- | --- |
| `yamllint --format parsable` on the unit file | exit 1, 2131 | exit 1, 1773 |
| quoted-strings | 358 | 0 |
| line-length | 1061 | 1061 |
| indentation | 710 | 710 |
| document-start | 1 | 1 |
| document-end | 1 | 1 |
| `ruff check` on the new regression | file absent | exit 0, 0 findings |
| `mypy` on the new regression | file absent | exit 0, 0 errors |
| pytest, cache plugin off | file absent | exit 0, 1 passed |

Pytest module: `tests/test_quality_p56_45_service_availability_quotes.py`.
It only reads this unit file and composes it. No promtool, cluster, or
network. The lane's scheduled offline test list is empty. No other test
module references this file.

## Second repair

The same unit file gained a leading `---` and a trailing `...`. Both
loaders still compose exactly one document. Tag, value, scalar style,
flow style, and alias sharing match the pre-marker bytes. `safe_load`
values are equal. The regression test was run again after this edit.

| Check | Before markers | After markers |
| --- | --- | --- |
| `yamllint --format parsable` on the unit file | exit 1, 1773 | exit 1, 1771 |
| document-start | 1 | 0 |
| document-end | 1 | 0 |
| line-length | 1061 | 1061 |
| indentation | 710 | 710 |
| quoted-strings | 0 | 0 |
| pytest on the regression, cache plugin off | exit 0, 1 passed | exit 0, 1 passed |

The Python regression was not edited. Re-running `ruff check` and `mypy`
on it after the marker edit stayed exit 0 with 0 findings and 0 errors.

## Remaining blockers

`line-length` (1061) and `indentation` (710) remain. The long lines are
PromQL expressions and series selectors. Indenting sequences adds columns
to lines that are already over 100 characters, so it increases
`line-length`. Reflowing those plain scalars changes the string unless
every break round-trips to the same scalar; that was not attempted.
Parent still has to register the new test module; this lane did not edit
`quality/test-suites.json`.
