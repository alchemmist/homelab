# Strict policy

This file is the enforcement contract for `quality/strict-all`. It does not claim the tree is clean. Historical `quality/debt/*.json` files stay visible and are marked `"acceptance": false`. They do not decide success, and `--record-debt` cannot regenerate them. `quality/rules.json` is an old catalog, not this contract.

The existing 15-node `qg.yaml` graph is unchanged. Its `python`, `yaml`, `shell`, `workflow`, `secrets`, `docker`, `javascript`, `ansible`, `manifests`, and `dependencies` nodes call the stricter adapters. No shard and no decorative node was added. Trusted-base registration is not bypassed.

Monori (`/Users/antonmoss/code/monori`) is the reference for strict Python, read-only. It selects Ruff `ALL` with `strict` mypy. Its test ignores (`D*`, `S105`, `S106`, `S107`, `F401`, `PLR2004`) and its `D212` choice are not copied. Homelab keeps one test exception, `S101`, because pytest rewrites `assert`.

## Python

- Ruff `0.15.12` selects `ALL`. The formatter check is mandatory.
- `D203` is ignored because it cannot pass together with `D211`. PEP 257 keeps `D211`.
- `D213` is ignored because it cannot pass together with `D212`. PEP 257 keeps `D212`.
- `ISC001` is ignored because the formatter can introduce the concatenations it forbids.
- `COM812` is ignored because the formatter owns trailing commas. The defect remains visible through `ruff format --check`.
- `ISC002` stays enabled. Its formatter conflict requires `allow-multiline = false`, which is not set.
- `**/tests/**` ignores only `S101`.
- mypy `2.4.1` uses `strict` plus `warn_unreachable`, `explicit_package_bases`, `disallow_any_explicit`, `disallow_any_unimported`, `disallow_any_decorated`, `strict_equality_for_none`, and the extra error codes in `quality/mypy.ini`.
- The config file does not set `follow_imports`, `ignore_missing_imports`, or `disable_error_code`. The adapter passes every owned Python file and `--follow-imports=silent` so imported modules that are themselves in that set still report. Missing third-party stubs stay `import-untyped` findings. Stubs are not installed to hide them.
- There is no Ruff `exclude`. Vendor trees are omitted by `deploy/contracts/vendors.json` before invocation. Owned paths are never reclassified as vendor.

## YAML, shell, workflows, Docker, JavaScript

yamllint `1.38.0` extends `default`, so `document-start`, indentation, and comment rules are on. `line-length.max` is 100, the same length Ruff uses, not the yamllint default of 80 and not a disable. Truthy values are only `true` and `false`. `check-keys: false` is required because GitHub Actions and several schemas use the key `on`, which is a truthy word and not a boolean value. Helm and Ansible templates under `/templates/` and `*.j2` are not parsed as YAML.

Shellcheck uses `--enable=all` on `*.sh` and shell shebangs. Jinja templates are not shellchecked. Inline workflow scripts are parsed as Python or checked with the pinned shell dialect. An unrecognized shell is `workflow-shell-unreviewed`, not a skip.

Workflow security uses `zizmor --persona auditor`. Expression syntax uses actionlint without a second shellcheck or pyflakes pass. hadolint `failure-threshold` is `style` and `ignored` is empty. The single `DL3064` exception is the exact line `ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app` in `services/spi-tokenizer/Dockerfile`. Any other line fails. JavaScript is `node --check` only.

Not adopted, and not counted as a pass: ESLint, Prettier execution, Bandit beside Ruff `S`, Vulture, and mutation testing. Those need a reviewed tool lock or a test-owned change. This configuration does not add them.

## Ansible

ansible-lint `26.11.0` uses profile `min`, `offline: true`, and `strict: true`. Profile `min` always runs `internal-error`, `load-failure`, `parser-error`, and `syntax-check`. Every other rule printed by `ansible-lint -L` is either enabled or given a reason in `quality/strict-policy.json`.

`loop-var-prefix` is enabled without a `loop_var_prefix` setting, so only implicit `item` is flagged. A forced prefix would rename loop variables. `name[prefix]` is not added; that tag rewrites task identities used by `--start-at-task`.

These installed rules are not enabled:

- `args`, `complexity`, `warning`: experimental, not a stable contract. `strict: true` already fails real rule warnings.
- `event-query`: Ansible Automation Platform event catalogs only.
- `galaxy`, `galaxy-version-incorrect`, `meta-incorrect`, `meta-no-tags`, `meta-runtime`, `meta-video-links`, `role-argument-spec`: Galaxy or Automation Hub publication. `ansible/` is operational content.
- `only-builtins`: experimental, and it forbids collections the plays intentionally use.
- `role-name` and `var-naming`: would rename role paths or externally consumed variables without a consumer map.
- `yaml`: a second yamllint with a different config. `quality/yamllint.yaml` covers the same files.

`profiles.yml` in this release still names rules that `ansible-lint -L` does not provide: `layout`, `meta-version`, `no-changelog`, `max-block-depth`, `max-tasks`, `unsafe-loop`, `spell-var-name`, `avoid-dot-notation`, `import-task-no-when`, `meta-no-dependencies`, `single-entry-point`, and `use-loop`. They are not enabled because this binary has no such rule.

## Kubernetes

kube-linter `0.8.3` keeps every default check (`doNotAutoAddDefaults: false`) and adds the security and dangling-reference checks in `quality/kube-linter.yaml`. There is no `exclude` list. Defaults include `host-network`, `privileged-container`, `unset-cpu-requirements`, and `dangling-service`. Those findings stay visible, including cross-application dangling references.

Omitted optional checks, with the conflict:

- `no-rolling-update-strategy` would forbid `Recreate`, which single-writer ReadWriteOnce volumes require.
- `minimum-three-replicas` and `hpa-minimum-three-replicas` would override measured capacity and single-writer intent.
- `exposed-services` would forbid intentional NodePort and LoadBalancer publication.
- `restart-policy` would reject Job and CronJob `Never` / `OnFailure`.
- `dnsconfig-options` would force `ndots: 2` over the cluster DNS contract.
- `no-node-affinity` and `priority-class-name` invent scheduler policy this tree does not have.
- `required-annotation-email` and `required-label-owner` are organization metadata, not runtime controls.
- `schema-validation` would use kube-linter's unlocked schemas. kubeconform with the checksum-locked Kubernetes 1.36.0 schemas stays authoritative.
- `sorted-keys` is alphabetical cosmetics, not an admission property.

`writable-host-mount` and privileged-port checks are enabled. Reporting them does not weaken mount, existing-data, or single-writer guards, and this change does not edit those guards.

## Suppressions and secrets

`scripts/quality/strict_guard.py` fails the configuration when tool pins, rule partitions, vendor prefixes, or the reviewed secret false-positive digest drift. Inline `noqa`, `type: ignore`, `nosec`, shellcheck, yamllint, hadolint, kube-linter, and ansible-lint suppressions are blocking findings. They are not a baseline. Existing hits remain for the source partitions; this change does not delete them and does not add new ones.

Secret matches still pass only on an exact id, path, and rule in `quality/secret-false-positives.json`. The digest of that file is pinned in the strict policy.

## What this commit does not do

Source cleanup is not done. Downstream partitions still own `scripts`, `tests`, `ansible`, `manifests`/`services`, and `tools`/`workflows`. Kind acceptance, native reports, and the curated pytest suites stay in place. A strict lint or schema result is not production acceptance.
