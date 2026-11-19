# Historical strict audit receipts

> Historical evidence follows. Old counts, exit semantics, disabled-rule descriptions and branch/main references are NOT current configuration. For current integration scope and enforcement read [README](README.md), [CI enablement](ci-enablement.md), and [strict policy](strict-policy.md). Use the exact-head private audit and published PR evidence for current results.

# Strict audit status

This is the tracked receipt for the strict configuration on `quality/strict-all`. It is not a clean-tree claim and not production acceptance. The full per-finding report is private, mode `0700`/`0600`, at `~/Library/Application Support/homelab/quality-strict/`. No raw secret values are in that report.

`configurationReady` is true: the strict policy is enforced, debt does not decide success, and the checks below actually ran. `sourceClean` is false. `scripts/quality/strict_report.py` returns 0 when the tools finish, including when findings remain. That exit code is not a clean tree.

## Integration

Base `9cf5e13885b86375d0306933ed6e4cee018d96b6` was clean. Three reviewed ranges were cherry-picked. They do not share files. These were not integrated:

- `pi-subagents/manifests-services-2ec348c-442f-s0-t0` at `ccbe2964b60339015fa8c42a41b6b2f4b16de927`. The first commit replaces explicit nulls in vendored Grafana values and does not restore them. The second commit does not restore those values either.
- `pi-subagents/ansible-7148291-4628-s0-t0` is still `9cf5e138` with a dirty worktree, including backup, secret, identity, SSH, and VPN helpers. Nothing there was committed.
- `pi-subagents/tests-b2ddff5-09d1-s0-t0` is still `9cf5e138` with no reviewed test commit.
- Fifteen uncommitted scripts in `pi-subagents/scripts-4154a7e-9683-s0-t0` stay in that worktree. Tests outside `scripts/` pin their exact text. They are not in these commits.

`origin/main` (`ded215cbd41cf120d537814ec6c3fa6bb922f84e`) was merged. Its only delta was the Venice API digest and wiki note. No file overlapped the integrated ranges.

## Commands

Recorded on the full-report commit `e6bcac5b95e80e632bf983e7ee50cfbe33d80f74`, then a secrets-only rescan after the reviewed-line restore:

- `pytest tests/test_quality_system.py tests/test_ansible_quality_policy.py`: exit 0, 40 passed.
- `python scripts/quality/strict_guard.py`: configuration checks passed. Exit 1 is 11 inline suppressions, not a tool crash.
- `ruff check --config quality/ruff.toml scripts/quality/boundaries.py`: exit 1, `INP001` once.
- `zizmor --offline --persona auditor .github/workflows`: exit 0, and the SARIF still has 3 findings. Exit 0 is not a clean audit.
- `yamllint` and `actionlint` on the two hand-written workflows, and `shellcheck --enable=all` on `android/build.sh`: exit 0 after the document-end markers.
- `python scripts/quality/strict_report.py`: exit 0, `configurationReady=true`, `sourceClean=false`. No command blocker. Private `summary.json` records head `e6bcac5b95e80e632bf983e7ee50cfbe33d80f74`.
- `python scripts/quality/tests.py cluster`: exit 1. Kind could not create `homelab-qg-1ed5690f29b8` because this rootless Podman provider requires systemd `Delegate=yes`. No host or VM setting was changed. `kind get clusters` was empty afterwards. The private kubeconfig never left the test tmp directory. This is not a passed Kind lifecycle.
- After restoring the two reviewed public-key lines and renaming the digest pin: `python scripts/quality/lint.py secrets` printed 0 blocking and 51 reviewed non-secrets, exit 0.
- Hosted fast suite on Quality Graph run `43985778073` failed two exact-byte checks. `scripts/otel-application-credentials.py`, `scripts/otel-sdk-source-privacy.py`, and `scripts/otel-open-webui-source-profile.py` were restored to their pre-format bytes because a ConfigMap mirror and a content-addressed source name pin them. Local `python scripts/quality/tests.py fast` then exited 0: 595 passed, 1 skipped, 329 subtests passed.
- Hosted Kind run `43985778237`: `tests.py cluster` on `ubuntu-24.04` exited 0, 4 passed in 49.78s. The log line did not report skips. That is the private UUID lifecycle for this branch. It is not production acceptance.

