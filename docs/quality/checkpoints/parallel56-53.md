# Parallel 56 lane 53

Every previously unnamed task in the four allocated playbooks now has a unique
name. Command lines, phase defaults, image pins, protected digests, modes,
service names, URL literals, async polls, and refusal conditions are unchanged.
PyYAML compose graphs match except the added `name` keys. Scalar tags and styles
match, and none of the four documents shares an alias node.

Commits:

- `66d5cf458fef2bb3fa3d67b6db3e6c6d0a1489d2` VPN refresh names
- `f4b2fb1853cd15c222303bc514eb4766d299d8b1` Moscow CPU override names
- the commit containing this checkpoint: Moscow repair and TV URL names

## Checks

Pinned parent tools: ansible-lint 26.11.0, yamllint 1.38.0, ruff 0.15.12,
mypy 2.4.1. Worker cwd and local `quality/ruff.toml` / `quality/mypy.ini` /
`quality/ansible-lint.yaml` / `quality/yamllint.yaml`.

| Check | Before | After all names |
| --- | --- | --- |
| `ansible-lint --offline --nocolor --format brief` on the four playbooks | exit 2, 77 (60 `name[missing]`, 8 `no-changed-when`, 7 `jinja[spacing]`, 1 `command-instead-of-module`, 1 `no-relative-paths`) | exit 2, 17 (0 `name[missing]`, other counts unchanged) |
| `yamllint --format parsable --config-file quality/yamllint.yaml` on the same files | exit 1, 108 (25/21/39/23) | exit 1, 108 (25/21/39/23; 77 `quoted-strings`, 23 `line-length`, 8 `indentation`) |
| `ruff check` and `ruff format --check` on the three new tests | new files | exit 0 |
| `mypy --config-file quality/mypy.ini` on the three new tests | new files | exit 0 |
| inspected offline pytest | | exit 0: VPN name test plus stage-phase contract (2); OTEL name test plus `tests/test_otel_socrat4_cpu_tuning.py` (5); Moscow/TV name tests plus the two Moscow playbook contracts and `test_live_update_is_url_only_and_does_not_reprovision_tv` (5) |

## Still blocking

- Eight `no-changed-when` hits are successful mutating `command` tasks. `changed_when: true` matches the success-path default and can differ on the failed-task changed bit, so it was not mixed into the name repairs.
- Seven `jinja[spacing]` warnings include TV dict literals locked by `tests/test_grafana_tv_public.py` (`{'startURL':tv_start_url}` and the unspaced plan dicts). That test is not in this lane.
- `command-instead-of-module` is `systemctl show homelab-otel-agent.service -p DropInPaths --value`. The task asserts that exact stdout is empty. The systemd module does not return that stdout.
- `no-relative-paths` is the OTEL copy `src` containing `../files`. It resolves to `ansible/files/otel/socrat4-cpu.conf`.
- Yamllint `quoted-strings`, `line-length`, and `indentation` remain at 108. Requoting would change substrings the contracts require, including `default("preflight")`, `default("stage")`, and `(voters.stdout | from_json)["items"]`.
- `tests/test_vpn_native_refresh.py` has two pre-existing failures against `scripts/vpn-native-image-promote.py` and `ansible/roles/vpn_failover/files/smoke_test.py`. Those paths are outside this lane and were not edited. The playbook contract in that module passed.
