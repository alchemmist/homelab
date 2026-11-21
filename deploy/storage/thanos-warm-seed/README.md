# Workshop seed, not a live writer switch

The `thanos` Application serves a new private TLS S3 API from the retained
`socrat-1` volume; `workshop-s3/` is separate from the 5m seed and tests. No
Ingress, production Query, sidecar, Compactor or cleanup job points to it.
A dedicated immutable `thanos-warm-root` Secret was created once; do not
regenerate on upgrade. Keep credentials and cert-manager recovery material in
the approved backup path. Single-drive RustFS has no parity or redundancy.

`thanos-workshop` was created through the authenticated TLS API. The seed Job
on 0 mounts the raw host directory read-only and receives only 4h, exact-key
HEAD/PUT/GET capability URLs (no list, no DELETE, no admin key). A short-lived
signer on 1 creates those in a private exec pipe. Do not print the capability
Secret. The worker validates the service certificate against the private CA,
rate-limits uploads to 24 MiB/s, publishes meta.json last, never replaces an
existing object and reads every object back over HTTPS to compare SHA-256
against the source. Compared data includes chunks and indices, not just meta.
The job fails on errors; no production dependency on the Job succeeding.

`start.py --run` starts an explicitly requested batch in context Socrat. A
repeat spends time hashing existing objects but refuses mismatches. Any failure
or source block changing/deletion mark during a run requires review, not deletion
of existing objects. A partial block lacking meta.json is not accepted history.
Completed active blocks only: root-level markers and state, existing marked
blocks, concurrent changes and partials require final reconciliation. This
is intentionally *not* a bucket mirror or a verified complete backup.

2026-11-21: `warm-raw-seed-8262c4fd` submitted 121 files / 49,808,643,568
bytes. First block upload and downloaded content verification observed. Check
`kubectl -n cattle-monitoring-system logs job/warm-raw-seed-8262c4fd` and Job
completion before claiming the whole batch. No worker logs contain URLs or
credentials. Job and its capability Secret are garbage-collected after TTL;
retain acceptance evidence separately. Keep source directories and TSDB/WAL.

Before cutover: reconcile the delta and deletion markers at a stable writer
boundary, verify an independent restorable copy, and strictly compare queries
from an isolated destination Store with the old Store. Create bucket-scoped
production identities and CA-only trust for each role (no root in consumers).
The current filesystem cascade reads local block files. Adapt and verify its
1h copy, coverage checks and deletion handling against the new bucket before
activating a new compactor or retiring old data. Separate 5m history must not
be merged blindly. Verify the first natural new shipper upload, catch-up and
hourly cascade, then plan a distinct storage reclamation window.

## Live reconciliation and read gates, 2026-11-21 18:02–18:11 UTC

* First batch completed in 55m: 121 files, 49,808,643,568 bytes, manifest digest
  `032f8fd38e5cd0ce045635cfd7c5284d15364a7e95f226bae89e8c7abb528e72`.
  `start.py --run --delta` added the two newly completed blocks in
  `warm-raw-seed-74f60ab9` (9 files, 2,194,402,123 bytes; SHA-256 readback).
* Four previously seeded blocks became compaction inputs. A live source mark,
  same external labels/resolution, covering time range, source ULID inclusion,
  and an independently readback-verified replacement were checked before copying
  the existing marks. Replacement `01M7ZM0RM7VYX7YXF18KSKV0SM`; marker-only
  Job `warm-raw-seed-da3b8a77`. No new source deletion decisions or object
  deletes. Do not copy marks for absent blocks. `delta.py`: 118 active files,
  zero missing, extra active, or size mismatches. This is a moving snapshot;
  `delta.py` alone does not prove content integrity.
* `bootstrap_reader.py` provisions a separate read-only/list-workshop identity
  with verified `mc`, private TLS and no root credentials in Store/Query.
  `compare.py` uses two separate single-endpoint Queries, no dedup, no partial
  answers. `warm-workshop-parity-rpl7s` after the marker pass matched all 11
  nonempty historical windows of `up` (7 with 5m permitted, 4 raw-only).
  This samples real queries; it is not exhaustive series validation.
* `bootstrap_reader.py --run --synthetic-hour` and `hour_probe.py` use a
  **different bucket and reader** and only synthetic output of the earlier
  block drill. Actual Thanos replicate on node 3 pulled the 1h block over TLS
  from node 1, skipped 5m inputs, verified index/chunk/meta SHA-256 on 3.
  `warm-hour-pull-rkmb5` completed. Destination was emptyDir, NOT the production
  hour shelf. No production compaction, writes to the hour shelf, or change to
  the live shipper. Implement production copy/confirmation/retention coordination
  before cutover; do not assume a passing transport drill is a cascade rollout.

## Production switch, 2026-11-21 18:18 UTC

The sole Prometheus on 0 now ships over verified TLS with a workshop-only
Put/Get/List identity (no Delete); it no longer mounts the old raw directory.
Same retained TSDB PVC UID `97a31a0a-b498-42a6-be10-1cab44673c41`, WAL replay
and all 17 previously journaled block IDs retained across the operator restart.
Never reset the journal to force a test upload. During restart the fresh Query
briefly had no data; do not infer uninterrupted scraping from historical parity.
Raw Store moved to 1, read-only workshop identity. Production strict Store-only
controls after cutover: raw `up[5m]` at 1795132800: 98 series/hash
`e9c8e124251d9191`; 5m-permitted per-job count at 1793577600: 8 series/hash
`fc52a22761d5b465`; nonexistent Store negative controls empty. Single workshop
Compactor on 0 uses its existing local work directory, S3 bucket-scoped identity
and a 48h physical deletion delay, with time-based retention disabled for now.
Existing marks can age out on the normal compacted-block cleanup path. This is
not a promise to retain *redundant* compaction inputs forever. A transient S3
refusal on pod startup cleared; initial metadata sync then succeeded. Check
`thanos_compact_halted`, compaction passes and object pressure continuously.

The regular `thanos-cascade` now runs on 3 at :30 (no service-account token,
no legacy scaling call, read-only S3 identity). It stages only eligible complete
unmarked 1h blocks, checks every downloaded SHA-256 by rereading disk, fsyncs
then atomically publishes with no replacement. Existing conflicting blocks fail
closed. It does not expire raw/5m data or delete S3 objects. In the isolated
real two-pass `s3-hour-copy-check-dqdz7`, index, chunk and metadata matched the
source fixture SHA-256s. A zero-candidate scheduled run does not prove a real
hourly block arrived. Keep the legacy 5m reader on NFS; old raw directory is
now a retained recovery copy (not blank space or a live destination).

`warm-natural-shipper-ngvx2` watches the production journal for up to 3h from
cutover and verifies the first new local TSDB block vs the S3 object metadata,
index and chunk bytes. Its deadline/Ready state is not evidence; inspect the
verification container log and Job completion. Never count the seed as a new
shipper upload. If this gate fails, diagnose before the 12h local TSDB buffer
expires. After any new writes, rolling back just a Secret or values file is
not a lossless rollback: preserve both stores, account for journaled ULIDs and
reconcile the delta first. Do not delete the old archive, shrink retention, or
turn on age-based pruning merely because these rollouts are Healthy.
