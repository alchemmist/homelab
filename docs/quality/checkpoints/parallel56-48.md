# Parallel 56 lane 48 checkpoint

YAML semantic lane. Parent allocation source head `72419ef6`. Worktree base at
repair time was `3274cb0628152046185f8f4f5488391bfd52d3ed`, which contains
`03bb16146e5d23ddb083aa170bdce1cc18c779d6`. Lane files: 55. Initial yamllint
findings: 610. No other lane files were edited.

## Repair

Removed redundant quotes around three Chart.yaml `appVersion` scalars that
already parse as strings:

- `charts/open-terminal/Chart.yaml`: `'0.14.1'` to plain `0.14.1`
- `charts/pyroscope/Chart.yaml`: `"2.4.2"` to plain `2.4.2`
- `charts/traefik-edge/Chart.yaml`: `"3.7.13"` to plain `3.7.13`

No other token, comment, marker, version, or description changed.
`tests/test_quality_p56_48_chart_appversion.py` locks those three file texts.
Parent registers the new test. No `__init__` file was added.

## Graph proof

`yaml.compose` with the default loader and `SafeLoader`, before versus after,
matched on tags, scalar values, mapping order, and alias sharing (0 alias
nodes). The only difference on each file was one scalar style (`'` or `"` to
plain). `yaml.safe_load` still returns those appVersions as `str`.

Local `helm template` for `open-terminal`, `pyroscope`, and `traefik-edge`
exited 0 before and after. Rendered stdout SHA-256 values matched
(`678c634067f7`, `0bbb6ed2d0fb`, `025afd2126fc`) and byte length was unchanged
(18878, 8874, 29763). No chart dependency fetch and no cluster connection.

## Commands

Worker cwd. Parent pinned tools on `PATH`. `subprocess.run(check=False)`.

| Check | Before | After |
| --- | --- | --- |
| `yamllint` lane 55 files, `quality/yamllint.yaml` | exit 1, 610 findings | exit 1, 607 findings |
| quoted-strings | 250 | 247 |
| line-length | 273 | 273 |
| indentation | 65 | 65 |
| document-end | 13 | 13 |
| document-start | 4 | 4 |
| braces | 4 | 4 |
| comments | 1 | 1 |
| `yamllint` on the three Chart.yaml files | exit 1, 1 each | exit 0, 0 |
| `ruff check` on the new test | n/a (file absent) | exit 0 |
| `ruff format --check` on the new test | n/a | exit 0 |
| `mypy` on the new test | n/a | exit 0 |
| pytest, plugin autoload off, no cache | n/a | exit 0, 1 passed |

Ruff and mypy were also invoked on the YAML lane paths as a category check.
Ruff exit 1 (YAML is not Python; baseline stdout reported `Found 7113 errors`).
Mypy exit 2 (`Duplicate module named "__main__"` when several YAML paths are
passed together). Those statuses are unchanged by quote style and were not
treated as defects to repair by rewriting YAML.

## Remaining blockers

607 yamllint findings remain on this lane. 247 are `quoted-strings` (43
redundant quotes, 204 single quotes that still need double quotes). 273 are
`line-length`. Indentation, document markers, braces, and one comment remain.
File modes, Jinja, PKI, and alert-expression scalars were not rewritten in this
commit. No production, Ansible, SSH, or credential command was run.
