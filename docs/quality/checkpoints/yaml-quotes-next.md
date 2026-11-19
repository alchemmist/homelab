# YAML quoted-strings checkpoint — owned plain chart values

This is not a clean YAML tree. Sixteen owned `charts/*/values.yaml` files had
redundant or single-quoted string scalars rewritten to the strict
`quoted-strings` form: bare when a plain scalar stays a string, double quotes
when the quotes are what keep the scalar a string. Vendor charts, the
byte-pinned rancher and litellm values, the reviewed secret-context file, one
Helm template scalar, and one test-pinned version token were not edited.
No yamllint disable, file ignore, debt approval, or policy change was added.
Those paths stay in the owned lint set. No Helm apply, production SSH,
kubeconfig, VPN, backup, or credential use was run.

Rule in force, unchanged: `quality/yamllint.yaml` `quoted-strings` with
`quote-type: double`, `required: only-when-needed`, `check-keys: false`,
`allow-quoted-quotes: false`. Tool pin: `yamllint==1.38.0`, `pyyaml==6.0.3`.

## Inventory

Plain files are exactly `charts/<name>/values.yaml` (49 paths). `owned()`
excludes the vendor prefixes `charts/litellm/` and `charts/rancher/`, so 47
are owned. Frozen compatibility inputs are `charts/spi-triage/files/*.py`
only; `charts/spi-triage/values.yaml` stays owned.

Thirty owned files had zero `quoted-strings` findings and were not edited:
`alertmanager`, `blog`, `cats`, `format-quorum`, `img-proxy`,
`kube-state-metrics`, `litellm-infra`, `lms`, `lms-database-ha`, `loki`,
`monitoring-llm`, `monori`, `netbird`, `node-exporter`, `nvidia-device-plugin`,
`open-webui`, `password-self-service`, `prometheus-operator`, `pyroscope`,
`remark42`, `socrat-bot`, `socrat-home`, `syncthing`, `tempo`, `thanos`,
`umami`, `uptime-kuma`, `vpn-transit`, `wishlist`, `x-ui`.
Other yamllint rules on those files were left as they are.

## Commands and exits

```text
uv run yamllint --version
```

Exit 0. `yamllint 1.38.0`.

```text
uv run yamllint --format parsable --config-file quality/yamllint.yaml charts/*/values.yaml
```

Before this batch, exit 1. 517 findings:

| Rule | Count |
| --- | ---: |
| line-length | 216 |
| quoted-strings | 104 |
| comments | 65 |
| comments-indentation | 46 |
| indentation | 40 |
| braces | 22 |
| empty-values | 16 |
| trailing-spaces | 4 |
| document-start | 2 |
| document-end | 2 |

The same command after the edits, exit 1. 430 findings. `quoted-strings` fell
from 104 to 17. Every other rule count above is unchanged, including
`line-length` 216. No finding was added.

`quoted-strings` before, 104 across 19 files:

| File | Before | After | Edited scalars |
| --- | ---: | ---: | ---: |
| `charts/authentik/values.yaml` | 14 | 1 | 13 plain |
| `charts/cert-manager/values.yaml` | 4 | 0 | 4 plain |
| `charts/grafana/values.yaml` | 17 | 0 | 16 double, 1 plain |
| `charts/grafana-mcp/values.yaml` | 1 | 0 | 1 plain |
| `charts/harbor/values.yaml` | 21 | 0 | 21 plain |
| `charts/monitoring-k3s/values.yaml` | 19 | 1 | 18 plain |
| `charts/n8n/values.yaml` | 1 | 0 | 1 double |
| `charts/open-terminal/values.yaml` | 1 | 0 | 1 double |
| `charts/pr-agent/values.yaml` | 1 | 0 | 1 double |
| `charts/prometheus/values.yaml` | 1 | 0 | 1 double |
| `charts/rustfs/values.yaml` | 1 | 0 | 1 double |
| `charts/searxng/values.yaml` | 1 | 0 | 1 double |
| `charts/spi-triage/values.yaml` | 1 | 0 | 1 double |
| `charts/traefik-edge/values.yaml` | 2 | 0 | 2 plain |
| `charts/venice-api/values.yaml` | 1 | 0 | 1 plain |
| `charts/vllm/values.yaml` | 3 | 0 | 3 double |
| `charts/litellm/values.yaml` | 2 | 2 | 0 |
| `charts/private-gateway/values.yaml` | 2 | 2 | 0 |
| `charts/rancher/values.yaml` | 11 | 11 | 0 |