Tool path was this worktree's `.venv/bin` and checksum-locked `.quality-tools/bin`. No production SSH, operator kubeconfig, live cluster mutation, backup, identity, VPN, GPU, workflow, or Wiki operation was used.

## Counts

The full report below is head `e6bcac5b`. It includes 3 `generic-api-key` hits that the follow-up restore removed from the blocking set. Other tools were not rerun after that restore. Total blocking findings in that report: 102045. Historical debt entries were ignored for success.

| Check | Targets | Blocking | Status | Partitions |
| --- | ---: | ---: | --- | --- |
| python | 651 | 95118 | failed | scripts 16616, tests 54088, ansible 13746, manifests 9453, services 536, quality-policy 679 |
| yaml | 604 | 5319 | failed | tests 2066, manifests 2007, ansible 1207, quality-policy 36, workflows 3 |
| shell | 23 | 184 | failed | ansible 149, scripts 11, services 17, manifests 7 |
| workflow | 5 | 3 | failed | workflows 3 |
| ansible | 358 | 384 | failed | ansible 384 |
| manifests | 58 | 1023 | failed | manifests 997, vendor 26 |
| suppressions | 11 | 11 | failed | quality-policy 4, tests 4, scripts 3 |
| secrets | 2767 | 3 | failed | quality-policy 1, scripts 2; 49 reviewed non-secrets still matched |
| docker | 5 | 0 | passed | none |
| javascript | 32 | 0 | passed | none |
| dependencies | 70 | 0 | passed | none |

The secrets rescan after the restore is the current secrets result: 2767 targets, 0 blocking, 51 reviewed. It replaces the secrets row above. It does not by itself make `sourceClean` true.

Largest Python rules in the full report: `Q000` 43024, `no-untyped-call` 7966, `PT009` 5243, `no-untyped-def` 4714, `ANN201` 4112, `ANN001` 3969, `E501` 3385. `python-syntax` 1 and `ruff-syntax` 1 were recorded, and mypy still reported `invalid-syntax` 8. The python tool finished; those syntax findings did not abort the rest of the owned set. Largest YAML rules: `yaml-line-length` 2759, `yaml-indentation` 1377, `yaml-document-end` 644, `yaml-document-start` 289. The three workflow YAML hits are `document-end` on the three generated Quality Graph workflows. Largest shell rules: `SC2250` 130, `SC2312` 25, `SC2292` 15. Ansible: `name[missing]` 196, `no-changed-when` 71, `command-instead-of-module` 26. Manifests: `kube-linter-use-namespace` 139, `kube-linter-non-isolated-pod` 95, `schema-unavailable` 92. The private `summary.json` has every rule from the full report.

Compared with the previous 117026 receipt, integrated script formatting and the hand-written workflow fixes account for the lower Python, shell, and workflow totals. New document-end, comment, and sorted-keys rules raised the YAML total. This is not a sign-off of any partition.

## Suppressions still present

These are blocking. They are not an allowlist. The new suppression test writes its marker into a temporary file. The tracked test does not contain a contiguous marker, so it is not a twelfth hit.

- `scripts/nightnode/nightnode:27`
- `scripts/ns3-public-dns.py:30`
- `scripts/spi-public-dns.py:30`
- `scripts/quality/install_collections.py:29`
- `scripts/quality/install_collections.py:53`
- `scripts/quality/install_tools.py:29`
- `scripts/quality/tests.py:72`
- `tests/kubernetes/test_cluster.py:21`
- `tests/test_ansible_quality_policy.py:38`
- `tests/test_quality_system.py:165`
- `tests/test_quality_system.py:171`

## Blockers

