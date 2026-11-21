# Thanos 5m — active production data

**Do not delete or reset `thanos-5m-s1-candidate`.** All three 5m roles use
its `active/` subdirectory on NFS served by 0. The Store mounts it read-only.
The original directory on 1, the independent cold archive there and pilot
quarantine are not current data. Never revert to stale local storage after
new writes. Loss of NFS server 0 is not covered by this drill.

After cascade scheduling was suspended, the previous job finished and the
raw compactor was Ready. Both writers and the Store stopped. A read-only
source was archived and independently extracted; all 12 paths (10 files,
3,986,362,815 bytes) matched by type/size/SHA256. The helper was unmounted
before the three shared singletons started on 0. The strict 5m query returned
900; nonexistent-store and raw-only controls were empty. Raw, hourly, current
queries and both Store/Compactor readiness passed. Live Prometheus reported
one allocation series (3,986,415,616 bytes on 0) and fresh NFS available bytes
within 0.01% of host df. Existing otel-cluster pod discovery owns this scrape.
Size is sampled asynchronously; unavailable/stale size is omitted, never
reported as zero. The scheduled 23:30 UTC cascade succeeded in 6 seconds;
raw compactor restored. It was not proof of a new inbound 5m block.

## Historical preflight (not cutover instructions)

Before cutover, production on node 1 used `/var/lib/socrat-thanos-5m`. Neither
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

## Pre-power-off gate (2026-11-20 UTC): NO-GO

The migration itself is accepted; these are independent drill prerequisites.
All six nodes Ready. API through 0 passed livez/readyz including etcd. Three
voters report a leader, no learners, 0 leader and no increase in failed proposals
in 10m. Direct peer TCP passed 0→2 and 2→0 at their advertised addresses.
Recent etcd snapshots on both survivors (21:00 UTC). DNS from n8n on 5 passed
3/3 against the VIP and each CoreDNS endpoint on 0 and 3. Existing Alertmanager
route and Prometheus discovery are present; no active silence matched node
readiness. Hold time is 900 seconds, then grouping and delivery. Real Telegram
receipt is a drill measurement, not a preflight substitute.

The old/new Loki and Tempo queries and old/new Pyroscope CPU queries passed
on 0. However the cluster OTel **metrics** queue reached ~99% of 256 MiB and
enqueue failures increased, despite subsequent drainage. Queue-full messages
also predate the storage cutover. Do not assume causation, complete capture,
or durable alert delivery until ingestion is stable across a representative
window (no new enqueue failures, fresh six-node KSM series). Do not drop queues.

The live critical PostgreSQL primary is on 1, replicas Ready on 0/5. Not the
out-of-scope experimental LMS DB. Confirm failover readiness and no maintenance
with its owner; do not promote or alter it as part of this preflight. External
Authentik and the Grafana login path return HTTP 200 without old cookies;
real fresh login/MFA with an authorized user still required. Confirm independent
physical power-on (laptop battery; a smart socket is not proof). No drill or GO.

Other node-1 residents: generic stateless controllers/gateways can reschedule;
Traefik/CNPG controller, cats and socrat-home have surviving siblings. Trivy
uses NFS on 0. The NFS provisioner may itself relocate; existing mounts don't
require it. Per-node DaemonSets/peer identity are not promised migrations.
Certification runner's host Docker socket and local certification DB need
explicit scope. Keep the existing two Query/probe copies for this drill; this
is not a general replica policy. On 0, memory requests were ~81% of allocatable;
5 had ~54% memory request headroom. Do not count 4 as recovery headroom.

Proposed timing for operator confirmation: allow 5m for portable singleton
recovery; check alert at 15m + grouping, stop if no receipt by 20m. Abort sooner
on loss of quorum/API, risk to data, failed critical DB recovery, or loss of
observability. No preliminary drain. Only operator may power off after a separate GO.