87 scalars changed: 61 redundant quotes removed, 26 single-quoted strings
rewritten with double quotes. 17 `quoted-strings` findings remain, all on
unedited tokens.

Graph proof, before each file write and again on the bytes just written,
exit 0. For every edited file, `yaml.compose` with the default Loader and
`yaml.compose(..., Loader=yaml.SafeLoader)` produced the same signature
before and after: node tags, scalar values, mapping and sequence order, and
alias sharing. None of these 16 documents had an alias node (shared-node
count 0 on both sides). `yaml.unsafe_load` was not called. SafeLoader is the
constructor used when a loader object is built for the second compose;
compose itself only builds the node graph.

An independent compare of the pre-edit copies against the written files
repeated that check and also walked every scalar. The only differences were
string-scalar styles, and the style-change counts match the table above.
Failures: 0.

```text
uv run pytest -q tests/test_update_watch.py \
  tests/test_recovery_20261109_contracts.py::test_vllm_chart_and_authoritative_admission_agree \
  tests/test_observer_membership.py::MembershipTests::test_grafana_roles_are_explicit_without_unadmitted_viewer_fallback \
  tests/test_refactor_acceptance.py::GrafanaStorage::test_explicit_existing_data_and_retained_claims \
  tests/test_refactor_acceptance.py::GrafanaStorage::test_mcp_remains_read_only_stateless_and_exact_version
```

Exit 0. 8 passed. These load the edited values or assert the pinned
`current: "0.12.3"` source text. They are not a Helm render and not a
production check.

## What the edits kept

Each replacement was the scalar token only. Keys, comments, block scalars,
document markers, anchors, and neighboring tokens were not rewritten.

Plain scalars were used only where yamllint called the quotes redundant and
the compose tag stayed `tag:yaml.org,2002:str` with the same value. That
covers names, version strings, image tags, repository paths, and CIDR
strings. Digests were not on finding lines and were not edited. Already
double-quoted numeric strings, including the Harbor database port and the
vLLM numeric arguments, were not findings and were not turned into numbers.

Double quotes replaced single quotes where dropping the quotes would change
the tag. Resource limits stay strings (`"1"`, `"2"`, `"6"`), not integers.
Grafana OAuth environment values stay the strings `true`, `false`, and `1`.
`writerSecret` stays an empty string. `pushCommands` stays the string
`["/review"]`, not a YAML list. The Prometheus memory-overcommit expression
stays one folded string: the outer quotes changed from single to double and
the inner quotes were escaped, without joining the physical lines. That line
went from 95 characters to 99, still within the length limit.

The long Grafana role-attribute path was already over 100 characters. Removing
its redundant double quotes shortened it by two characters and left the
`line-length` finding in place. Parsed text, including the trailing `|| ''`,
is unchanged.

## Left unedited on purpose

- `charts/litellm/values.yaml` (2) and `charts/rancher/values.yaml` (11) are
  outside `owned()` and are byte-pinned (`charts/litellm/upstream-file-sha256.json`,
  `charts/rancher/UPSTREAM-SHA256.json`, and `deploy/contracts/vendors.json`).
- `charts/private-gateway/values.yaml` (2) is an exact path in
  `quality/secret-false-positives.json`. The file was not opened for edit.
- `charts/authentik/values.yaml:1129` is the Helm template string
  `{{ (include "postgresql.v1.database" .) }}`. It is still single-quoted.
  One `quoted-strings` finding remains.
- `charts/monitoring-k3s/values.yaml:231` is `current: "0.12.3"`.
  `tests/test_update_watch.py` asserts that exact source text, and this batch
  cannot edit tests. The other 18 `current` version strings in that file were
  unquoted; their decoded values are unchanged. One `quoted-strings` finding
  remains.

No candidate was dropped because compose disagreed. The two in-file skips
above were excluded before replacement. A one-line escaped form of the
Prometheus expression was not used: it would have created a 173-character
line. The folded double-quoted form passed compose and the length check.

A strict lint result is not production acceptance. 430 findings remain on
`charts/*/values.yaml`, including the 17 `quoted-strings` findings above.
