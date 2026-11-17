# Parallel 56 lane 46 checkpoint

One source repair: the two file modes in
`ansible/roles/debian_laptop/tasks/wifi_dns.yml` are double-quoted octal
strings. They stay the string `0644`. Unquoting them would make YAML 1.1
read an integer and would trip `octal-values`. No DNS servers, routes,
commands, paths, or task order changed.

`charts/private-gateway/values.yaml` is in the reviewed secret inventory and
was not edited. No yamllint disable, file ignore, or policy change was added.

## Commands

Working directory is this lane worktree. `PATH` starts with the parent
`.venv/bin` and `.quality-tools/bin`. Findings were collected with
`subprocess.run(check=False)`.

```text
yamllint --format parsable --config-file quality/yamllint.yaml <55 lane files>
```

Before: exit 1, 611 findings. After: exit 1, 609 findings.

| Rule | Before | After |
| --- | ---: | ---: |
| line-length | 276 | 276 |
| quoted-strings | 235 | 233 |
| indentation | 46 | 46 |
| braces | 40 | 40 |
| document-end | 10 | 10 |
| document-start | 3 | 3 |
| truthy | 1 | 1 |

`ansible/roles/debian_laptop/tasks/wifi_dns.yml` went from 2 `quoted-strings`
findings to 0. No other lane file count changed.

Ruff and mypy on `tests/test_quality_p56_46_wifi_dns_modes.py`: both exit 0.
Pytest on that file: exit 0, 1 passed. The lane allocation lists no scheduled
offline tests. Existing tests do not read this task file.

Pointing ruff or mypy at the YAML task file makes them parse it as Python
(ruff exit 1, 122 syntax diagnostics; mypy exit 2, 65 syntax diagnostics).
Those are not YAML findings and were not treated as a repair target.

## Graph proof

`yaml.compose_all` with the default `Loader` and with `SafeLoader` matched
before and after: one document, the same tags, scalar values, mapping and
sequence order, and zero shared alias nodes. The scanner shows exactly two
style changes, both the value `0644` from single quotes to double quotes.
The file bytes differ only by those two quote characters. `yaml.unsafe_load`
was not called.
