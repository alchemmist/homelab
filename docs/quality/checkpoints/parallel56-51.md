# Parallel 56 lane 51 checkpoint

Lane 51 is the yaml-semantic allocation at source head `72419ef6`.
The worker base contains parent `03bb16146e5d23ddb083aa170bdce1cc18c779d6`.
Only allocated files and this checkpoint were edited. Raw yamllint output
stays outside Git. No playbook, Helm, SSH, or cluster command was run.

## Repairs

`deploy/storage/grafana-socrat5/volume.yaml`

- Added the missing document start and three document end markers.
- Rewrote two empty `storageClassName` scalars from single quotes to double
  quotes. Both remain `tag:yaml.org,2002:str` with value empty.
- Names, UID, namespace, path `/mnt/files/homelab/grafana/data`, `Retain`,
  `local-path`, access mode, sync-options, and capacity are unchanged.

Quote style on 33 other allocated YAML files:

- 46 redundant quotes removed.
- 112 single-quoted scalars rewritten as double quotes.
- PyYAML `compose_all` with `Loader` and `SafeLoader` matched the pre-edit
  graph for every edited file: same tags, scalar values, mapping and sequence
  order, and no alias, anchor, tag, or directive tokens before or after.
- The only scalar differences are those quote-style changes.
- One redundant-quote removal in `ansible/roles/ssh/tasks/main.yml` also
  cleared one `line-length` finding. No other rule count increased.

## Left in place

- `charts/alertmanager/alert-graphs.values.yaml` (8 `quoted-strings`).
  `scripts/alert_graphs.py` byte-compares this generated file and is not in
  this lane.
- `deploy/monitoring/otel/loki.yaml` (8 `quoted-strings`). The retention
  renderer emits single-quoted selectors, and
  `charts/loki/files/loki.yaml` must stay byte-identical. That copy is not
  allocated here, so this file was not edited.
- `ansible/roles/wireguard_admin_client/tasks/main.yml` lines 96, 106, and
  144 keep `mode: '0600'` because
  `tests/test_wireguard_admin_client.py` pins that source token.
- Sequence indentation, comments, empty values, the comma spacing finding,
  and the Harbor trailing-space finding are outside this quote/framing pass.

## Commands

Parent pinned `yamllint 1.38.0`, worker cwd, `quality/yamllint.yaml`,
`subprocess.run(check=False)`.

| Check | Exit | Findings |
| --- | ---: | ---: |
| Lane yamllint before | 1 | 610 |
| After volume framing commit | 1 | 604 |
| After quote-style edits | 1 | 445 |

Final rule counts: `line-length` 267, `indentation` 93, `comments` 44,
`quoted-strings` 19, `empty-values` 15, `comments-indentation` 5, `commas` 1,
`trailing-spaces` 1. From the 610 baseline, `quoted-strings` fell 179 to 19,
`document-start` 1 to 0, `document-end` 3 to 0, and `line-length` 268 to 267.

Inspected offline tests, all exit 0:

- `tests.test_refactor_acceptance.GrafanaStorage.test_explicit_existing_data_and_retained_claims`
- `tests.test_deployment_ownership.DeploymentOwnership.test_argocd_bootstrap_version_and_values_match_git_owner`
- `tests.test_wireguard_admin_client` methods for the private-key pin, peer
  defaults, and direct endpoints (3 tests)
- `tests/test_moscow_native_primary.py::test_retirement_requires_gitops_zero_and_uid_precondition`
- `tests/test_k3s_overlay_marks.py::test_persistence_has_no_network_restart`
- `tests/test_recovery_20261109_contracts.py::test_vllm_chart_and_authoritative_admission_agree`
- `tests/test_otel_loki_retention.py::RetentionTests::test_copies_and_defaults`

`tests.test_wireguard_admin_client` also fails two methods on the unmodified
HEAD text: `become: true` occurs twice (the test expects at least four), and
the unedited admin-client template contains `DNS`. Those failures are not
caused by this lane.

## Remaining

445 lane findings remain. The 19 `quoted-strings` hits are the generated
alert-graph file, the paired Loki config, and the three pinned `0600` modes.
