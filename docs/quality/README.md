# Quality Graph in Socrat

**[Quality Graph → quality-graph.xyz](https://quality-graph.xyz/)** is the upstream reference. This page describes our graph: what it checks, where the results appear and which file to change.

## What runs here

Our [graph declaration](../../qg.yaml) defines 16 blocking nodes. Read `needs` as a prerequisite, not a suggested order. Cheap checks fan out from `graph`; later nodes join several of those branches, the same shape as the monori review flow and the lazy-tmux packaging gate.

| Prerequisite | Nodes | What they check |
| --- | --- | --- |
| None | `graph` | Generated workflows and manifest match their sources; repository contracts, strict policy and selected Python checks pass. |
| `graph` | `docs-language`, `javascript`, `shell`, `docker`, `secrets`, `python-scopes` | Documentation language, JavaScript syntax, shell scripts, container recipes, credential findings, and the declared Ruff scopes. |
| `python-scopes` | `scripts-q000`, `deploy-i001` | Quotes and docstrings (Q000, D300), then import order (I001) and unused imports (F401). |
| `deploy-i001` and `scripts-q000` | `rustfs-return-types` | Public return types in the RustFS gateway, after the shared Python static gates. |
| `python-scopes`, `scripts-q000`, `deploy-i001` | `ownership` | Infrastructure contracts, source pointers, operational entrypoints, vendor boundaries and alert definitions. |
| `docker` | `image-cves` | Trivy scans [selected deployed images](../../ci/quality/image_cves.py) after their recipes pass. |
| `secrets` and `shell` | `workflow` | GitHub Actions security after credential hygiene and shell safety. |
| `ownership` and `shell` | `ansible` | Playbook safety. |
| `ownership` and `javascript` | `dependencies` | Dependency audit, including the JavaScript lockfile smoke check. |
| `ownership`, `docker`, `workflow`, `shell` | `tests-medium` | Integration tests after the contracts, images, delivery workflow and shell gates. |

`yaml`, `tests-fast`, `manifests`, the full `python` audit and `tests-cluster` stay [outside this graph](../../ci/quality/local-checks.json). `make check` includes them. A green PR graph does not certify a Kind run, a production rollout or checks that were skipped.

## From declaration to PR result

1. **Define** nodes, runner profiles, prerequisites, policies and report paths in [`qg.yaml`](../../qg.yaml). Each node invokes `make <node>`; its recipe lives in the [Makefile](../../Makefile). The check implementations, tool locks and lint policies live in [`ci/`](../../ci/README.md).
2. **Generate** with `make graph-generate`. Our adapter uses the compiler pinned in [`uv.lock`](../../uv.lock) and applies repository YAML formatting. Commit the resulting [manifest](../../.quality-graph/manifest.json) and generated workflows; do not edit them by hand.
3. **Execute** on [pull requests](../../.github/workflows/quality-graph.yml) and [pushes to `main`](../../.github/workflows/quality-graph-push.yml). For a failure, open the named job: `image-cves` writes findings to its log, while nodes with declared outputs also produce native JSON or JUnit reports.
4. **Publish** separately. The [publisher workflow](../../.github/workflows/quality-graph-publish.yml) reconciles results on a schedule or by manual dispatch from the default branch. It updates the aggregate check and dashboard for the verified PR head. If the dashboard lags, distinguish the execution run from the publisher run before rerunning a check.

## Where to start

- **Reproduce one job:** `uv sync --locked`, then `make <node>` (for example, `make ownership`). Check that node's `profile` in `qg.yaml` for its tools, history depth and runner requirements. The medium suite needs full Git history; the fast and medium CI suites use Linux network isolation.
- **Change a gate:** edit its owning recipe or policy. For a new scoped Python rule, add a [scope declaration](../../ci/quality/python-scopes/) and run `make python-scopes`. If the graph declaration changed, run `make graph-generate` and `make graph-validate`. Validation checks generated-file freshness, not whether the underlying checks pass.
- **Investigate a policy or exception:** read the [enforcement policy](strict-policy.md). For earlier integration decisions and results, use the [CI enablement record](ci-enablement.md) or [historical evidence](strict-status.md), not those records' old node lists.
