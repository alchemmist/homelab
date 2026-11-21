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
