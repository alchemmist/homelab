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
