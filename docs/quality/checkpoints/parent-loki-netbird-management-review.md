# Selective Loki, NetBird and management test repairs

Reviewed lanes09/10/11/15 without treating branch completion or a clean lint label as acceptance. Selected only the lane10 Loki native-scrape file and a strictly metadata-only port from two lane15 files. No whole worker commit or unchecked partial was integrated.

## Loki

Compared the complete module AST under an explicit normalization of annotations/docstrings, unchanged import inventory plus required pytest import, equality/false assertions and exception contexts. Added only the two exact loader-presence guards; conflict exception matching is stricter than the original ValueError-only check. All original fixtures, mTLS pins, additive/idempotent/unchanged-input predicates and conflicting-job case remain. Parent inspected the loaded helper; only pure configuration functions execute in these two scheduled offline tests. Pinned before/after: Ruff18→0, mypy5→0;2tests pass both times. Private full proof and raw results are retained.

## NetBird and VM105 management

The initial full worker-patch canonical comparison did not prove equivalence. Rather than dismissing that mismatch or accepting renamed/extracted expressions, parent retained the original runtime bodies, variable names, unittest assertions, subtests, decorators, defaults and fixture values. Only matching function signatures and documentation were ported from the reviewed candidate; standard-library imports were sorted separately. No new TypeGuard, unchecked callable-signature assertion, cast or Any was introduced.

Complete executable AST equality was independently checked before and after formatting, erasing only annotations/docstrings and the explicitly checked import ordering. All function parameter names/defaults remain unchanged. The unchanged source/read-only and temporary local Helm provenance tests pass:9tests, zero skips. Pinned mypy reports zero across both files. Scoped Ruff NetBird30→19 and management46→28; remaining rules are retained, not suppressed.

The inspected NetBird source-only module moved from deferred inventory to fast, with the matching deferred entry removed. Existing Loki and management scheduling remains intact. No provisioning, VPN/identity action, credential helper, installer, backup/archive/restore or live cluster access was performed. Rancher full vendored-byte and local Helm equivalence checks remain real. Source paths, native identities, security values, resource versions and authoritative-data intent were not altered.

Private proofs: `p56-10-parent-loki-native-proof.json`, `p56-10-loki-native-validation/`, `p56-15-parent-metadata-only-port-proof.json`, `p56-15-parent-partial-final-proof.json`. Whole-head audit/suite/hosted results must be tied to the subsequently committed exact head; the scoped47Ruff reduction is not a claim of global green. Other retained lane changes remain pending independent review.
