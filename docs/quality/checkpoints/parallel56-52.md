# Parallel 56 lane 52 checkpoint

Lane 52 is the yaml-semantic allocation. This checkpoint records the committed
source repairs. It is not a clean-tree claim. Remaining yamllint findings stay
visible. No yamllint disable, file ignore, debt approval, or policy change was
added. No Helm, Ansible, Kubernetes, SSH, or credential command was run.

## Repair

`deploy/n8n/values.yaml` is the retired Fleet bundle, not the Argo-owned
`charts/n8n` values. Its CPU limit was the single-quoted string `'1'`.
Yamllint `quoted-strings` (`quote-type: double`, `required: only-when-needed`)
requires double quotes when quotes are what keep the scalar a string. The
scalar is now `"1"`. A bare `1` is an integer and was not used.

The image pin, node name, host, webhook, persistence size and class, memory
requests and limits, and `ingress.enabled: true` were not edited.

## Proof

`yaml.compose_all` with `SafeLoader` and the default `Loader` produced the same
node tags, scalar values, mapping order, and alias-sharing count (`0`) for the
single-quoted and double-quoted forms. The bare integer form differs: the CPU
limit tag changes from `tag:yaml.org,2002:str` to `tag:yaml.org,2002:int`.
`yaml.unsafe_load` was not called.

Regression: `tests/test_quality_p56_52_n8n_cpu_quote.py`. Parent registers it.
No `__init__` file was added.

## Commands

Pinned parent tools were invoked with this worktree as the cwd and
`quality/yamllint.yaml`, `quality/ruff.toml`, and `quality/mypy.ini`.
`subprocess.run(check=False)` preserved real exit codes.

Baseline, before the edit:

```text
yamllint --format parsable --config-file quality/yamllint.yaml <57 lane files>
```

Exit 1. 610 findings: quoted-strings 237, line-length 211, indentation 76,
comments-indentation 41, braces 22, document-end 11, comments 8,
document-start 4.

The same command after the edit: exit 1. 609 findings. `quoted-strings` is 236.
Every other rule count is unchanged. `deploy/n8n/values.yaml` went from 1
finding to 0, and yamllint on that file alone exits 0.

```text
ruff check --config quality/ruff.toml tests/test_quality_p56_52_n8n_cpu_quote.py
ruff format --check --config quality/ruff.toml tests/test_quality_p56_52_n8n_cpu_quote.py
mypy --config-file quality/mypy.ini tests/test_quality_p56_52_n8n_cpu_quote.py
python -m pytest -q tests/test_quality_p56_52_n8n_cpu_quote.py
```

Exits 0, 0, 0, and 0. Ruff reports 0 findings. Pytest reports 1 passed.

## Repair: plain Helm appVersion strings

Four chart metadata files had a redundantly double-quoted `appVersion`.
The quotes were removed. The composed scalar stays `tag:yaml.org,2002:str`
with the same version text, and chart `name` / `version` are unchanged:

- `charts/netbird/Chart.yaml`: `0.82.0`
- `charts/pr-agent/Chart.yaml`: `0.49.0`
- `charts/syncthing/Chart.yaml`: `2.1.3`
- `charts/x-ui/Chart.yaml`: `3.10.2`

`yaml.compose_all` with `SafeLoader` and the default `Loader` matched the
quoted form on tags, values, mapping order, and alias-sharing count `0`.

Regression: `tests/test_quality_p56_52_chart_app_version.py`.

After this edit the same 57-file yamllint command exits 1 with 605 findings.
`quoted-strings` is 232. Every other rule count matches the baseline.
Each of the four chart files, and `deploy/n8n/values.yaml`, now has 0 findings.

```text
ruff check --config quality/ruff.toml tests/test_quality_p56_52_chart_app_version.py
ruff format --check --config quality/ruff.toml tests/test_quality_p56_52_chart_app_version.py
mypy --config-file quality/mypy.ini tests/test_quality_p56_52_chart_app_version.py
python -m pytest -q tests/test_quality_p56_52_chart_app_version.py tests/test_quality_p56_52_n8n_cpu_quote.py
```

Exits 0, 0, 0, and 0. Ruff reports 0 findings. Pytest reports 2 passed.

Neither new test is listed in `quality/test-suites.json`. Parent owns that
registration.
