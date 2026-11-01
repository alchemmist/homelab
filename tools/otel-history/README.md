# Isolated historical OTLP roundtrip

This tool reads copied raw Prometheus TSDB blocks using the Prometheus v3.15 library, exports standard OTLP protobuf batches and imports them offline into a new isolated TSDB block. It does not send historical samples to production or replace Thanos blocks.

## Build and test

```sh
cd tools/otel-history
GOTOOLCHAIN=go1.26.7 go test ./...
GOTOOLCHAIN=go1.26.7 go vet ./...
GOTOOLCHAIN=go1.26.7 go build -o /tmp/otel-history .
```

The explicit toolchain avoids the incomplete local Homebrew Go 1.27.1 installation encountered during implementation (`internal/routebsd` missing). Dependencies are pinned by `go.mod` and `go.sum`.

## Commands

Use an immutable copy extracted from a verified backup, never the live Prometheus head/WAL. Output parents must already exist. Output directories are exclusive and production paths are rejected.

```sh
/tmp/otel-history capabilities --source /tmp/workspace/BLOCK_ULID
/tmp/otel-history inventory --source /tmp/workspace/BLOCK_ULID
/tmp/otel-history export --source /tmp/workspace/BLOCK_ULID --output /tmp/workspace/otlp --max-bytes 4294967296
/tmp/otel-history import --source /tmp/workspace/otlp --output /tmp/workspace/restored
/tmp/otel-history verify --source /tmp/workspace/otlp --block /tmp/workspace/restored/NEW_BLOCK_ULID
```

For a bounded pilot, add `--metric node_cpu_seconds_total` to export. The manifest and verification receipt explicitly mark this as an incomplete source-block export. A successful pilot is not approval of whole-history migration.

Files are standard gzipped `ExportMetricsServiceRequest` protobuf messages. Unknown historical metric types are represented as gauges without inventing cumulative/delta metadata. This preserves the untyped numeric TSDB series through the offline importer; it is not a recommendation for live SDK counter instrumentation.

The manifest records original block metadata, selection, sample count, compressed-file SHA-256 and a canonical hash of ordered original labels, timestamps and float bits. Import restores the original time bounds, semantic Thanos metadata and (for complete blocks) source compaction ancestry while generating a new block ULID, then rereads the block to verify canonical samples. Physical Thanos inventories are rebuilt from the actual native index/chunk files; stale file sizes, segment inventories, index statistics and upload timestamps are not copied. The verifier checks these separately from signal identity. Counter resets, Unicode labels, infinities, NaN payloads and stale markers are tested. Stale markers use standard `DataPointFlags.NO_RECORDED_VALUE_MASK`; offline import restores the exact Prometheus stale-NaN bits. An integration test checks exported protobuf against the pinned Prometheus 3.15 OTLP translator. Batches are bounded to 5,000 points and 32 MiB of uncompressed protobuf; the compressed output budget is enforced separately.

## Intentional safety limitations

- Downsampled blocks are refused and remain native.
- Native histograms are refused rather than silently coerced. The complete source block remains native if unsupported samples are encountered. Staleness itself is supported by standard OTLP.
- No successful manifest is written for a failed/over-budget export. Partial directories are retained for inspection and must not be imported or published.
- Existing output directories are not overwritten. `scripts/otel-history-migrate.py` coordinates verified archives and resumes completed blocks or interrupted final verification. Partial OTLP streams and incomplete imports still require inspection; they are not overwritten. Multi-source label-context conflicts and imported-store query compatibility need separate validation.
- Import bounds each mutable native TSDB Head to 2,500,000 samples plus at most one 5,000-point batch, then flushes and closes it. Upstream Prometheus compaction merges private shards in groups of at most 16 until one block remains. Final canonical verification is unchanged; intermediate receipts explicitly are not canonical-verification receipts. Private shards and merge outputs are retained, so disk projections must include them. This sample bound is not a hard RSS limit (manifest cardinality, labels, mmap and compaction also consume memory). The 20% filesystem reserve is checked before shard flush and with a conservative additional-copy estimate before each compaction group.
- Tombstones are applied by the Prometheus block querier. Verification covers query-visible samples, not byte-identical original TSDB files. Original files remain in the backup.
- A source block can contain hundreds of millions of samples; do not interpret the default byte cap as a complete capacity forecast. Start with a selected real metric and measure CPU, memory and expansion before a whole-block export.
- Production Thanos Query never includes original and reimported copies of the same raw range simultaneously.

The initial pilot is recorded in `deploy/monitoring/migration-evidence/history-pilot-20261028.json`. A complete 235,173,517-sample block, including 22,716 stale markers, passed exact canonical verification; see `history-whole-block-20261028.json`. Chunk-level classification found 18,500,148,016 samples in seven active raw blocks. Only one is roundtrip-verified so far; whole-history and isolated Thanos query compatibility remain unverified. The original snapshot lacks sidecar external-label metadata: resolve that context explicitly before serving its restore through Thanos.


