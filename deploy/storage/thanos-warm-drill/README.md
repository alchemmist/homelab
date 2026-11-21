# Warm archive on socrat-1: isolated block acceptance

The job mounts only `thanos-warm-s1-candidate`, creates a fresh `drill-<pod UID>`
directory and uses loopback Store/Query endpoints. No Service, production block,
credential, Store discovery or change to production retention. It is an explicit
one-shot experiment, not an Argo hook. The scratch PVC directory survives Job TTL;
do not use it as a production bucket or delete the containing PVC.

Render with `python3 deploy/storage/thanos-warm-drill/job.py`. To repeat in the
Socrat context, inspect the rendered JSON then submit with `kubectl create -f -`.
Watch the generated Job in `cattle-monitoring-system`; inspect `upload`, `compact`,
`project`, and `verify` logs. A Job with no successful `verify` result is not accepted.

2026-11-21 16:36 UTC: `thanos-warm-block-drill-nmqfh` completed on socrat-1.
A 28-day synthetic gauge generated 336 raw blocks. Thanos v0.42.4 uploaded them
to the local FILESYSTEM bucket; the one-shot Compactor produced five active 5m
blocks and one 1h block. Each test Store saw **only** its resolution (hard-linked
synthetic files, no raw fallback). Both strict queries returned the expected 7 and
both raw-only negative controls were empty. This tests format, downsampling and
readback, not production-scale capacity, the 0→1 network or transfer to socrat-3.

Next gate: test the selected authenticated network transport from a disposable
shipper on 0 to an isolated bucket on 1. Interrupt only the disposable path,
continue ingesting numbered samples, restore access and compare timestamps,
values and block inventory through the test Store. Do not change the live
sidecar or retire its local bucket on the strength of this filesystem test.

## Cross-node outage and migration safety gates

`network.py --run` creates only uniquely named disposable clients on 0 and a
private RustFS endpoint on 1 (new subdirectory of the candidate). It uses
one-use credentials, a namespaced ingress policy, no production data, no
public Service or live Store discovery. Accelerated 30s blocks exercise the
real Prometheus/Thanos sidecar shipper. Only the test backend is stopped;
scrapes on 0 continue. Acceptance requires a real shipper upload warning,
consecutive numbered source samples and an identical range vector (including
timestamps) from **only the remote Store** after restart. Not a long outage,
production durability guarantee, TLS validation or a live-scale load test.
If manually interrupted, inspect resources with the exact `warm-drill` run ID;
do not delete the retained PVC. Production needs durable keys and separate
bucket-scoped identities, not the disposable credentials used in this test.

2026-11-21, `warm-net-c95f5832`: 36 numbered scrapes accrued during the
outage; all 73 samples through the comparison cutoff matched after recovery.

`inventory.py` is a read-only census; its summary hash is **not** a checksum
of file contents. In the 16:44 UTC inventory, 7 active raw blocks, 3 marked raw
blocks and 7 active 5m blocks were in the workshop. The 5m shelf and the 1h
shelf each had 1 active block. Workshop 5m `01M70GFT8JHAMSXFECR2YZCQ68` and
shelf 5m `01M6Z6FB66G4QN1JA5YGWDQBV1` have identical external labels,
different ULIDs, 144 hours of overlap and 114 common compaction source IDs.
These are distinct archives, not safe input for an undifferentiated merge.
Preserve separate namespaces/buckets, deletion marks, and the existing query
semantics. Never resolve an overlap by deleting one side on sight.

`copy_five.py` renders a Job that mounts only `active/` of the live 5m shelf
read-only, creates a unique destination, rate-limits the copy, compares every
file by SHA-256 including markers, and rejects changes to the source inventory.
A successful seed is **not a synchronized current writer**. `read_seed.py POD_UID`
renders a read-only historical acceptance Job for that seed. There is no
production Store discovery, Compactor or cascade attached to the seed.

Before switching the single live sidecar: provision production S3 and scoped
credentials, pre-copy the workshop to its separate destination, establish an
independent restorable backup, then reconcile delta/markers at a stable writer
boundary. Preserve the TSDB, WAL and shipper journal: changing the endpoint
does not make a shipper re-upload all previously shipped blocks. Verify source
vs destination content hashes, Store inventory, strict historical queries and
the first natural new upload. Keep the original stores available and track
post-cutover writes; after new writes, rolling back a Secret alone is not a
lossless rollback. Do not remove source directories or PVCs at cutover.

Live 5m seed, 2026-11-21: `thanos-five-seed-f6gpw` copied 10 files,
3,986,362,815 bytes to `seed-five-d616060a-86fd-4834-b892-caac18bd3eda/tree`
on `thanos-warm-s1-candidate`. File manifest SHA-256:
`3569fc3feac7f8631f7dc65a24fbaa43812d518be1f3c73e7b0e963d2869cb06`.
`thanos-five-seed-read-6szzn` read only that copy: 5m control = 900 at Unix
1792785600, raw-only empty. Original NFS remained live and unchanged by both
Jobs. This is a validated point-in-time **seed of the 5m shelf only**, not a
backup of raw, the Prometheus TSDB or the 1h shelf. Do not put a writer in the
seed directory. A final cold delta/reconciliation is still required.
