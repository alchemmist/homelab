# Logging rollout recovery — bounded phase accepted

Status: **fixed cluster logs candidate live; narrowed filelog exclusion live on all four hosts; desired logs source promoted**. This is bounded recovery acceptance, **not all-service coverage or blanket reliability**. Sanitized numerical evidence: `recovery-acceptance-2026-11-04.json`.

## Root cause and corrected candidate

Previous-container diagnostics identified propagated OTTL `ParseJSON` failures on truncated JSON-looking bodies. The prior 40-second measurement with 39 receiver refusals was not clean and is not waived.

Parsing now runs in an isolated silent-error statement group, assigning parsed data directly to `body`. The subsequent propagate-on-error group replaces any still-JSON-looking string with a fixed invalid-JSON marker. Later sanitization remains fail-closed.

The first authorized runtime rerun exposed an actual defect in the proposed candidate: cache values were not shared between statement groups, so valid JSON lost safe fields. The safe-field assertion failed. Direct body assignment corrected it; assertions were not weakened. Subsequent pinned-image results: agent privacy 9/9, severity 3/3; cluster privacy 9/9; queue outage 12 sends, 2 acknowledged and 10 blocked; crash/restart recovery 12/12 unique synthetic IDs and 12 total records.

## Exact live activation and nonlogs protection

Fresh live ConfigMap/pod/container snapshots, not stale original identities, drove the logs-only merge. Candidate validated through the installed Collector after projection. An initial validation command used the wrong config path and failed; corrected to the actual `/etc/otel/config/collector.yaml`, which validated successfully before activation.

Used committed `ansible/playbooks/otel-cluster-logs-activate.yml`: projected config SHA, fresh pod UID, exact running container ID/name/state/imageRef, and full pinned binary SHA `57911a9d902cfe2c287dac09fcee4b054630b4ec248fa190a3115d860a32f81f` checked before `k3s crictl stop --timeout 90` of only that Collector. No whole-pod or StatefulSet restart. Same pod UID/storage/checkpoints/TLS; adjacent Prometheus, config-reloader and Thanos container IDs and restart counts unchanged at final check. Collector restart count 2 to 3, previous exit 0; stopped 09:45:01Z, running 09:45:02Z.

Actual native stored `up` sample timestamps for the two apiserver scrape targets spanning activation show 14.998s and 9.999s gaps, versus nominal 5s. This captures a scrape interruption despite only a one-second container transition. Do not equate container downtime with scrape continuity. Earlier unrelated larger gaps in the 30-minute query were not attributed to this activation.

Logs-only merger asserted unchanged live nonlogs components and extensions. Desired `cluster.yaml` now contains the accepted logs pipeline/privacy/exporter changes; these equal live semantically. Existing source/live **metrics exporter adaptations differ** (native loopback receiver versus generic source settings) and were deliberately not overwritten or claimed equal. Existing production owner `scripts/otel-production-cluster.py` generates the cluster ConfigMap using the source plus native adaptation. No metrics/trace configuration was changed in this phase.

## Fresh bounded acceptance

The first postactivation gate incorrectly aggregated metrics/traces queues with logs and required no positive instantaneous growth. It falsely rejected a 1.56MB metrics queue despite zero data-plane errors. Preserved that failed observation and corrected instrumentation to logs-only queue/capacity with the existing bounded capacity/growth criteria. This was a test bug, not silently accepted loss or a reason to roll back a healthy logs plane.

Corrected three consecutive 40-second cluster windows: exported logs 5,225 / 70,886 / 4,235; receiver refusal, send failure and enqueue failure deltas **zero throughout**. Logs queues 0→0, 0→34,855, 34,855→0 bytes, below capacity/growth limits. Metrics export positive in each interval. These are 120 seconds of bounded evidence, not indefinite reliability.

## Narrowed exclusion, serial hosts and actual receipts

The overbroad `otel-*` pod exclusion is replaced with the actual monitoring Prometheus pod's `otel-cluster` container path. Loki/Tempo and adjacent Prometheus/Thanos containers remain collectible. The merger migrates only the exact known broad pattern, preserving custom exclusions, shared receivers, cursor/storage settings, includes and host adaptations.

Used `ansible/playbooks/otel-logs-only-rollout.yml` serially with one explicit host limit per invocation. Each fetched fresh live config, merged/asserted nonlogs equality, validated, restarted only the native agent and passed its 40-second gate. All four active, positive logs/metrics export, refusal/send/enqueue deltas zero, queues bounded. A second fresh 40-second health check passed on all four after emitting one synthetic journal identity per host.

Count-only Loki queries proved delivery of all four known synthetic IDs through host agents, actual cluster and Loki: counts 2 / 2 / 1 / 2. Counts above one are not claimed as deduplication proof. Newly included backend log counts in the last 10 minutes: Loki 848, Tempo 226. No bodies were fetched or stored.

Offline tests: agent logging 5, logs-only rollout 5, privacy smoke 3, config contracts 5, production 3, logging coverage 8 passed. Prior dirty artifacts retained; private fresh snapshots, failed/corrected test observations and exact rollout results remain under `/tmp/logging-rollout-private`.

## Persistence and remaining limitations

Desired cluster logs source promoted only after live gates and actual receipts. Quarantined candidate retained as historical/runtime-test source, no automatic activation path. Host source and exact logs-only owner persist the narrowed exclusion and privacy fix. Commit/push must retain concurrent upstream changes; never force.

Active coverage reconciliation is still a separate denominator/evidence task. Historical `active-*` and rollout artifacts are preserved, not silently rewritten as current full coverage. Remaining source emission/absence investigations, rotation acceptance, sustained disk growth/deletion enforcement and service-specific fixes remain separate work. Dashboard API checks cover 98 services per UI lane; browser attempt failed profile-in-use and was not forcibly terminated. Installed provider/provisioned metadata mismatch and visual/Explore browser verification remain unresolved; no blanket UI validation claim.