## Background archive jobs

`scripts/otel-history-job.py` launches a pinned executable in a detached session against an already prepared private workspace. The coordinator uses an exclusive workspace lock; a second writer fails closed. Each job has a private request, log and exit-status receipt under `WORKSPACE/jobs/`. A missing result file is not proof of liveness. Completion must be verified from the actual result and canonical block receipts.

The launcher defaults to a 64 GiB compressed cap per block and a 12-hour timeout per export/import command, with `GOMAXPROCS=2` and a soft 2 GiB Go heap target. These defaults do not prove a sufficient worker-memory or complete retention budget. Each block still needs the filesystem reserve check. A detached process survives the initiating command session, not reboot or arbitrary control-host loss. Incomplete streams are retained and never overwritten. No production deployment or cutover is triggered by the background worker.

## Interrupted exports

`export --resume` accepts only an existing private non-symlinked incomplete output directory. It reconstructs the source stream and compares the decoded bytes of every existing batch before reuse; it never overwrites mismatched batches or a completed manifest. Import orders batch filenames by their numeric sequence, including the transition from `999999` to `1000000`. Partial TSDB imports are not automatically repaired or deleted.


## Explicitly approved recovery of one corrupt chunk

`recover-chunk --source PRESERVED_BLOCK --output NEW_PRIVATE_DIRECTORY --loss-approval APPROVAL.json` is a separate incident-recovery operation, not an export/import compatibility mode. It requires an approval that pins the block ULID, chunk reference, complete-series label SHA256, exact chunk timestamps, stored/actual CRC32C, sample count and every preserved input-file SHA256. The maximum approved window must be at most one day. Existing tombstones require separate accounting and are refused. The preserved source is never modified, and the output must not be inside it.

The command copies and rehashes the complete source into a new private workspace, writes a stock Prometheus tombstone for that exact series/time interval and uses the upstream TSDB compactor. A fully deleted chunk is skipped by the stock block querier before CRC decoding; no checksum is bypassed or rewritten. All other chunks must decode normally. Both the filtered source and independently compacted result must contain exactly `original sample count - explicitly approved removed sample count`, with equal full canonical hashes. Time bounds, compaction ancestry and semantic Thanos labels/resolution/source remain unchanged; physical file inventories are regenerated. Any other loss or mismatch fails closed.

The recovery receipt is **not** a whole-history roundtrip receipt or permission to publish. Native production-Thanos query compatibility, transport/read integrity, isolated replacement and all migration gates still apply. The first real recovery preserved 6,383,043,932 samples exactly outside one 120-sample gap; publication remained blocked by recurrent cached-read instability on the source node. See the 2026-10-30 approved-recovery and source-read-instability evidence. Do not replace the original canonical baseline with a loss-filtered one without retaining the explicit loss authorization and gap receipt.


## Completed legacy-worker output: physical metadata normalization

An older pinned worker can have exact canonical samples but outdated physical Thanos inventories or private-shard compaction ancestry. Do not weaken verification or edit a running coordinator's output. Make a separate private copy:

```sh
otel-history normalize-native-metadata \
  --source /private/export-with-manifest \
  --block /private/completed-legacy-output/ULID \
  --output /private/new-normalized-copy
```

The command validates the complete export hashes, source bounds/semantic context and canonical samples before copying; preserves the 20% filesystem reserve; rebuilds native physical metadata; restores source ancestry only for whole blocks; and repeats canonical plus metadata verification afterward. Nested/pre-existing outputs are rejected. Original output and production buckets are unchanged. A partial metric pilot must never claim all original ancestors. A snapshot without external Thanos label context remains without that context: establish it independently before serving through Query. Metadata verification alone is not isolated native Store/Query compatibility or a production cutover.

`scripts/otel-history-native-metadata.py` can follow atomically published completed block receipts from an existing coordinator and normalize each into an isolated workspace. It stops on source-job or normalizer failure, never starts another importer, and never modifies production or claims the entire migration complete.

## Independent host source canary

`cmd/host-source-probe` uses the upstream Prometheus text parser to compare legacy → native candidate → legacy scrapes. It checks full family/type/help/ordinary-label sets and selected stable constants exactly, reports explicitly observed legacy churn, and does not pretend unrelated live gauges were sampled simultaneously. Duplicate samples and explicit source timestamps fail closed; unexpected labels are represented only by SHA256 in receipts, never raw bodies.

