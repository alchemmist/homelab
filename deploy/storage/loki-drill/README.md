# Loki production storage: shared PVC on socrat-0

**Active production data. Do not empty, replay a delta onto, or delete
`loki-s1-candidate`.** Despite its historical name this is the live Loki PVC.
The singleton now runs on socrat-0 with `storagePhase: shared`. The retained
hostPath on socrat-1 is stale. Do not revert to local after new writes.
The NFS server is on 0; this covers the drill for loss of 1, not loss of 0.

After #209 stopped the sole writer, a 59,269,120-byte delta was sent directly
from 1 to 0. Both archive and inventory checksums matched. All 37,242 target
paths matched the stopped source, including WAL, index, chunks and compactor.
Copy workers exited before #210 started the sole writer. Post-start checks:
original log matched its private timestamp and body hash; a real log newer
than pod startup was queried, collector queue drained to zero, mTLS `/ready`
returned ready, and compaction and retention each reported a successful pass
after startup. The TCP readiness probe alone was not sufficient. Archives
and earlier preseed quarantines are preserved; do not merge them into Loki.

## Historical staging notes (not current operational instructions)

The target is single-writer, NFS on socrat-0, not protection from
loss of the NFS server. Requested capacity does not impose a hard directory
quota. Both the bound PV and PVC report ReadWriteOnce; this does not fence a
second writer. Require one replica, Recreate, and verified writer shutdown
before remounting, as in the sequential two-node pilot. Preserve 336h global retention, stream policies, mTLS, ruler and existing
compactor marker paths; no change to other storage consumers.

The production Loki image digest was tested in two disposable, sequential pods
with UID/GID 10001 and this same mount. No Service, service token, live labels,
TLS keys, log data or production ruler configuration were used. Ingress/egress
were denied; test OTLP/read/flush used loopback. One synthetic line was written,
queried and flushed on node 1, then read on 0; a second OTLP write and query
succeeded there. Only synthetic files were removed. This was not a crash or
load test, nor an acceptance of production compaction behavior.

`incomplete-preseed/` is deliberately NOT the production directory. An online,
rate-limited, read-only-source copy of `loki/chunks` only reduces later downtime.
Never point Loki at the warm tree or treat it as a backup. At cutover require:

1. Independent protected backup and verified restore. Check actual bytes and
   inodes, source workload identity, NFS PV/claim UID and gateway queue headroom.
2. Exactly zero production writers before final sync. Reconcile additions,
   updates **and removals** with the stopped source; include the entire `loki/`
   tree (WAL, active TSDB, compactor and persistent markers). Preserve source
   unmodified. Compare path/type/size/SHA256; expose the final directory only
   after verification and unmount the copy pod before starting a writer.
3. Exactly one writer, unchanged mount path, security and retention. Verify
   historical line by private timestamp/hash, new log arrival via the real
   cluster Collector, queue drain, /ready and a successful retention pass. TCP
   readiness alone is insufficient. Do not switch back to the stale source
   after new writes without preserving and reconciling both copies.

## Second-window result and next launch guard

The 82,606,080-byte cold delta and its inventory were transferred directly;
37,040 target paths matched the stopped source. No production writer used the
claim. A squash/remerge propagated `replicas: 0` into the proposed resume;
server dry-run caught this, #206 was closed, #207 restored the original writer.
The candidate now has a `loki/` tree **as of that stop**, not a current copy.
Do not reapply the original empty-target pilot or replay the previous delta.

The chart's single `storagePhase` chooses local (one writer, original disk),
paused (zero writers, original disk), or shared (one writer, verified claim).
Never merge `shared` until the newest cold inventory matches and helpers have
unmounted. Base resume on the **actual squash-merged paused main**; change
only that values line. Verify the prospective merge tree through Helm using
Argo's values file and Kubernetes server dry-run (replicas, strategy, claim,
node selection). Reject mismatch; after new writes never restore `local`
without reconciling both histories. Changing a phase is a maintenance action,
not part of installing this neutral chart change.
