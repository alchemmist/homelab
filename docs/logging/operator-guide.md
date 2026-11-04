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
- Backend owner: `charts/otel-backends`. Target only the defective resource. Loki requires writable marker scratch `/tmp` despite RO root; the chart supplies Loki-only bounded emptyDir. Completed marker objects and compactor working state stay on the existing persistent data path. Do not touch retention durations, certificates, security context or Tempo to fix scratch permissions.
- Check actual readiness, exported log growth, receiver refusal/send/enqueue failure deltas, **logs-only byte queues** and source receipts. A positive instantaneous queue is not loss; demonstrate bounded/draining behavior. Record actual restart/scrape gaps and failed commands rather than silently retrying with another provider/CLI.
- Retention acceptance requires successful compaction counters/timestamps and clean new failure deltas, plus long-horizon deletion/capacity evidence; a config file alone is insufficient. Never manually delete data/markers as a test.

## Grafana

On actual Grafana13.2.4, `meta.provisioned:false` with provider `allowUiUpdates:true` and nonempty `provisionedExternalId` is normal database-backed API behavior. See linked official version source in the report. Do not change auth or provisioning to make this cosmetic field true. API checks do not substitute for browser validation; never terminate another user's browser session.

## Known open work

The report preserves exact unmatched journal candidates, external app source-level logging/deployment gaps and unrelated rollout health exceptions. Re-run counts in a fresh aligned window before acting. Source-silent exclusions and best-effort vendor normalization are not blanket all-service logging acceptance.