`ansible/playbooks/otel-host-source-canary.yml` runs the exact official exporter executable pinned by `deploy/monitoring/otel-node-exporter.lock.json` in a bounded temporary native systemd unit: loopback 19100, 64 MiB memory maximum, 180s runtime maximum, UID/GID 65534. The unchanged textfile path labels are preserved by a standard read-only systemd bind; process timezone matches the original image. A new private result is required, executable hashes and root ownership are checked, and the unit is stopped in cleanup. This is source compatibility validation, not the four complete OTLP agent pipelines or a Kubernetes-shutdown failure test.


### Four native host metrics pipelines

`ansible/playbooks/otel-host-metrics-canary.yml` stages and exercises metrics-only copies of the actual agent/cluster configurations. Four native host agents send standard OTLP over mTLS to a private-WireGuard-bound temporary Collector gateway and an isolated native Prometheus OTLP backend. It tests persistent queues across agent restart during gateway outage and verifies raw pre-restart samples after recovery. Cleanup stops all agents first, then gateway and backend, verifies no owned process survives, and removes temporary TLS files. There is no production ownership switch or log ingestion in this test.

Pinned Collector 0.164.0 emits a generic "Dropping data" log on shutdown Send errors even when the persistent queue retains those requests for replay. The canary separately requires exact version/signature and matching recovered in-flight request counts; generic/permanent errors, missing replay, storage errors and memory refusals are never waived. Preserve the original logs privately and do not substitute this runtime accounting for canonical historical verification.

Generate new canary requests with `scripts/otel-host-metrics-request.py`, not by copying old target aliases or recomputing their observation timestamp. It checks a ≤900s scrape contract, all host config fingerprints, official image receipts and binary SHA256. Required arguments are `--bundle`, `--binaries`, `--prometheus`, `--exporter-path` (the already verified host-source canary executable), `--backend-ip` (an existing private WireGuard address), and a new private `--output`. The remote prepare phase independently checks observation freshness and content binding. A subsequent hardening sets native cgroup `MemorySwapMax=0`; do not retroactively claim this setting was measured in an earlier receipt.


### Native historical Query validation

`cmd/native-anchors` selects finite samples from three distinct actual host-metric families in a normalized block with already established external Thanos context. It refuses to invent context for an unlabeled snapshot. `scripts/otel-history-native-compat.py` verifies the transfer archive and pinned production Thanos executable, runs stock native index issue checks without repair, and queries isolated Store/Query. All labels, float bits and sample timestamps must match. Full canonical verification is still mandatory and independent.

`ansible/playbooks/otel-history-native-compat.yml` executes only on the explicit healthy test inventory host. `scripts/otel-history-query-job.py` may follow completed metadata receipts sequentially in private workspaces; it stops on failure, preserves originals/evidence, and never publishes or certifies the entire migration. Missing snapshot external-label context remains a reported blocker, not an exception silently waived by the worker.

## Bounded parallel export and contiguous-series import cache (2026-11-01)

`export --export-workers N` accepts1..16 (default1). A single ordered reader
computes the unchanged full canonical-v1 digest and assigns stable batch numbers.
Immutable batches pass to a bounded worker pool for protobuf marshal, gzip and
file SHA. At mostNqueued+Nactive batches+the producer's current batch exist;
workers reuse private gzip compressors. Existing5,000point/32MiB protobuf limits
remain. Worker failure/budget overrun prevents any success manifest; bounded
already-in-flight batches may finish, so filesystem reserve must cover them.

Scheduling does not alter the batch protobuf bytes, gzip bytes, filenames,
file digests, counts, NaN/stale bits or final canonical digest. `--resume` validates
*every* existing batch against the original decoded protobuf before reuse,
including sparse parallel outputs. It never accepts a completed manifest for
rewriting, mismatching content, invalid gzip, links or a fake partial proof.

Import caches only consecutive identical **validated** metric-name/attribute
vectors and the upstream appender's SeriesRef. It resets at every batch/appender
boundary, including mutable-Head flushes. All per-point flags, time bounds,
values, stale restoration and full final canonical verification still execute.
Invalid/changed attributes always take the original validation path. There is
no unbounded all-series cache or new concurrent native TSDB writer.

On socrat-0 a synthetic500,000point benchmark (12CPU cgroup ceiling) measured
export1worker1.780s vs16workers0.334s (~5.33x). Full synthetic import including
native writes and canonical verification measured2.101s uncached vs1.675s cached
(~1.25x). These are **not full-history ETA/acceptance**, and native compaction,
ordered digest calculation and source traversal still impose serial costs.

The running queue was moved via guarded SIGINT of **only its own history
controller/export**, preserving the completed original inventory and temporary
batches. The new `--resume-export` mode accepts only the exact first source,
export phase,0completed blocks and no import/native output. Interrupted receipt
and logs remain. Only an incomplete last predecessor transport batch may be
moved to private quarantine, never source history; the real handoff needed none.
The global importer lock now covers startup, validation, cleanup and resume too.
New service: `otel-history-tail-parallel-20261101.service`,16CPU/9GiB/zero swap,
GOMAXPROCS16/GOMEMLIMIT6GiB, one importer. A tested import-cache binary was later
atomically promoted for subsequent subprocesses; the executing export inode,
controller PID and checkpoints were not modified/restarted for that promotion.

