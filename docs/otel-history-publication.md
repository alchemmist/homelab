# Historical publication — closed without a second copy

The serving history is the original Thanos raw bucket. It still answers queries
older than Prometheus retention. Replacing those blocks with OTLP round-trips is
cancelled. New samples are in that same store only after the cluster collector
scrapes them and writes OTLP into Prometheus.

Done means both of these, and nothing further:

- Prometheus has the OTLP receiver on and does not scrape. The collector is the
  only scraper.
- A Thanos query older than local retention still returns node metrics.

The conversion workspaces, frozen archives and staged candidates are disposable
once those two checks pass. They are not a second copy of the served history.

# Historical publication preparation — no production changes

This is a **preparation/runbook**, not an execution authorization. The offline
ledger `scripts/otel-history-publication-plan.py` never contacts production or
moves TSDB data. Every generated report keeps `productionPublicationApproved`,
`productionModified` and `allCurrentHistoryVerified` false. No history is published
by the tail roundtrip queue.

## Current reconciliation

Use `deploy/monitoring/migration-evidence/history-publication-preparation-20261101.json`
for the timestamped, input-SHA-bound ledger. Metadata snapshots are lightweight:
`meta.json`, native verification/durability receipts and queue progress only; no
additional full chunk scan was launched alongside the importer.

The ledger has 17 source rows: six original backup blocks, the snapshot, the
already repaired current block and nine frozen tail sources. **Do not add their
sample counts as a unique-history total.** Four backup/snapshot candidates have
complete label/timestamp/float-bit/multiplicity containment proofs against the
repaired current block. They remain recovery artifacts, not additional serving
blocks. The two tiny OOO tail sources are independent multiplicity, not duplicates
merely because their time ranges overlap a larger block.

- Four contained candidates: `01M61PJFZ9Q86GRQ70N0M81NH3`,
  `01M68X0C52EXRRVDQGF12XAYGH`, `01M68YFW7529BN0T0KJZ0W9XRJ`,
  `01M69T4GP87P4YY0DBE7N7Q2JJ`. Do not publish these beside the full current replacement.
- Two backup originals are absent from the observed live raw bucket:
  `01M5P6GGQM3K9NAF43KP5JX3JW` and `01M5VBA2WTA1H8QE21D6PHVHWY`.
  Native downsampled counterparts are present. Absence is not proof that restored
  raw blocks may be inserted: reconcile active coverage, ancestry, retention and
  query resolution first. Do not remove downsampled aggregates as if they were
  duplicate raw samples.
- The current raw repair `01M66BZJJH7AX3HTZFRZD02SXP` maps to verified native
  candidate `01M6BBYTZHHWT579DX99J3S7EF`. The earlier **repair** was published;
  this subsequent OTLP-roundtrip **replacement** has not been published.
- First tail source `01M66G9HT3YJ4W6TSADWG305M6` maps to completed native candidate
  `01M6C1A7HHG5S3K3F4WCXNR61C` (847,811,515 samples). Remaining tail rows must wait
  for actual completed full-canonical/native/durability receipts, not checkpoint counts.
- The snapshot contains 55 live bucket metadata entries. Of 44 outside the planned
  original IDs, four are native downsampled aggregates and 40 have ranges starting
  after the frozen conservative legacy-boundary upper bound. Preserve all of them.
  This time classification is **not** a proof of their ingestion path, complete
  canonical integrity, or full current-history migration acceptance.

Native histograms and downsampled aggregates unsupported by the converter remain
native with explicit exceptions. The old backup classification is not a new
whole-production histogram census. Any unclassified pre-boundary block or changed
source identity blocks execution until reconciled.

## Preparation and evidence refresh

Example, executed on the controller with private metadata files:

```sh
python3 scripts/otel-history-publication-plan.py \
  --snapshot "$CROOT/history-publication-metadata-socrat-0.json" \
  --snapshot "$CROOT/history-publication-metadata-socrat-1.json" \
  --tail-scope "$CROOT/cutover-tail-scope.json" \
  --output "$CROOT/history-publication-plan-NEW.json"
```

The planner refuses metadata older than 15 minutes, duplicate block identities,
ambiguous content candidates, inconsistent archive scope and mismatched completed
receipts. Output is exclusive-create, mode 0600 and fsynced. This **does not** make
its observations transactionally fresh: rerun immediately before execution and
bind exact files under the writer/serving barriers. The report has no executable
shell commands and cannot be passed as approval to a publisher.

## Required execution gates — all remain pending

1. Finish all nine tail roundtrips. For each, require equality of full original and
   restored canonical content, supported sample semantics, native Thanos index and
   query verification, correct external labels/resolution/time bounds and durable
   staged bytes. Check every source against the frozen archive, including OOO.
2. Refresh the full raw/5m/1h inventories, deletion marks, source ancestry and
   supported/unsupported type scope. Reconcile all boundary intersections and
   prove which raw representations cover each candidate. Do not resurrect
   deletion-marked sources or infer content equality from count/time/ancestry.
