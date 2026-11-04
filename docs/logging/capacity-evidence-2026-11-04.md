# Loki allocated-disk measurement — 2026-11-04

Scope: explicitly authorized temporary privileged diagnostic pod on socrat-1, only `/var/lib/private/homelab-otel-loki` hostPath mounted read-only. Busybox 1.37 ran `du -k -d 2`, `df -k`, `df -i`, timestamps and a 120-second sleep. No file contents, application data, log bodies, credentials, or deletes were requested. No retention or collector rollout. Pod `cattle-monitoring-system/logging-capacity-diagnostic` was deleted and Kubernetes wait-for-deletion completed successfully. No host root mount or service-account token.

| Measurement (KiB allocated, not apparent bytes) | 08:53:42Z | 08:55:42Z |
|---|---:|---:|
| Loki hostPath total | 513380 | 523332 |
| chunks | 482424 | 483424 |
| WAL | 30652 | 39604 |
| active TSDB index | 68 | 68 |
| shipper cache | 160 | 160 |
| compactor | 64 | 64 |
| rules | 4 | 4 |
| filesystem capacity | 387034356 | 387034356 |
| filesystem available | 224625436 | 224613644 |
| filesystem used | 142675416 | 142687208 |
| inodes total | 24649728 | 24649728 |
| inodes available | 22425543 | 22425512 |

Total allocation increased from **525701120 to 535891968 bytes**, delta **10190848 bytes / 120s**. Naive extrapolation is 7,337,410,560 bytes/day (~6.83 GiB/day). This is explicitly **not** a daily-growth upper bound or retention approval: WAL accounts for most delta, flush/compaction/deletion churn is unobserved, and the short interval is not representative. Chunks alone increased 1,024,000 bytes. Shared filesystem capacity is 396,323,180,544 bytes and final available is 230,004,371,456 bytes. Neither is a dedicated Loki allocation. At least 79,264,636,109 bytes (20% rounded up) must stay reserved before other-workload growth, WAL/compactor transients and safety margin; no explicit Loki budget or approver exists.

Prior metadata-only count evidence observed ~62 records/s; cumulative native ingestion metrics do not measure compressed disk growth. Per-level stored-byte growth remains unavailable/unattested, so no severity-based storage discount is justified. No additional log-body queries were made. This measurement supersedes the earlier report's **unknown allocated size**, not its unresolved representativeness/retention gates.

Decision: **no capacity approval; no live retention rollout**. Stage trace/debug3d, info7d, warn/error/fatal at most14d; preserve unknown and legacy fallback14d. Desired warn30/error30 (and any service extension >14d) require the renderer's documented representative 7d evidence, conservative projection, explicit budget and reviewed headroom approval. Shortening debug/info also needs separate live deletion approval. Still missing: representative gross storage-growth upper bound, transient peaks, other-workload reserve, per-level metrics if desired, human approver, pinned-binary config validation, and live retention verification.
