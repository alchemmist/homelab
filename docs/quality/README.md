# Home Lab Quality Graph

[Research, rule/tool matrix and limitations](research-20261116.md).
[Initial failed-regression audit](initial-findings-20261116.md).

## Sources of truth

- `qg.yaml`: jobs, profiles, dependencies, event membership, result adapters/policy.
- `pyproject.toml` / `uv.lock`: exact Python quality toolchain.
- `quality/tools.lock.json`: Linux x86_64 and Darwin arm64 tool release SHA256 pins.
- `quality/schemas.lock.json`, `quality/schemas/`: offline Kubernetes1.36schemas.
- `quality/rules.json`: concrete selected Python/Kubernetes/YAML rule catalogue.
- `quality/test-suites.json`:114scheduled modules in20groups;127not yet scheduled.
- `quality/debt/`: exact legacy lint/resource identities; NOT fixed/approved-safe.
- `quality/secret-false-positives.json`: separately reviewed non-secret matches,
  exact context hashes and reasons; no credential values or whole-path ignores.

Generated workflow/manifest files are owned by Quality Graph. Never patch their
YAML by hand. `uv run qg generate` and `uv run qg validate` are the only normal
publication/freshness path. Do not add deploy credentials or `pull_request_target`.

## Local commands

```sh
uv sync --locked
uv run qg validate
uv run python scripts/quality/contracts.py
uv run ruff check --config quality/ruff.toml scripts/quality tests/test_quality_system.py
uv run python -m pytest -q tests/test_quality_system.py
uv run python scripts/quality/lint.py python
uv run python scripts/quality/lint.py yaml
```

Additional standalone tools can be installed explicitly into ignored local space:

```sh
uv run python scripts/quality/install_tools.py --tools shellcheck actionlint kubeconform kube-linter gitleaks
export PATH="$PWD/.quality-tools/bin:$PATH"
uv run python scripts/quality/lint.py shell
uv run python scripts/quality/charts.py --shard 0
```

Installer checks the downloaded asset SHA256, HTTPS-only redirects, allowed tool
name and regular archive member. It never executes an upstream installer or
extracts an archive tree. Release digests are observed GitHub metadata, not an
independent attestation/signature verification claim. Bounded downloads can fail;
there is no fall-through to an unpinned installed binary during installation.
Helm is separately pinned to3.19.0in CI; JS syntax uses Node24.11.1.

Tests use `uv run python scripts/quality/tests.py <suite>`. New CI test nodes pass
`--isolate-network`: Linux network namespace with loopback only. Missing isolation
is an error, never a silent fallback. Mac local tests are explicit non-isolated
fixture/source tests; do not treat an arbitrary operational script as a test.
The namespace prevents accidental external calls, not hostile CI code that has
runner sudo. No SSH agent/cloud credentials are passed to these test processes.

## Results and PR controls

- Lints/charts produce data-only `reports/<check>.json`, collected through
  `results.native`. QG owns identity, provenance, dashboard, annotations and controls.
- pytest writes JUnit per suite. Both unittest classes and plain functions execute.
- A command/setup/parser failure emits `failureKind=command`, never an accepted
  lint baseline. Missing/malformed JUnit remains failure, and stale XML is removed.
- Known debt and newly blocking findings are separate metrics. Semantic hashes
  survive line moves; duplicate occurrences have unique IDs. No blanket per-file
  acceptance and no CI baseline rewriting.
- Security/chart/integrity nodes disable finding/file/node approval escapes.
  Ordinary quality findings use the existing administrator policy and reversible
  `/qg ignore <finding>` / `/qg remove-ignore <finding>` controls. `/qg status` and
  `/qg help` belong in PR comments; no custom command bot is introduced here.
- Ansible-lint is explicitly advisory while the reproduced tool crash remains.
  Advisory does not mean its job passed. The full expanded graph is not yet a
  certified-green merge policy: see the initial failed-regression audit.

## Reviewed debt changes

Never run baseline generation to make an unexplained CI failure green. First
reproduce it, determine defect vs intended exception, verify source ownership and
choose repair or a narrow reviewed exception. Initial capture commands accept
`--record-debt '<review reason>'` outside CI only. Secret findings cannot use it;
false-positive review is separate and must not accept a live credential as debt.
No automatic fixes, runtime setting changes or deployment fallbacks are provided.

Before promotion, compare raw/effective PR results and findings, trigger a small
probe PR from the updated base, verify native status/log links/rerun/approvals and
fork security, then separately review required-check policy. No branch protection
has been changed by this package. Linux run43937975011exercised all42PR nodes
and uploaded42results;30passed/12failed. The framework itself passed20tests.
The failing expansion remains [draft PR181](https://github.com/alchemmist/homelab/pull/181),
not the active main merge policy. Backups, GPU/VPN work, identity reconciliation,
workflow execution and production maintenance remain outside this CI work.