3. Collect private preimages: relevant Deployment/StatefulSet/CronJob specs,
   active jobs, Query endpoints/flags, object-store mount paths, resource versions,
   block file inventories and current serving identities. Never print credentials.
   Include sidecar, every Store/raw/downsample endpoint and any Query replicas.
4. Identify and fence **only the competing historical bucket writers** (raw
   compactor, downsample/cascade jobs, upload/move paths and any maintenance jobs).
   Suspend their schedules, allow active work to drain naturally, confirm no owner
   can mutate selected blocks, and bind a recoverable lease/preimage. Do not stop
   the live Collector or Prometheus ingestion. If isolation cannot be demonstrated,
   do not mutate the bucket.
5. Prepare verified candidates on socrat-0 outside every served bucket; check
   total peak disk requirement (including rollback files/cache/ongoing import) and
   >=20% disk/memory reserves. Avoid a redundant full corpus copy or scan during
   import. Bind exact immutable file SHA inventories before publication; the
   planner's receipt/metadata matching does not replace this gate.
6. Rehearse the **serving barrier** and reverse barrier before execution. A plain
   filesystem rename is insufficient: running Store processes cache original
   metadata and chunks; consistency/deletion-mark delays are not a transaction.
   Withdraw the affected historical endpoints from **all** production Query
   replicas, prevent an alternate route, and drain already-started queries under
   the configured timeout. Stop/recreate the affected Store only through the
   planned controlled handoff after its queries drain. Verify no original can
   still be served before exposing replacement files. If Query cannot represent
   a safe historical-read pause, use an explicitly approved maintenance window;
   never claim uninterrupted historical availability. Endpoint withdrawal alone
   is not proof that earlier queries have finished.
7. With serving withdrawn and competing writers fenced, move only the proven
   superseded originals to a private rollback directory **outside all bucket
   roots**, then expose their exact replacements. Keep an ordered fsynced journal
   and revalidate every move/file inventory. Same-filesystem rename may reduce
   copying, but several block moves are not one atomic transaction; on interruption
   keep historical serving withdrawn until the journal is reconciled. Never copy
   replacements into a live bucket while their originals remain discoverable.
   Never retire OOO companions without their own exact replacement/containment proof.
8. Start an isolated stock Store/Query on the candidate-only view. Verify raw
   queries with `max_source_resolution=0`, `dedup=false`, no partial responses,
   exact labels/timestamps/float bits and multiplicity. Check before/inside/after
   every boundary and the specifically waived metric interval. Reconcile native
   downsample paths and auto-downsampling separately; deduplication must not hide
   replacement/original overlap. Require Store discovery to list only the intended
   raw identities. Check all production Query replicas and any caches/routes.
9. Restore production historical routing only after the exclusive replacement
   view passes. Confirm the same datasource UID `prometheus`, 78 fresh/UP sources,
   OTLP receiver progress and expected historical results. Restore historical job
   ownership/schedules from the preimages only after validating that compaction
   will preserve external labels and original ancestry, not regenerate duplicates.
10. Record actual publication, exact replaced/retained IDs, native exceptions,
    query checks, original preservation and rollback evidence. Only then update
    publication status. Final genuine 72h/capacity/SDK acceptance remains separate;
    it does not block integrity-qualified publication and is not waived by it.

## Rollback — reverse the serving barrier, never co-serve

Rollback is required if any byte inventory, native query, discovery identity,
capacity gate or production source freshness check fails.

1. Keep/fence historical writers; withdraw replacement historical routes from
   every Query replica and drain in-flight replacement reads. Preserve the failed
   candidate, its receipts, logs and move journal. Do not force-kill production.
2. Stop the affected historical Store under the same controlled barrier. Move
   replacements out of all served roots **before** returning exact retained
   originals; restore only IDs actually retired by this transaction. Do not undo
   the separately authorized prior repair or reintroduce its corrupt source.
3. Verify original inventories, metadata/deletion-mark state and native discovery
   in isolation. Run the original query anchors with dedup disabled and raw
   resolution selected. Restore Query endpoints and historical schedules from
   preimages only after the original-only view passes.
4. Verify the 78-source live ingestion remains healthy; record rollback status and
   any historical-read pause. Keep both originals and failed artifacts. This
   written procedure is not evidence of a completed production rollback exercise.

## Allowed loss and outstanding acceptance

The only allowed loss is the already documented 120 samples of
`node_scrape_collector_duration_seconds`, 1793276401534–1793276996534 ms. The repaired
6,383,043,932-sample content is the baseline now; publication/rollback must not
expand that exception, delete sources, reduce retention or restore the corrupt
pre-repair block. Preserve the quarantined original as evidence, never as serving
rollback data.

Deferred work remains explicit: cross-app SDK/inference proofs, complete source
coverage/lifecycle, production-owner rollback exercise, sustained capacity and
configuration-bound genuine 72h observation. Socrat-2's paused capacity observer is
not evidence that the production agent is stopped and is not a reserve waiver.
