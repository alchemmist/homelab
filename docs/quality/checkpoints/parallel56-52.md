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

## Repair: wiki-runtime storage document markers

`ansible/files/wiki-runtime-storage-socrat-0.yaml` had one missing document
start and two missing document ends. The edit adds `---` after the two header
comments, `...` before the existing document separator, and `...` at the end.
No volume name, claim name, host path, `Retain` policy, capacity, access mode,
storage class, or node selector was edited. `git diff` adds only those three
marker lines.

`yaml.compose_all` with `SafeLoader` and the default `Loader` matches the
pre-edit bytes, including scalar style, flow style, tags, values, order, both
documents, and alias-sharing count `0`.

Regression: `tests/test_quality_p56_52_wiki_storage_framing.py`.
Yamllint on this file alone exits 0.

The 57-file yamllint command now exits 1 with 602 findings: quoted-strings 232,
line-length 211, indentation 76, comments-indentation 41, braces 22,
document-end 9, comments 8, document-start 3.

```text
ruff check --config quality/ruff.toml tests/test_quality_p56_52_wiki_storage_framing.py
ruff format --check --config quality/ruff.toml tests/test_quality_p56_52_wiki_storage_framing.py
mypy --config-file quality/mypy.ini tests/test_quality_p56_52_wiki_storage_framing.py
python -m pytest -q tests/test_quality_p56_52_n8n_cpu_quote.py tests/test_quality_p56_52_chart_app_version.py tests/test_quality_p56_52_wiki_storage_framing.py
```

Exits 0, 0, 0, and 0. Ruff reports 0 findings. Pytest reports 3 passed.
The new tests remain unregistered until the parent adds them.

## Repair: Ansible scalar quotes

Two pure `quoted-strings` files were normalized. Composed tags, values, order,
and alias-sharing count `0` match the previous bytes under both `SafeLoader`
and the default `Loader`.

- `ansible/playbooks/identity-rbac.yml`: the kubectl `argv` filename flag
  changes from `'-'` to `"-"`. The argument stays the string `-`. The stdin
  lookup is unchanged.
- `ansible/roles/debian_laptop/tasks/time.yml`: the chrony regexp loses
  redundant single quotes. Its value still contains the same six backslash
  escapes. `mode` changes from `'0644'` to `"0644"`, so it stays a string.
  A bare `0644` resolves as an integer and was not used.

Regression: `tests/test_quality_p56_52_ansible_scalar_quotes.py`.
Yamllint on each of these two files alone exits 0.

The 57-file yamllint command now exits 1 with 599 findings: quoted-strings 229,
line-length 211, indentation 76, comments-indentation 41, braces 22,
document-end 9, comments 8, document-start 3.

```text
ruff check --config quality/ruff.toml tests/test_quality_p56_52_ansible_scalar_quotes.py
ruff format --check --config quality/ruff.toml tests/test_quality_p56_52_ansible_scalar_quotes.py
mypy --config-file quality/mypy.ini tests/test_quality_p56_52_ansible_scalar_quotes.py
python -m pytest -q tests/test_quality_p56_52_ansible_scalar_quotes.py tests/test_quality_p56_52_n8n_cpu_quote.py tests/test_quality_p56_52_chart_app_version.py tests/test_quality_p56_52_wiki_storage_framing.py
```

Exits 0, 0, 0, and 0. Ruff reports 0 findings. Pytest reports 5 passed.

Remaining lane findings are still blocking. The larger quoted-string files mix
Jinja, flow sequences, and long lines, so they were not rewritten in this pass.
No test was added to `quality/test-suites.json`.
