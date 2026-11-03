# LMS single-node failure resilience

## Deployed contract (2026-11-03)

The previous single PostgreSQL Deployment used a `local-path` PVC pinned to
`socrat-3`; node eviction moved the web pod but could not move that database's
files. This has been replaced **for production traffic** by CloudNativePG:

- operator chart **0.29.1 / operator 1.30.1**, two controller replicas with
  required hostname anti-affinity on socrat-0/1;
- PostgreSQL **17.11**, digest-pinned CNPG image, **three instances** with required
  hostname anti-affinity on **socrat-0/1/3**, excluding reserved socrat-2;
- local independent data volumes, not three pods sharing one NFS directory;
- quorum synchronous replication `ANY 1`, `synchronous_commit=on`,
  `dataDurability=required`, `failoverQuorum=true`, failover delay 30 seconds;
- application endpoint `lms-ha-rw.lms.svc.cluster.local:5432`, application role
  `lms`, TLS **verify-full**; live connection verified TLS 1.3;
- 256 MiB requested / 512 MiB maximum per DB member, 64 MiB shared buffers,
  max_connections 60. Operator replicas have 256 MiB memory ceilings.

A healthy primary plus one synchronous standby can continue acknowledging
writes after one member fails. Required durability intentionally blocks writes
if the synchronous quorum is lost; it must not be relaxed automatically just to
make a dashboard green. Replication is not backup and three nodes are not three
independent sites. This is not a promise of zero interrupted requests, zero
recovery time, or availability after two member/site failures.

## Web worker constraints and storage

The web process remains **one replica**: its submission queue is in-process, and
startup recovery marks queued/running work interrupted. Two web replicas would
be unsafe without redesigning job ownership/queueing. `Recreate` prevents
voluntary rolling-update overlap. It is not distributed process fencing under
arbitrary asymmetric network partitions. Running checks can be interrupted by a
worker loss and may need resubmission; exactly-once execution is not promised.

Node not-ready/unreachable eviction tolerations are 60 seconds instead of the
default 300. Expected web recovery still includes node detection, scheduling and
startup. No full-node outage RTO measurement has been performed in production.
The pod can use socrat-0/1/3, not the reserved etcd/VPN node.

Source inspection confirmed the current runtime is PostgreSQL-only; `/data` was
an unused SQLite-era mount. Production sets `persistence.mountInApp: false`:
the old `lms-data` NFS PVC is **preserved but not mounted** by the web pod.
This removes a scheduler/startup dependency on the NFS server for LMS. Course
assets remain inside the image. Other services (OIDC, ingress, VPN, etc.) have
their own availability boundaries; this change does not make the whole homelab HA.

## Migration and evidence

1. Created an isolated `lms-ha` cluster without redirecting the old application.
2. Made an AES256-encrypted logical backup on independent NFS storage. Plaintext
   dumps/fingerprints stay in private tmpfs, never in Git or the operator output.
3. Decrypted that archive and restored into the isolated target using TLS.
4. Tested failover on the isolated copy: cordoned the primary node, gracefully
   deleted its pod, waited for promotion, checked an acknowledged marker and a
   new write, then uncordoned the node. **43.65 seconds** to promotion/write probe.
   This was not a power-off or network-partition experiment and was not a test
   of live LMS HTTP failover.
5. Stopped the sole web writer for final copying. The first strict check rejected
   locale-dependent fingerprints; the app was resumed on the old DB rather than
   bypassing verification. Fingerprints now use explicit `COLLATE "C"`, avoid
   printing generated SQL and compare canonical table contents.
6. Repeated the freeze, encrypted dump, decrypt, atomic restore and exact logical
   fingerprint check. Source and target SHA256 matched. No queued/running
   submissions were present before the migration window.
7. Switched the runtime DSN while the writer was stopped; resumed LMS with the
   HA CA mounted; verified actual TLS, lesson/authenticated synthetic-session
   traffic, database spans, Tempo and Loki/Grafana.
8. Fixed a pre-existing Helm `lookup` credential ownership trap exposed by the
   cutover: Argo rendering cannot rely on live Secret lookup. `lms-db` data is
   runtime-managed, ignored under `/data`, with `RespectIgnoreDifferences=true`.
   A resync had removed the DSN before startup; credential keys were recovered
   without printing values, and the ownership fix prevents a repeat.
9. Scaled the old PostgreSQL Deployment to **zero**; retained its disk and old
   credential in the Secret. The old DB must not continue accepting stray writes.

Evidence:
- `deploy/monitoring/migration-evidence/lms-postgres-staged-failover-20261103.json`
- `deploy/monitoring/migration-evidence/lms-postgres-final-copy-20261103.txt`
- `deploy/monitoring/migration-evidence/lms-ha-post-cutover-browser-20261103.json`
- `deploy/monitoring/migration-evidence/lms-ha-acceptance-20261103.json`

The exact pre-cutover fingerprint was
`80a16f17bc94a6d196206b1967d5047193f548edae9f678e7726e25ee64e670c`.
Normal live sessions/submissions legitimately change data after cutover.

## Backups and residual DR limits

