# Parent repair: explicit test package and typed contract fixtures

This is implemented source work, not recovery by trusting the failed24-worker
batch. It changes no production entrypoint, policy, approvals, image, deployment,
storage, network or credential context.

## Package/import boundary

Added tests/__init__.py and changed all7statically discovered sibling-helper
imports to explicit tests-qualified imports. This makes the owned test package
explicit instead of ignoring INP001. The package was tested before proceeding:
fast702passed/1existing skip/329subtests; fast+medium collection1010tests, exit0.
Deferred tests were not executed to justify this change.

## Eight contract modules

Scope: alert_graph_panel_ids, deployment_ownership, gateway_readonly,
operational_entrypoints, source_pointers, spi_execution_links,
target_placement_ownership, vendor_contracts.

- Ruff ALL:182before,2remaining. Both remaining findings are still blocking:
  S106on the simulated Secret resource-name argument and S104on the deliberately
  rejected all-interface service-address fixture. Neither is approved/ignored,
  obfuscated or removed. Seven of the eight files have zero Ruff findings.
- Strict mypy with the collector's --follow-imports=silent:155errors before,
  zero after (all8source files). Baseline used --shadow-file with immutable
 4b2a1a1b sources, not a weaker config or a new source exclusion.
- Concrete TypedDict fixtures describe mutated Argo source forms, rollout
  ownership chains, operational classifications and cluster resource documents.
  Optional fields represent actual different fixture resource/source forms;
  there is no Any, cast, stub or ignored diagnostic.
- Missing dynamic import specs/loaders now fail explicitly before execution.
- Gateway fault callbacks are created by factories binding their command logs,
  fault points, endpoints and statuses. Two added tests invoke callbacks after
  the creating loop finishes to prove independent bindings and preserved fallback.
- Existing52test function definitions are retained with identical assertion ASTs
  and pytest.raises expressions. Parameterization produces58old executed cases;
  the two new cases bring the focused run to60passed/60subtests, exit0.
- Type/doc-only edits were initially checked for executable AST equality. Typed
  fixture declarations, explicit import preconditions, equivalent command-key
  indexing, callback factories and unexpected-path AssertionError were separately
  reviewed and exercised. No existing negative mutation was deleted.

## Validation before commit

- Locked Ruff formatter:8files unchanged, exit0.
- Locked strict mypy:8files, zero errors, exit0.
- Focused suites:60passed/60subtests, exit0.
- Full fast:704passed/1existing skip/329subtests, exit0.
- Contracts:25offline schemas,122/279modules scheduled, exit0.
- Strict guard:suppressions=0, exit0.

Private evidence is under ~/Library/Application Support/homelab/quality-strict/
(parent-eight-contracts-* and parent-test-package-fast.txt), mode0600.
These are precommit working-tree checks, not a complete exact-HEAD audit or
native/hosted admission claim. The whole repository remains red until the full
strict audit, real prerequisites and hosted admission are satisfied.
