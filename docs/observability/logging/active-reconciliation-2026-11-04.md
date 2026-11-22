# Active logging reconciliation (metadata only)

Acceptance: **NOT complete**. This supplements, and deliberately preserves, the pre-existing untracked rollout JSON/remaining TSV. Their 120 verified historical receipts and installed/inactive denominator must not be represented as today's active coverage.

## Durable runtime evidence

Fresh bounded Loki instant count queries: namespace and host selectors, 600s and 3600s; all four succeeded, 332/685 returned groups (selectors overlap). TLS verification and existing mTLS secret mounted only in named temporary diagnostic pod `logging-metadata-diagnostic-20261104`; pod creation, readiness, requests and deletion succeeded. No application bodies returned. Native severity index and configured 3d/1w/2w severity retention rules were observed, not merely repository configuration. This does not attest actual deletion or disk capacity.

`active-coverage-2026-11-04.{json,tsv}` is the exact identity matrix. Denominator: 141 running regular non-Job containers plus 117 currently running host service units across **all four hosts**. Init/ephemeral, Job and nonrunning regular definitions are excluded and counted separately. Source snapshots are collected sequentially, not atomically.

258 active identities: 94 fresh canonical receipts; 13 hour receipts without fresh receipts; 145 no matched receipts with emission unproven; 2 explicit self-log exclusions; 4 journal-emitting identities without a matched fresh receipt. Neither silence nor installed-unit existence is classified as missing. Running system services are not the full set of periodic emitting services: timer-driven inactive services may still emit, but are outside this active denominator.

### Exact actionable exclusions

- `cattle-monitoring-system/otel-loki-58655fcd84-mvsbt/loki`
- `cattle-monitoring-system/otel-tempo-7b5d947c8b-gc9lj/tempo`

Repository `deploy/monitoring/otel/agent.yaml` excludes `/var/log/pods/*_otel-*_*/*/*.log`, unintentionally excluding backend application logs along with collector self-logs. Bounded fix: narrow exclusion to actual collector pod/container identities, retain loop protection, validate the logs-only rendered config, then use the existing agent deployment path. No live changes were made under read-only authorization.

### Exact independent journal-emission candidates

On socrat-1: `iwd.service`, `knot.service`, `NetworkManager.service`, `sshd.service`. Visible journal metadata counts in the later host 600s observation: 4, 80, 8, 7 respectively. No matched fresh Loki receipt at the earlier query evaluation. These are **investigation candidates, not proven loss**: sequential moving windows and ingestion latency can explain disagreement. Align absolute source/query intervals before treating these as missing. Inspect journald receiver units/priority filters, ingestion-start cut, checkpoint lag and service-name attribution; never reset checkpoints or replay journals wholesale.

Journal reads were unprivileged with only `_SYSTEMD_UNIT` requested. socrat-0/2/3 returned predominantly user/session metadata; their accounts do not list systemd-journal membership. Directory readability alone does not establish system-journal access. Thus zero journal counts there cannot establish lack of emission. Agents on all four hosts are active/running with journal stdout and default root User; no service restart or privilege escalation was attempted.

## Remaining bounded diagnostics / exact deployment paths

- All other absent identities and their node/service attribution are listed individually in the TSV under `no-receipt-emission-unproven`; do not replace them with a speculative missing-service list. Determine stdout versus file-only destination from each workload's reviewed configuration and targeted file-size/mtime metadata; no wholesale `/var/log` reads. File-only sources require explicit approved narrow receiver includes, not arbitrary application data requests.
- Existing health probes were inventoried but no health call was issued: ordinary health handlers are not known to emit logs per source, and forcing traffic would not independently prove each sidecar's output. No arbitrary writes, DB calls, auth/model changes or synthetic user requests were performed.
- Agent collection owner paths: `deploy/monitoring/otel/agent.yaml`, logs-only renderer `scripts/otel-logs-only-config.py`, `ansible/playbooks/otel-production-agents.yml`. Preserve existing metrics/traces settings; review a logs-only diff before any deployment. Backend owner paths: `deploy/monitoring/otel/loki.yaml`, `ansible/playbooks/otel-production-backends.yml`; do not deploy broad backend playbooks to remedy source silence. Metrics/Thanos and databases remain untouched.
- Reconciler: `scripts/reconcile-active-logging.py`, consuming bounded snapshots and verified count vectors. It fails closed on partial query failures. Matrix counts deduplicate overlapping label groups; moving evaluation timestamps still prevent exact loss calculations.

No cluster configuration writes except the authorized temporary diagnostic pod; no root filesystem writes, application database accesses, commits, pushes or deployment. Original dirty files preserved. This is a practical narrowed acceptance report, **not a completed unified-logging claim**. Remaining gates include source-aligned emission proof, explicit exclusion resolution, per-active-source safe natural canary where supported, rotation/restart acceptance, disk growth/retention enforcement and dashboard verification.
