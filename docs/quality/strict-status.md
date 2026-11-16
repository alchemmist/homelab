# Strict audit status

This is the tracked receipt for the strict configuration on `quality/strict-all`. It is not a clean-tree claim and not production acceptance. The full per-finding report is private, mode `0700`/`0600`, at `~/Library/Application Support/homelab/quality-strict/`. No raw secret values are in that report.

`configurationReady` is true: the strict policy is enforced, debt does not decide success, and the checks below actually ran. `sourceClean` is false. Five source partitions remain for later owners and independent review: `scripts`, `tests`, `ansible`, `manifests`/`services`, and `workflows`.

The audit ran on parent `adc8581ef6ba20c1a0a38a7335be18d56f526698` plus the uncommitted strict adapters in this commit. The private `summary.json` records that parent HEAD because the commit is created after the run.

## Commands

- `python scripts/quality/strict_guard.py` completed. Configuration checks passed. Exit 1 is the 11 inline suppressions, which are findings, not a tool crash.
- `pytest tests/test_quality_system.py tests/test_ansible_quality_policy.py`: 27 passed.
- `python scripts/quality/strict_report.py` ran yaml, shell, workflow, secrets, docker, javascript, ansible, dependencies, and manifests. The first Python pass stopped with `RuntimeError` because `ruff format --check` exits 2 when a file cannot be parsed. The adapter now records that as `ruff-syntax` plus the reformat list. Python was then rerun through the same reporter and merged into the private summary. No command blocker remains.

Tool path was this worktree's `.venv/bin` and checksum-locked `.quality-tools/bin`. No production SSH, kubeconfig, live cluster mutation, or credential helper was used.

## Counts

Total blocking findings: 117026. Historical debt entries were ignored for success.

| Check | Targets | Blocking | Status | Partitions |
| --- | ---: | ---: | --- | --- |
| python | 648 | 110582 | failed | scripts 42496, tests 46871, ansible 12327, manifests 8164, services 437, quality-policy 287 |
| yaml | 604 | 4684 | failed | tests 2060, manifests 1736, ansible 848, quality-policy 31, workflows 5, other-owned 4 |
| shell | 23 | 335 | failed | ansible 149, scripts 97, other-owned 65, services 17, manifests 7 |
| workflow | 5 | 7 | failed | workflows 7 |
| ansible | 358 | 384 | failed | ansible 384 |
| manifests | 58 | 1023 | failed | manifests 997, vendor 26 |
| suppressions | 11 | 11 | failed | quality-policy 4, tests 4, scripts 3 |
| secrets | 2760 | 0 | passed | 51 reviewed non-secrets, unchanged |
| docker | 5 | 0 | passed | none |
| javascript | 32 | 0 | passed | none |
| dependencies | 70 | 0 | passed | none |

Largest Python rules: `Q000` 69389, `E501` 5541, `PT009` 5243, `ANN201` 4080, `ANN001` 3934, `E702` 2766. Largest YAML rules: `yaml-line-length` 2760, `yaml-indentation` 1379, `yaml-document-start` 293. Largest shell rules: `SC2250` 271, `SC2312` 26, `SC2292` 22. Ansible: `name[missing]` 196, `no-changed-when` 71, `command-instead-of-module` 26. Manifests: `kube-linter-use-namespace` 139, `kube-linter-non-isolated-pod` 95, `schema-unavailable` 92. The private `summary.json` has every rule.

## Suppressions still present

These are blocking. They are not an allowlist.

- `scripts/nightnode/nightnode:27`
- `scripts/ns3-public-dns.py:30`
- `scripts/spi-public-dns.py:30`
- `scripts/quality/install_collections.py:29`
- `scripts/quality/install_collections.py:53`
- `scripts/quality/install_tools.py:29`
- `scripts/quality/tests.py:72`
- `tests/kubernetes/test_cluster.py:21`
- `tests/test_ansible_quality_policy.py:38`
- `tests/test_quality_system.py:162`
- `tests/test_quality_system.py:168`

## Blockers

No tool or configuration blocker remains. Kind, curated suites other than the two quality tests above, and the five source partitions were not cleaned or signed off. Missing stack checks, not counted as passes: ESLint, Prettier execution, a separate Bandit run, Vulture, and mutation tests. `quality/rules.json` is not the enforcement catalog. `qg.yaml` was not changed and was not registered through trusted-base.
