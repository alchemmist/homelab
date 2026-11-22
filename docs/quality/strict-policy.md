# Strict policy

This file is the enforcement contract for `ci/quality/strict-all`. It does not claim the tree is clean. Historical `ci/quality/debt/*.json` files stay visible and are marked `"acceptance": false`. They do not decide success, and `--record-debt` cannot regenerate them. `ci/quality/rules.json` is an old catalog, not this contract.

See [active CI scope](README.md#active-ci-scope) for hosted versus local checks. Graph integrity runs the strict configuration and suppression guard before dependent jobs; a guard failure blocks the graph. The full Python adapter remains a local check.

Monori (`/Users/antonmoss/code/monori`) is the reference for strict Python, read-only. It selects Ruff `ALL` with `strict` mypy. Its test ignores (`D*`, `S105`, `S106`, `S107`, `F401`, `PLR2004`) and its `D212` choice are not copied. Homelab's exceptions for test modules and assertions are described below.

## Python

- Ruff `0.15.12` selects `ALL`. The formatter check is mandatory.
- `D203` is ignored because it cannot pass together with `D211`. PEP 257 keeps `D211`.
- `D213` is ignored because it cannot pass together with `D212`. PEP 257 keeps `D212`.
- `ISC001` is ignored because the formatter can introduce the concatenations it forbids.
- `COM812` is ignored because the formatter owns trailing commas. The defect remains visible through `ruff format --check`.
- `ISC002` stays enabled. Its formatter conflict requires `allow-multiline = false`, which is not set.
- `tests/**/test_*.py` ignores only `D102` and `D103` for missing method/function docstrings. The behavior name serves as the test description. This covers both direct modules in `tests/` and nested suites in `blog_updates`, `kubernetes`, `n8n`, `openhands`, `spi_triage`, `swe_mini`, and `wiki_openapi`.
- Ruff matches files, not function names: colocated test helpers share the module's exception. Separate helpers such as `tests/public_entry_contract.py` and the SSH integration driver keep both rules. There is no missing-module/class docstring or docstring-style exemption. The independent `**/tests/**` exception for pytest assertions (`S101`) is unchanged; it does not extend to experiments.
- mypy `2.4.1` uses `strict` plus `warn_unreachable`, `explicit_package_bases`, `disallow_any_explicit`, `disallow_any_unimported`, `disallow_any_decorated`, `strict_equality_for_none`, and the extra error codes in `ci/quality/mypy.ini`.
- The config file does not set `follow_imports`, `ignore_missing_imports`, or `disable_error_code`. The adapter passes every owned Python file and `--follow-imports=silent` so imported modules that are themselves in that set still report. Missing third-party stubs stay `import-untyped` findings. Stubs are not installed to hide them.
- A syntax error is a source finding for that file. It is parsed first so mypy's fatal exit 2 cannot drop the rest of the owned set. If mypy still stops (`Duplicate module`, an internal traceback, or exit 2), the adapter retries by directory and then by file. A batch that exits 2 is never stored as a complete audit. `mypy coverage incomplete` is a tool failure, distinct from source findings. The owned-file count is claimed only after every file was examined.
- There is no Ruff `exclude`. Vendor trees are omitted by `deploy/contracts/vendors.json` before invocation. Owned paths are never reclassified as vendor.

## YAML, shell, workflows, Docker, JavaScript

yamllint `1.38.0` extends `default`. `line-length.max` is 100, the same length Ruff uses, not the yamllint default of 80. Truthy values are only `true` and `false`. `check-keys: false` is required because GitHub Actions and several schemas use the key `on`, which is a truthy word and not a boolean value. Comment, comment-indentation, document-start, and truthy findings are errors. `document-end` requires the document end marker. Implicit octal values are rejected; explicit `0o` forms stay allowed because they are the unambiguous spelling. Floats must have a numeral before the decimal point. Scientific notation, NaN, and infinity stay allowed because forbidding them would reject real numeric data. Helm and Ansible templates under `/templates/` and `*.j2` are not parsed as YAML.

`key-ordering` cannot pass together with ansible-lint `key-order`: task mappings
use that semantic order, not Unicode alphabetical order. Its scope outside
Ansible still requires review; it is not a completed architecture-policy audit.

Two earlier disable rationales were factually wrong and have been removed.
`empty-values` flags implicit nulls, **not** `permissions: {}`. Explicit null and
empty maps stay valid; implicit empty mapping and sequence values now fail.
`quoted-strings` applies to string scalars, not boolean/number coercion. It now
enforces double quotes when necessary and rejects unnecessary quotation, the
compatible bare-scalar style rather than an exception. Key checking stays off
for the same cross-schema `on` boundary as truthy-key checking. These are blocking
rules, not accepted historical debt. A pinned-tool stdin test proves both rules
reject violations while least-privilege empty permissions and typed booleans/
numbers remain valid. Newly revealed findings must be repaired, not baselined.

Shellcheck uses `--enable=all` on `*.sh` and shell shebangs. Jinja templates are not shellchecked. Inline workflow scripts are parsed as Python or checked with the pinned shell dialect. An unrecognized shell is `workflow-shell-unreviewed`, not a skip.

Workflow security uses `zizmor --persona auditor` on the whole `.github/workflows` directory. Generated files are included. There is no rule allowlist and no generated-file waiver. Every tracked workflow is explicitly passed to actionlint with ShellCheck and Pyflakes required, and to zizmor in strict collection mode without loading repository configs. CI provides the job’s read-only token to enable online audits; a local run without GH_TOKEN does not verify those online rules. hadolint `failure-threshold` is `style` and `ignored` is empty. The single `DL3064` exception is the exact line `ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app` in `services/spi-tokenizer/Dockerfile`. Any other line fails. JavaScript is `node --check` only.

The generated publisher reconciles PR results on a default-branch schedule instead of `workflow_run`. Neither it nor the command handler checks out PR code. Each write permission is documented at its point of use. GitHub can delay scheduled runs; a passing execution job alone does not replace the aggregate check. If the base changes before publication, update the PR and rerun on the new head. Generated workflows have no audit exemptions.

Not adopted, and not counted as a pass: ESLint, Prettier execution, Bandit beside Ruff `S`, Vulture, and mutation testing. Those need a reviewed tool lock or a test-owned change. This configuration does not add them.

## Ansible

ansible-lint `26.11.0` uses profile `min`, `offline: true`, and `strict: true`. Profile `min` always runs `internal-error`, `load-failure`, `parser-error`, and `syntax-check`. Every other rule printed by `ansible-lint -L` is either enabled or given a reason in `ci/quality/strict-policy.json`.

`loop-var-prefix` is enabled without a `loop_var_prefix` setting, so only implicit `item` is flagged. A forced prefix would rename loop variables. `name[prefix]` is not added; that tag rewrites task identities used by `--start-at-task`.

These installed rules are not enabled:

- `args`, `complexity`, `warning`: experimental, not a stable contract. `strict: true` already fails real rule warnings.
- `event-query`: Ansible Automation Platform event catalogs only.
- `galaxy`, `galaxy-version-incorrect`, `meta-incorrect`, `meta-no-tags`, `meta-runtime`, `meta-video-links`, `role-argument-spec`: Galaxy or Automation Hub publication. `ansible/` is operational content.
- `only-builtins`: experimental, and it forbids collections the plays intentionally use.
- `role-name` and `var-naming`: would rename role paths or externally consumed variables without a consumer map.
- `yaml`: a second yamllint with a different config. `ci/quality/yamllint.yaml` covers the same files.

`profiles.yml` in this release still names rules that `ansible-lint -L` does not provide: `layout`, `meta-version`, `no-changelog`, `max-block-depth`, `max-tasks`, `unsafe-loop`, `spell-var-name`, `avoid-dot-notation`, `import-task-no-when`, `meta-no-dependencies`, `single-entry-point`, and `use-loop`. They are not enabled because this binary has no such rule.

## Kubernetes

kube-linter `0.8.3` keeps every default check (`doNotAutoAddDefaults: false`) and adds the security and dangling-reference checks in `ci/quality/kube-linter.yaml`. There is no `exclude` list. Defaults include `host-network`, `privileged-container`, `unset-cpu-requirements`, and `dangling-service`. Those findings stay visible, including cross-application dangling references.

Omitted optional checks, with the conflict:

- `no-rolling-update-strategy` would forbid `Recreate`, which single-writer ReadWriteOnce volumes require.
- `minimum-three-replicas` and `hpa-minimum-three-replicas` would override measured capacity and single-writer intent.
- `exposed-services` would forbid intentional NodePort and LoadBalancer publication.
- `restart-policy` would reject Job and CronJob `Never` / `OnFailure`.
- `dnsconfig-options` would force `ndots: 2` over the cluster DNS contract.
- `no-node-affinity` and `priority-class-name` invent scheduler policy this tree does not have.
- `required-annotation-email` and `required-label-owner` are organization metadata, not runtime controls.
- `schema-validation` would use kube-linter's unlocked schemas. kubeconform with the checksum-locked Kubernetes 1.36.0 schemas stays authoritative.

`sorted-keys` is enabled. Alphabetical manifest keys are a consistency rule with no single-writer, replica, or admission effect. Findings stay on the manifests partition; this change does not reorder manifests.

`writable-host-mount` and privileged-port checks are enabled. Reporting them does not weaken mount, existing-data, or single-writer guards, and this change does not edit those guards.

## Suppressions and secrets

`ci/quality/strict_guard.py` fails the configuration when tool pins, rule partitions, vendor prefixes, the reviewed secret false-positive digest, the yamllint enable/disable contract, or the generated publisher surface drift. Inline `noqa`, `type: ignore`, `nosec`, shellcheck, yamllint, hadolint, kube-linter, and ansible-lint suppressions are blocking findings. They are not a baseline: fix the source or leave the finding visible rather than adding a directive. A fatal mypy run cannot be reported as full coverage of the owned Python files.

Secret matches still pass only on an exact id, path, and rule in `ci/quality/secret-false-positives.json`. The digest of that file is pinned as `reviewedExceptionDigest`. The pin name does not contain `secret`: that word made gitleaks treat the hash as a generic API key. The reviewed list itself is unchanged.

## What this commit does not do

Source cleanup is not done. Downstream partitions still own `scripts`, `tests`, `ansible`, `manifests`/`services`, and `tools`/`workflows`. Kind acceptance, native reports, and the curated pytest suites stay in place. A strict lint or schema result is not production acceptance.
