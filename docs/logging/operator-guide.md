# Unified logging operator guide

Start with the [final active coverage report and complete source registry](coverage-final-2026-11-04.md), not configured receiver lists. [Recovery acceptance](rollout-recovery-2026-11-04.md) records exact deployed owners, runtime failures and queue gates. The broader [operations guide](../unified-logging-operations.ru.md) remains applicable.

## Diagnose before changing collection

1. Inventory **running regular non-Job containers** and **currently running host units** separately. Do not label inactive/timer units failures. Include Loki/Tempo; exclude only actual Collector self-output.
2. Use metadata-only instant Loki count queries with **one fixed evaluation timestamp**, namespace and host selectors, 600/3600s windows; `scripts/logging-coverage.py` supplies validated grouping. Never print secrets or application bodies. Existing authenticated query helpers must keep credentials private.
3. For unmatched containers, count timestamped stdout in the identical absolute window, discarding bodies in process memory without output/persistence. For hosts request journal metadata fields, not MESSAGE; record effective journal visibility. Do not infer silence from an unprivileged empty journal.
4. Run `scripts/reconcile-active-logging.py --pods PODS.json --metadata COUNTS.json --host-prefix HOST_SNAPSHOT_PREFIX --source-counts STDOUT_COUNTS.json --output REPORT`. Source counts require start/end600s and successful per-identity `status:ok,count`; metadata must declare `evaluationTimeFixed:true`. Host snapshot names end0.txt through3.txt, with running-unit lines then `JOURNAL_COUNTS` JSON. Failed queries and unaligned windows stop acceptance.
5. Zero stdout is a **window-specific explicit no-heartbeat exclusion**, not proof of delivery or permanent silence. Emitting unmatched sources need reviewed identity/path/receiver/checkpoint evidence. Preserve cursors/queues; never wholesale replay, reset state or invent heartbeat traffic for unknown applications.

## Changes and runtime acceptance

- Single writer per scope. Review current live config and remote concurrent changes. No force pushes. Test/render before normal commit/push and deploy through the owning chart/Argo resource or exact logs-only owner.
- Native host owner: `ansible/playbooks/otel-logs-only-rollout.yml`, serial one-host limits. Cluster owner: `ansible/playbooks/otel-cluster-logs-activate.yml` with exact pod/container/config/binary identity checks. Preserve shared metrics/traces, Thanos and adjacent containers. Never deploy applications as a collection workaround.
- Backend owner: `charts/otel-backends`. Target only the defective resource. Loki requires writable marker scratch `/tmp` despite RO root; the prepared local chart supplies Loki-only bounded emptyDir (not deployed; see blocker report). Completed marker objects and compactor working state stay on the existing persistent data path. Do not touch retention durations, certificates, security context or Tempo to fix scratch permissions.
- Check actual readiness, exported log growth, receiver refusal/send/enqueue failure deltas, **logs-only byte queues** and source receipts. A positive instantaneous queue is not loss; demonstrate bounded/draining behavior. Record actual restart/scrape gaps and failed commands rather than silently retrying with another provider/CLI.
- Retention acceptance requires successful compaction counters/timestamps and clean new failure deltas, plus long-horizon deletion/capacity evidence; a config file alone is insufficient. Never manually delete data/markers as a test.

## Grafana

On actual Grafana13.2.4, `meta.provisioned:false` with provider `allowUiUpdates:true` and nonempty `provisionedExternalId` is normal database-backed API behavior. See linked official version source in the report. Do not change auth or provisioning to make this cosmetic field true. API checks do not substitute for browser validation; never terminate another user's browser session.

## Known open work

The report preserves exact unmatched journal candidates, external app source-level logging/deployment gaps and unrelated rollout health exceptions. Re-run counts in a fresh aligned window before acting. Source-silent exclusions and best-effort vendor normalization are not blanket all-service logging acceptance.


## Updated retention/journal operations
Loki-only writable scratch /tmp1Gi is required with RO root. Verify actual successful retention timestamps/counters after restart; do not compare counters across process resets. Production deletion delay2h is unchanged; isolated fixture expiry proves implementation, not production sweeper timing or disk approval. Cache/index lifecycle can retain query visibility after physical deletion. Retention failure/stale/missing-metrics rules installed, but authenticated scrape remains unverified and missing-series alert must not be silenced as success. Per-service policy remains empty;3/7/14d severity,14d unlabelled fallback.
Journal identity must be staged per log then split by groupbyattrs before resource promotion: never assign resource.service.name from each record body within a shared batch. Current serial rollout preserves cursor state, TLS and all nonlogs components. Use unique logging_private_dir for EVERY attempt; rollback backup derives that basename and must match fetched current preimage, not stale original force:false backup. Require natural-source aligned receipts after activation; synthetic fixtures/heartbeat do not prove unrelated units.

## Final native Loki monitoring owner and bounded 24h observation
The prior missing-metrics gap is CLOSED. `scripts/otel-scrape-config.py:add_logging_self_monitoring` and production bootstrap persist the additive verified-mTLS `otel-logging/loki` target in native `scrape.yaml` (5s interval,4s timeout). Use existing `/etc/otel/tls/{ca.crt,client.crt,client.key}`; never copy a CA private key or use insecure_skip_verify. No legacy ServiceMonitor activation. Actual up=1, fresh retention series and all3rules inactive/healthy verified. Reconcile must preserve all other scrape jobs and exact Collector logs/traces/metrics configuration. Collector-only restart safeguards now optionally verify the scrape hash too.

Repeatable observation (read-only; start at a chosen operator window, not automatically left running):
```sh
# Terminal1; Ctrl-C when observation ends.
kubectl -n cattle-monitoring-system port-forward service/kube-prometheus-stack-prometheus 18099:9090
# Terminal2; creates a NEW local metadata-only file, maximum24h/2MiB.
python3 scripts/logging-retention-observe.py --duration-seconds 86400 \
  --interval-seconds 300 --output /tmp/loki-retention-24h.ndjson
# One-sample smoke instead: --duration-seconds 0 with a fresh output filename.
```
Default24h gives about289samples/2601instant aggregate queries, hard2MiB output bound and10s per-query timeout; no log bodies. Query/runtime failures are recorded as error types, never counted healthy. Review targetUp=1, sampleAgeSeconds<30, lastSuccessAgeSeconds<900, failures absent/zero delta only within the same processStart, and no firing retention alerts. Absent failure counter alone is NOT proof if target/sample missing. Marker creation/deletion may remain0 when no aged data is eligible; do not force-delete or shorten live retention. Observe natural2h sweeper lifecycle and cache/index convergence when markers appear. Snapshot physical Loki disk allocation/free space/inodes read-only before/after; require disk usage<80%,free>20% and nonnegative growth headroom as provisional operator budget, not an approved retention-extension model. Stop/reassess on missing scrape, errors, stale success or exceeded disk headroom; never silently extend retention.3/7/14d/global14d policy unchanged, services{} and capacityApproval null; approval requires actual disk/growth reserve evidence, not logical compressed-payload estimates alone.

Monitoring implementation is complete now; this bounded24h operational observation is a followup reliability/capacity check, not a requirement to wait a week or a claim of infinite service guarantees. CI SSH-key repair, preexisting unrelated LMS DB-resource drift, optional browser visual verification and producer-native JSON enhancements are separately owned followups. Existing supported text/logfmt/journal formats need not all be rewritten to JSON.
