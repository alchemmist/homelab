# Quality Graph in Socrat

**[Quality Graph → quality-graph.xyz](https://quality-graph.xyz/)** is the upstream reference. This page describes our graph: what it checks, where the results appear and which file to change.

## What runs here

Our [graph declaration](../../qg.yaml) defines 18 blocking nodes. Read `needs` as a prerequisite, not a suggested order:

| Prerequisite | Nodes | What they check |
| --- | --- | --- |
| None | `graph` | Generated workflows and manifest match their sources; repository contracts, strict policy and selected Python checks pass. |
| `graph` | `docs-language` | Flags Russian alphabet characters by file and line in tracked text under `docs/` and in README files anywhere in the tree. Existing content blocks too; there is no baseline. This is not a general English-language detector. |
| `graph` | `yaml`, `javascript`, `shell`, `workflow`, `docker`, `secrets` | YAML structure, JavaScript syntax, shell scripts, GitHub Actions security, container recipes and credential findings. |
| `graph` | `python-scopes`, `scripts-q000`, `deploy-i001`, `rustfs-return-types` | Selected Ruff rules on specific paths: declared scopes, quotes and docstrings, import order and unused imports, and public return types in the RustFS gateway. This is not the full Python audit. |
| `graph` | `image-cves`, `tests-fast`, `ownership` | Trivy scans [selected deployed images](../../ci/quality/image_cves.py), the fast suite exercises repository code, and ownership checks verify infrastructure contracts, source pointers, operational entrypoints, vendor boundaries and alert definitions. |
| `ownership` | `ansible`, `dependencies`, `tests-medium` | Playbook safety, dependency audits and integration tests. These three wait for `ownership`, not for every sibling of `ownership`. |

The full `python`, `manifests` and `tests-cluster` checks are [outside this graph](../../ci/quality/local-checks.json). `make check` includes them. A green PR graph does not certify a Kind run, a production rollout or checks that were skipped.

## From declaration to PR result

1. **Define** nodes, runner profiles, prerequisites, policies and report paths in [`qg.yaml`](../../qg.yaml). Each node invokes `make <node>`; its recipe lives in the [Makefile](../../Makefile). The check implementations, tool locks and lint policies live in [`ci/`](../../ci/README.md).
2. **Generate** with `make graph-generate`. Our adapter uses the compiler pinned in [`uv.lock`](../../uv.lock) and applies repository YAML formatting. Commit the resulting [manifest](../../.quality-graph/manifest.json) and generated workflows; do not edit them by hand.
3. **Execute** on [pull requests](../../.github/workflows/quality-graph.yml) and [pushes to `main`](../../.github/workflows/quality-graph-push.yml). For a failure, open the named job: `image-cves` writes findings to its log, while nodes with declared outputs also produce native JSON or JUnit reports.
4. **Publish** separately. The [publisher workflow](../../.github/workflows/quality-graph-publish.yml) reconciles results on a schedule or by manual dispatch from the default branch. It updates the aggregate check and dashboard for the verified PR head. If the dashboard lags, distinguish the execution run from the publisher run before rerunning a check.

## Where to start

- **Reproduce one job:** `uv sync --locked`, then `make <node>` (for example, `make ownership`). Check that node's `profile` in `qg.yaml` for its tools, history depth and runner requirements. The medium suite needs full Git history; the fast and medium CI suites use Linux network isolation.
- **Change a gate:** edit its owning recipe or policy. For a new scoped Python rule, add a [scope declaration](../../ci/quality/python-scopes/) and run `make python-scopes`. If the graph declaration changed, run `make graph-generate` and `make graph-validate`. Validation checks generated-file freshness, not whether the underlying checks pass.
- **Investigate a policy or exception:** read the [enforcement policy](strict-policy.md). For earlier integration decisions and results, use the [CI enablement record](ci-enablement.md) or [historical evidence](strict-status.md), not those records' old node lists.
