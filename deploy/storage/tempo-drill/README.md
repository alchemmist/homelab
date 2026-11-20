# Tempo production volume — migrated from socrat-1

**Active production data: do not empty or delete this PVC.** Despite the
historical name `tempo-s1-candidate`, the singleton now uses this existing
`nfs-shared` claim (4 GiB requested, Retain backend on socrat-0). Its volume
is not node-local. Never start a second writer. This covers socrat-1 loss,
not loss of the NFS server. The provisioner does not enforce a directory quota.

On 2026-11-20, #198 quiesced the sole writer. The complete cold archive was
extracted and verified, then compared to the stopped source. A restricted copy
pod mounted the source read-only, verified every relative path, size and SHA256
for 949 files (237561281 bytes) and unmounted before #199 resumed Tempo. Exactly
one Ready pod on 0 uses the verified PVC. A preselected pre-cutover trace was
read from completed blocks; a new production trace after restart was searched
and read by ID. The gateway queue drained to zero. Do not publish trace IDs or
payloads. The old hostPath and backup archives on 1 are recovery points, not
current state. After new writes, never blindly switch back to the stale source.

## Earlier isolated pilot (before production cutover)

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
