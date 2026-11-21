# Thanos 5m drill: staging, NOT active production storage

Production on node 1 still reads/writes `/var/lib/socrat-thanos-5m`. Neither
raw storage on 0 nor 1h storage on 3 is being migrated. `thanos-5m-s1-candidate`
is RWX, Retain, NFS served by 0: three distinct existing roles need simultaneous
access; this is not three replicas of one writer. Requested 16 GiB is not a
hard quota. The pilot did not demonstrate loss of 0 or crash safety.

A source-read-only online seed of the completed block is in `warm-only/`.
Source/target stream checksums matched for 10 files, 3,986,362,815 bytes. An
earlier 96 MiB copy helper was OOMKilled; its incomplete tree is isolated in
`aborted-preseed/`. Neither tree is a production bucket root or a cold backup.
Retry used periodic flush/fsync, bounded throughput and a 384 MiB cap.

Production acceptance reference: instant query `sum(count_over_time(up[1h]))`
at Unix second `1792785600`, max_source_resolution `5m`, partial_response=false,
`storeMatch[]={__address__="thanos-store-5m.cattle-monitoring-system.svc.cluster.local:10901"}`
returned exactly 900, no warnings. Unknown-store and raw-only controls returned
empty. A loopback-only Store+Query pair on node 0, same Store image digest,
no Service, credentials, or production labels, mounted only `warm-only` via
the candidate read-only and independently returned 900 (raw-only empty).
This is a data read proof, not proof that the live roles have migrated.

## Gates before cutover

* Suspend the hourly `thanos-cascade` via its owner. Let any existing Job
  finish; verify the raw compactor is restored. Do not execute a synthetic
  cascade: it uploads blocks and marks data for deletion on multiple tiers.
* Quiesce both 5m writers: HTTP shelf (upload, finalize, mark) and 5m
  compactor (compaction/marker processing). Store Gateway reads blocks but
  currently has a writable mount; exclude it from the cold copy window too.
  Preserve hidden/staging files and markers; never treat matching metadata
  or the query alone as a full copy. Retain original; verified cold restore,
  complete path/size/hash reconciliation, unmount helpers before restart.
* Move only 5m roles to shared storage. Preserve current paths, priorities,
  singletons and consistency/deletion delays. Query, raw and 1h stay online.
  Do not expose the parent of the staged trees as the bucket.
* Correct the pressure-deletion input: `cascade.py::disk_free_bytes` currently
  samples **socrat-1 /** for the 40 GiB floor. It must measure the actual NFS
  backing filesystem (verified on 0: `/srv/k8s-nfs` on root ext4) before the
  cascade resumes. Check the pressure query on live Prometheus. `thanos-disk`
  measures the old host directory; don't report it as the new shelf or double
  count the retained copy. Validate target size reporting and dashboards.
* Check `/-/ready`, discovery, historical query plus negative controls, then
  compactor status and next naturally scheduled cascade. A successful idle
  run is not an inbound block upload. No blind rollback after new writes.
