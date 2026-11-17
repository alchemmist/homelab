# Parallel 56 lane 46 checkpoint

Quoted octal Ansible file modes in this lane are double-quoted strings.
Unquoting `0600`, `0640`, `0644`, `0700`, or `0755` would make YAML 1.1 read
an integer and would trip `octal-values`. Paths, commands, task order, DNS,
VPN addresses, AllowedIPs, and permission digits are unchanged. Non-octal
modes such as `preserve` were left as they were.

`charts/private-gateway/values.yaml` is in the reviewed secret inventory and
was not edited. No yamllint disable, file ignore, or policy change was added.

## Commands

Working directory is this lane worktree. `PATH` starts with the parent
`.venv/bin` and `.quality-tools/bin`. Findings were collected with
`subprocess.run(check=False)`.

```text
yamllint --format parsable --config-file quality/yamllint.yaml <55 lane files>
```

Before any edit: exit 1, 611 findings. After the laptop DNS file: exit 1,
609 findings. After the remaining octal modes: exit 1, 526 findings. After
removing 37 redundant quotes: exit 1, 489 findings.

| Rule | Before | After DNS file | After octal modes | After redundant quotes |
| --- | ---: | ---: | ---: | ---: |
| line-length | 276 | 276 | 276 | 276 |
| quoted-strings | 235 | 233 | 150 | 113 |
| indentation | 46 | 46 | 46 | 46 |
| braces | 40 | 40 | 40 | 40 |
| document-end | 10 | 10 | 10 | 10 |
| document-start | 3 | 3 | 3 | 3 |
| truthy | 1 | 1 | 1 | 1 |

85 single-quoted octal mode scalars moved to double quotes. Two files in that
batch now have zero yamllint findings:
`ansible/playbooks/vpn-transit-exit-fence.yml` and
`ansible/roles/public_authoritative_dns/tasks/main.yml`. A later batch removed
37 quotes that yamllint marked redundant, only where the plain scalar kept the
same tag and value. Every other rule count is unchanged.

Ruff and mypy on `tests/test_quality_p56_46_wifi_dns_modes.py`: both exit 0.
The lane allocation lists no scheduled offline tests. Eight inspected offline
tests that read edited files passed (exit 0): the two mode regressions, the
Moscow DNS role knob test, worker endpoint equality, Rancher placement,
Rancher management source, bootstrap mesh render, and issuer-IP drift
restoration.

Pointing ruff or mypy at a YAML task file makes them parse it as Python
(ruff exit 1, 122 syntax diagnostics; mypy exit 2, 65 syntax diagnostics on
`wifi_dns.yml`). Those are not YAML findings and were not treated as a repair
target.

## Graph proof

For every edited file, `yaml.compose_all` with the default `Loader` and with
`SafeLoader` matched before and after: same document count, tags, scalar
values, mapping and sequence order, and shared alias nodes. Octal-mode edits
changed only single quotes to double quotes. Redundant-quote edits removed
only the quote characters; decoded values, including inventory key strings and
the Rancher features scalar, are unchanged. `yaml.safe_load_all` mode
sequences, including `preserve`, match the previous revision.
`yaml.unsafe_load` was not called. `charts/private-gateway/values.yaml` was
not edited.
