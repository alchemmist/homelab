# Loki: socrat-1 migration staging (not active)

Only `pvc.yaml` has been provisioned. Production still uses its original
hostPath. The target is single-writer, NFS on socrat-0, not protection from
loss of the NFS server. Requested capacity does not impose a hard directory
quota. Preserve 336h global retention, stream policies, mTLS, ruler and existing
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
