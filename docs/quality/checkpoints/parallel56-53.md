# Parallel 56 lane 53

One source repair is committed in this worktree: every previously unnamed task in
`ansible/playbooks/vpn-native-image-refresh.yml` now has a unique task name.
Command lines, phase defaults, image pin, modes, async polls, and refusal
conditions are unchanged. PyYAML compose graphs match except those added `name`
keys. Scalar tags and styles match, and neither document shares an alias node.

## Checks

Pinned tools from the parent continuation `.venv` (ansible-lint 26.11.0,
yamllint 1.38.0, ruff 0.15.12, mypy 2.4.1). Worker cwd and local configs.

| Check | Before | After |
| --- | --- | --- |
| `ansible-lint --offline --nocolor --format brief` on the four lane playbooks | exit 2, 77 violations (60 `name[missing]`, 8 `no-changed-when`, 7 `jinja[spacing]`, 1 `command-instead-of-module`, 1 `no-relative-paths`) | exit 2, 63 violations (46 `name[missing]`, other counts unchanged) |
| `yamllint --format parsable --config-file quality/yamllint.yaml` on the same four files | exit 1, 108 findings | exit 1, 108 findings |
| `ruff check` and `ruff format --check` on `tests/test_quality_p56_53_vpn_task_names.py` | new file | exit 0 |
| `mypy --config-file quality/mypy.ini` on that test | new file | exit 0 |
| `pytest -q` that test plus `test_refresh_is_stage_first_and_promotion_is_explicit` | | exit 0, 2 passed |

## Still blocking

- Eight `no-changed-when` hits are successful mutating `command` tasks. An explicit `changed_when: true` matches the success-path default and can differ only on the failed-task changed bit. Not folded into this name-only edit.
- Seven `jinja[spacing]` warnings include TV dict literals locked by `tests/test_grafana_tv_public.py`, which this lane does not own.
- `command-instead-of-module` is `systemctl show homelab-otel-agent.service -p DropInPaths --value`, whose empty stdout is the assertion. The systemd module does not provide that stdout.
- `no-relative-paths` is the OTEL copy `src` containing `../files`. The resolved file is `ansible/files/otel/socrat4-cpu.conf`.
- Yamllint `quoted-strings` and `line-length` remain at 108. Requoting would change substrings other lanes' tests require, including `default("stage")` and `default("preflight")`.
- `tests/test_vpn_native_refresh.py` has two failing source assertions against `scripts/vpn-native-image-promote.py` and `ansible/roles/vpn_failover/files/smoke_test.py`. Those files are outside this lane and were not edited.
