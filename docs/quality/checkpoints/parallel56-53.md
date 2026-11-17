# Parallel 56 lane 53

Two name-only source repairs are committed in this worktree. Previously unnamed
tasks in `ansible/playbooks/vpn-native-image-refresh.yml` and
`ansible/playbooks/otel-socrat4-cpu-tuning.yml` now have unique names. Command
lines, phase defaults, image pin, protected digests, modes, service names,
async polls, and refusal conditions are unchanged. PyYAML compose graphs match
except the added `name` keys. Scalar tags and styles match, and neither
document shares an alias node.

The VPN repair is `66d5cf458fef2bb3fa3d67b6db3e6c6d0a1489d2`. The OTEL repair is
the commit that contains this checkpoint update.

## Checks

Pinned tools from the parent continuation `.venv` (ansible-lint 26.11.0,
yamllint 1.38.0, ruff 0.15.12, mypy 2.4.1). Worker cwd and local configs.

| Check | Before | After VPN names | After OTEL names |
| --- | --- | --- | --- |
| `ansible-lint --offline --nocolor --format brief` on the four lane playbooks | exit 2, 77 (60 `name[missing]`, 8 `no-changed-when`, 7 `jinja[spacing]`, 1 `command-instead-of-module`, 1 `no-relative-paths`) | exit 2, 63 (46 `name[missing]`, other counts unchanged) | exit 2, 48 (31 `name[missing]`, other counts unchanged) |
| `yamllint --format parsable --config-file quality/yamllint.yaml` on the same four files | exit 1, 108 | exit 1, 108 | exit 1, 108 (25/21/39/23 by file, unchanged) |
| `ruff check` and `ruff format --check` on the new lane tests | | exit 0 | exit 0 |
| `mypy --config-file quality/mypy.ini` on the new lane tests | | exit 0 | exit 0 |
| offline pytest | | VPN name test plus `test_refresh_is_stage_first_and_promotion_is_explicit`: exit 0, 2 passed | OTEL name test plus `tests/test_otel_socrat4_cpu_tuning.py`: exit 0, 5 passed |

## Still blocking

- Thirty-one `name[missing]` findings remain on `ansible/playbooks/moscow-watchdog-repair.yml` and `ansible/playbooks/tv-public-dashboard.yml`.
- Eight `no-changed-when` hits are successful mutating `command` tasks. An explicit `changed_when: true` matches the success-path default and can differ only on the failed-task changed bit.
- Seven `jinja[spacing]` warnings include TV dict literals locked by `tests/test_grafana_tv_public.py`, which this lane does not own.
- `command-instead-of-module` is `systemctl show homelab-otel-agent.service -p DropInPaths --value`, whose empty stdout is the assertion. The systemd module does not provide that stdout.
- `no-relative-paths` is the OTEL copy `src` containing `../files`. The resolved file is `ansible/files/otel/socrat4-cpu.conf`.
- Yamllint `quoted-strings` and `line-length` remain at 108. Requoting would change substrings other tests require, including `default("stage")` and `default("preflight")`.
- `tests/test_vpn_native_refresh.py` has two failing source assertions against `scripts/vpn-native-image-promote.py` and `ansible/roles/vpn_failover/files/smoke_test.py`. Those files are outside this lane and were not edited.