Generated `.github/workflows/quality-graph-publish.yml` stays untrusted. `quality-graph-github==0.2.0` `_publication_workflow` hardcodes `workflow_run` (`requested`, `completed`) and `issue_comment` (`created`, `edited`), plus uncommented job permissions, including `actions: write`. `qg.yaml` cannot narrow that. Hand-editing the generated file is overwritten by `qg generate`. `generatedWorkflows.trusted` and `waiver` are both false. zizmor reports `dangerous-triggers` once and `undocumented-permissions` twice. The same three generated workflows also fail yamllint `document-end`. Those findings are not waived.

Yamllint `key-ordering`, `empty-values`, and `quoted-strings` stay off. They collide with ansible-lint `key-order`, least-privilege `permissions: {}`, and scalar types. Ansible `var-naming`, `role-name`, and `name[prefix]` stay off because they rename external task and variable interfaces. kube-linter replica, `Recreate`, NodePort/LoadBalancer, DNS `ndots`, affinity, and Job `restartPolicy` omissions stay documented conflicts. `sorted-keys` is enabled.

`INP001` wants `scripts/quality/__init__.py`. Those modules are imported as top-level names through `sys.path` (`import boundaries`). Adding a package init would change that import identity. The finding is not ignored.

`SC2250` on `scripts/testing-class-wg-guard.sh` stays unbraced because the reviewed test requires the exact text `-A "$CHAIN" -j DROP`. `SC2310` and `SC2312` on `scripts/nightnode/nightnode` and `scripts/rustfs/deploy.sh` stay because splitting the substitutions would change `set -e` behavior. The two shell `*) ;;` arms are no-ops; an exiting default would reject valid backup ids and extra Deployments.

Local Kind did not run: rootless Podman refused `homelab-qg-1ed5690f29b8` without systemd `Delegate=yes`, and no cluster was left behind. The generated `tests-cluster` job needs the manifest, Ansible, and medium-test jobs, which fail closed on remaining findings, so Quality Graph run `43985778073` skipped it. `.github/workflows/strict-kind-lifecycle.yml` is the hand-written reproduction that produced run `43985778237`. It runs on a pull request only when that workflow file changes, because GitHub will not dispatch a workflow that is absent from the default branch. It is not a trusted-base registration and it does not edit the generated workflows. Missing stack checks, not counted as passes: ESLint, Prettier execution, a separate Bandit run, and Vulture. `quality/rules.json` is not the enforcement catalog. `qg.yaml` was not changed and was not registered through trusted-base. Draft PR 182 tracks this branch. PR 181 is a separate draft and was not updated.

## Parent continuation: semantic source contracts

The failed Grok fan-out was not integrated. Parent directly repaired the concrete
formatting regressions on top of284c0c2d, without removing checks or changing
production state. The Authentik retirement prerequisite now parses the reviewed
bootstrap recipe rather than matching quote/space-sensitive text. It requires
journal/token refusal, both administrative credential removals and use of the
filtered map before manifest construction. This is a bounded source prerequisite,
not proof of live identity state. Seven genuine AST mutations and decoy/comment,
formatting, invalid-syntax and size-limit cases cover the verifier without running
identity operations.

Relay scope mutation now modifies the actual AST, proves a change happened, then
checks rejection and no writes. Source assertions for LiteLLM, RustFS, queue auth,
gateway ownership, Kuma recovery and scoped DNS use parsed representations rather
than a particular quote style; security properties and scenarios remain intact.
Byte-pinned inputs and their existing hashes are unchanged.

Validation of this code change (before its documentation commit):
- Targeted seven modules:75passed.
- Curated fast:607passed,1existing fixture skip,329subtests passed.
- Curated medium on macOS:274passed,5existing Linux-only skips,313subtests passed.
- strict_guard:0inline suppressions; configuration validation passed.
- No new full strict lint count or current-head hosted/Kind acceptance claimed.

Private evidence: parent-semantic-fast.txt and parent-semantic-medium.txt in the
existing private quality-strict evidence directory. The stale102045/117026totals
are historical, not a current count. The overall strict refactor remains red and
unfinished; this successful regression checkpoint is not global lint acceptance.
