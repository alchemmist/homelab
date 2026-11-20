# Tempo candidate volume — staging only

`pvc.yaml` is a separate explicitly named 4 GiB RWO `nfs-shared` claim, not
mounted by production Tempo. The underlying NFS service is on socrat-0, so this
candidate addresses node **1** loss, not NFS server failure. Requested capacity
is not an enforced per-directory quota; check free space on the actual server.
Do not delete this PVC as part of a restart or substitute it for the live
hostPath before backup and verified cold copy.

2026-11-20 scoped preflight: two sequential tokenless disposable pods used the
production Tempo image digest and UID/GID 10001, each running an isolated Tempo
with the local backend and WAL on the candidate volume. No production Service,
credential or workload labels were used. The test listeners bound loopback and
a temporary NetworkPolicy denied pod ingress/egress. On 1, synthetic OTLP ingest,
TraceID lookup and a blocks-mode read succeeded. The first pod terminated before
the next mount. On 0, the prior synthetic trace was readable and a new trace
could be written and read. Both pods, the test config and policy were removed.
Only the unique synthetic scratch directory was removed; the candidate was
verified empty afterwards. Real telemetry and source hostPath were untouched.

This is a small, graceful-restart functional test, not production acceptance,
a benchmark, evidence of crash-safe WAL, or an indefinite NFS recommendation.
Before cutover: verify representative source layout, space and write/queue rates,
protect a restorable copy and a private reference TraceID. Stop the sole writer,
verify a full cold copy including the WAL, then start one instance and check
historical lookup, real new trace ingestion/query and exporter queue drain.
Before writes, abort can resume the unchanged source. After writes preserve both
copies; do not discard newer data or assume automatic merge on rollback.