### Operator-selected50-worker export (2026-11-01)

Export worker bound is now1..50; default remains1, and CPU parallelism is not
raised above16 just because more workers are requested. socrat0-fast fresh queue
launches explicitly select50 while retaining16CPU/9GiB/zero swap and Go16/6GiB.
For an already-running controller with cached16arguments, a protected root-owned
0600 `export-worker-override.json` in its fixed private state directory sets50
for subsequent export subprocesses. Applies only to root on socrat-0 and the
approved history workspace. Unknown schema/keys, trailing data, wrong owner,
public permissions, symlinks and out-of-range settings fail closed. No override
means ordinary CLI semantics. `export --show-export-workers --source WORKSPACE`
reports effective settings without reading samples or starting an export.

The active import was **not interrupted or parallelized into50importers**. Its
executing binary inode and controller PID were retained during atomic promotion.
New binary SHA: `ca3cf860b7735459fe5097caa5330e8f69478dc189b12a4d236b8dc2388422e0`.
Actual setting check: requested16/effective50, GOMAXPROCS16, no samples read.

50workers have **no demonstrated stable speed advantage** here. Repeated16CPU
synthetic benchmark means:16workers0.32081s,32workers0.32062s,50workers0.32722s;
50runs range0.300..0.360s. Initial12CPU test was slower with50. Do not equate
worker count to cores, claim an ETA gain, or reduce exact verification to fill
otherwise idle CPU. Setting50 follows the explicit operator request, not a claim
that50is the measured optimum. Maintained tuning playbook:
`ansible/playbooks/otel-history-export-workers.yml`.

## Import pipeline, asynchronous canonical digest and verified native resume

2026-11-01: CLI import now uses up to16bounded prefetch lanes. Each lane has at
most one ready and one decoding batch; the **single ordered consumer** still
performs every per-point check and upstream TSDB append. Gzip/protobuf decoding
and manifest SHA checks run concurrently. Cancellation drains/waits all workers;
CRC errors, oversized protobuf, invalid names, nonregular files and SHA mismatch
fail closed. No unordered appends, skipped validation or concurrent mutable Heads.

The unchanged canonical byte stream is hashed by one sequential SHA256 goroutine
using four fixed256KiB buffers, overlapping hashing with reading/OTLP assembly.
This does **not** change the legacy digest scheme or weaken full comparisons.
Native compaction can process up to4independent groups using separate upstream
compactor instances. Combined disk projection is reserved per wave; memory
projection limits fan-out and disk-pressure falls back to serial, never a lower
20%reserve. Inputs and failed outputs remain private/retained.

Synthetic500k-point full import on socrat-0: prefetch1=1.96262s,4=0.72912s,
16=0.45394s (~4.32x vs1). These are not whole-history ETA/retention acceptance.

`verify-import-prefix --source EXPORT --block OLD_IMPORT --output PROOF` performs
**read-only full comparisons** of closed native shards against the exact
contiguous original OTLP batches. The newest live checkpoint is excluded;
checkpoint counts alone are not trusted. Counts/canonical SHA/NaN/stale bits must
match, source manifest SHA binds the stream, and native size/mtime/device/inode
inventories bind the closed shards. The prefix proof is exclusive0600+fsynced.

`import --resume-import-proof PROOF --source EXPORT --output NEW_PRIVATE_DIR`
rechecks source manifest and native inventories, adopts only proven shards, skips
only the exact proven batch prefix and restores count/stale counters. Unproven
later shards/partial Head remain in the **old** output and are not adopted; that
small suffix is reconstructed. Final native canonical verification still covers
**all** original samples. Proof/manifest/shard mutation, wrong ordering, changed
counts and corrupt source/native samples fail rather than silently resume.

Actual first-block handoff verified **147closed shards/367,500,000samples** against
73,500original batches (502s read-only proof while old import continued), then
SIGINTed only the old migration controller/exporter. The verifier joined the
existing migration cgroup to share16CPU/9GiB instead of adding an unbounded job.
New guarded queue `--resume-import` writes `restored-fast`, keeps old `restored`
including unadopted/failed artifacts, and never redoes source inventory/export.
New service: `otel-history-tail-pipeline-20261101.service`; same16CPU/9GiB/swap0.
First real observation **14.09CPU cores vs~1.55before**, no OOM/limit/throttling
observed, checkpoint430,000,000samples including adopted prefix. Not a promise
that ordered final checks always saturate16cores. Active converter SHA:
`c2b4fd258ebffb1f31d9caec4c05cbc803dce52b0365fb69f7efa74ba411a077`.
