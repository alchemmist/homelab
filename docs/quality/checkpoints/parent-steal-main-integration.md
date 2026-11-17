# Integrate main's additional CPU-steal regression without losing coverage

Before publication fetched another new main commit701825ec084410cfab5edcc4880521f7671a62d7:
owner-approved socrat-4CPU-steal threshold/duration split, monitoring documentation
and tests/test_socrat4_steal.py. Merged it without changing the owner's source rule
or performing operational execution. New test classification was not bypassed:
explicitly scheduled the reviewed offline Helm/promtool module in medium. The
catalog is now123/280scheduled modules;157remain explicitly deferred.

Repaired the new test rather than accepting new main lint debt:
- Ruff ALL79findings ->0; strict mypy and formatter pass;
- all6original node/value/duration/firing cases retained;
- the parent comparison harness confirms identical4complete generated YAML
  documents and3native argv vectors (executable basename normalization only);
- both native promtool executions retained through the existing checked runner;
- explicit executable resolution, missing-prerequisite failure and no fallback.

Canonical generation again proposed only the same two diagnostic output files.
The complete inventory changed204->205rows: precisely one old
SocratNodeCPUStealHigh row replaced by two main variants. All other rows remain
identical, existing graph specifications still match and the panel-ID ledger is
byte-identical. Only those2outputs were written. Updated the explicit source count
to account for both independently reviewed owner-approved alert splits; did not
drop its assertion or weaken real rendered-condition comparison.

For comparison, the previous exact8e8a3c51 head passed fast708/1existing skip/
329subtests and medium302/5existing skips/314subtests; contracts, guard and graph
passed. Full strict audit was49937blocking, configurationReady=true,
snapshotStable=true, clean Git and no collector blockers. Python native report
was14876964bytes pretty /11241439bytes compact (including a final newline), and
41786findings. BOTH fixed native input/finding ceilings remained exceeded.
No compaction, truncation, new exception or policy change was used.

These historical numbers are not claimed as the result for this new commit.
Exact committed-head checks must be rerun before publishing the draft branch;
full strict/native/hosted green remains required before merging.