`lms-database-backup` runs **every 6 hours UTC**, concurrency forbidden, with a
five-minute deadline, placed on socrat-0/1 rather than the small reserved VPS or
the unstable worker. It dumps the current primary over verified TLS, validates
the archive, GPG-encrypts using a random key from `lms-backup-key`, decrypts and
compares the result before declaring success. This routine validates archive
integrity; it is **not a fresh database restore test on each run**. The migration
included an actual restore. Scheduled archives are retained for at least seven
days; migration archives are not automatically pruned.

The backup PVC is NFS on socrat-0, distinct from the former primary's disk but
**not off-site**. An NFS-node outage can delay backups, although the production
web pod/DB no longer need NFS to run. The backup key currently resides in the
Kubernetes Secret/etcd: secure off-cluster key escrow and an off-site archive
copy remain required for whole-cluster/site disaster recovery. Never assume
that encrypted archives alone survive loss of their only decryption key.
Catastrophic loss of all replicas can lose changes since the last backup;
there is no configured external continuous WAL archive in this rollout.

New DB volumes use `lms-db-retain` (`Retain`, WaitForFirstConsumer). The old
legacy PV and the first staged HA PV, allocated before that StorageClass was
applied, were explicitly patched to Retain. Do not delete PVCs to repair a
Pending pod. Local-path size requests are not hard disk quotas; keep node disk
reserve monitoring enabled. Neither old data nor migration backups have been
removed.

## Alerts

`lms-availability` is evaluated in the existing monitoring stack (no second
collector or sampler). It alerts on no available web worker, fewer than two
ready PostgreSQL members, fewer than three for five minutes, and an overdue
backup. Rules use already-ingested kube-state-metrics; the optional CNPG
PodMonitor is not relied upon because the legacy Prometheus scrape selector is
retired. All four rules were verified in the live rules API with health `ok`.
Alert evaluation is verified; end-to-end notification delivery has not been
force-triggered during the migration.

## Operations and rollback

```sh
ssh socrat-0 'kubectl -n lms get clusters.postgresql.cnpg.io,pods,pvc'
ssh socrat-0 'kubectl -n cnpg-system get pods -o wide'
ssh socrat-0 'kubectl -n lms get cronjob lms-database-backup'
helm lint charts/lms-database-ha
helm lint charts/lms -f deploy/lms/values.yaml
```

`lms-ha-prepare-credentials.py` is run via stdin on the administrative host:
`ssh socrat-0 python3 - < scripts/lms-ha-prepare-credentials.py`.
It only generates missing random credentials in Kubernetes, never in Git,
files or stdout. Preserve `lms-db` runtime credential data during all syncs.

`lms-ha-copy.py` and `lms-ha-failover-verify.py` are guarded **staging/migration
utilities** and deliberately refuse once the app uses the HA endpoint. They
must not overwrite the live HA database or be used to recreate a test from
stale production data. The copy utility also refuses a final copy while any
web pod exists or desired replicas are nonzero.

The old PVC is a rollback checkpoint, **not a current replica**. Once HA has
accepted writes, merely switching the DSN back would lose new sessions,
progress and submissions. Rollback now requires a maintenance freeze, a fresh
verified backup of HA, restore/verification into the legacy or another isolated
cluster, then an explicit endpoint switch. Never restore an old snapshot over
live HA or run both old and new databases as independent writers. If failover
cannot establish a safe primary, investigate fencing/quorum; do not manually
promote a disconnected old primary or force-delete unknown-running pods.


## Unplanned repeat node loss after cutover

At **13:06:18 MSK** on 2026-11-03 socrat-3 independently became NotReady again.
This was not induced by the verification. PostgreSQL primary `lms-ha-2` on
socrat-1 and its synchronous standby on socrat-0 continued acknowledging a
separate-schema write probe. Kubernetes automatically replaced the web pod on
socrat-1; replacement readiness was **13:07:29 MSK**, **71 seconds after the node
became NotReady**, with no manual pod relocation. This measures those two
Kubernetes transitions, not the complete user-visible HTTP outage.

A new authenticated real-browser lesson request then returned 200 and exported
a 39-span browser/backend/database trace with correlated Loki logs. The marker
was read successfully and its temporary schema dropped. See
`lms-ha-real-node-loss-20261103.json` and
`lms-ha-real-node-loss-browser-20261103.json` in the migration-evidence directory.

At final acceptance the cluster was **degraded but serving with two DB members**;
its configured third member is still on socrat-3. The node's recurring outage
root cause is not established by this work. The 44-second primary failover test
was staged; the subsequent real incident lost a standby and the old web node,
not the active primary. Do not conflate the two experiments.

The post-node-loss CPU functional canary also completed: 42 real lesson GETs in
20 seconds, nonzero function stacks from the replacement worker, synthetic
identity deleted. See `lms-ha-cpu-profile-after-node-loss-20261103.json`.

Canary administration now selects a non-terminating Ready pod on a Ready node,
not blindly `exec deployment/lms` while an unreachable old pod is terminating.
Remote Python cleanup programs have syntax regression tests as well.
