# Loki retention policy (staged, not applied)

Scope: Loki only. This change does not touch Prometheus, Thanos, Tempo, application databases or their storage. No live retention changes are authorized in this phase. Existing live retention remains unverified (repository baseline: 336h).

## Configuration

Edit `deploy/monitoring/otel/retention-policy.json`, run `python3 scripts/otel-loki-retention.py`, then `python3 scripts/otel-loki-retention.py --check`. Both static Loki config copies are generated identically. The Helm chart consumes its static copy; it does not introduce a second independent policy surface.

Defaults: debug 3d, info 7d, warn 30d, error 30d, unknown 14d. Missing, unrecognized or legacy severity labels fall through to global 14d. Explicit normalized `unknown` is also 14d. Trace should be normalized to debug, fatal/critical to error by the collector. Loki does not infer these labels from log text for retention. `log_level` must be an **indexed resource attribute** on each OTLP record's resource, not merely a log attribute or structured metadata. Resource indexing is explicitly allowlisted. Historical streams without this label retain the fallback; these rules do not retroactively label them.

All service names use the same defaults automatically. Exact per-service/severity overrides are supported, for example:

```json
"services": {"example-service": {"debug": 48, "error": 720}}
```

Only listed severities are overridden. All defaults have priority 10; service+severity overrides have priority 100. No equal-priority overlaps are generated. Loki picks the **highest numeric priority**, and for equal priorities picks the **shortest period**, not the longest. If no selector matches, global retention applies. Policy validates integer 24h–8760h, and permits >720h only for error with an explicit measured `capacityApproval` containing `measuredAt`, `evidence`, `budgetBytes`, `projectedBytes`, `approvedBy`. This review record is not a substitute for measurement. No 365d default is justified today.

## Read-only capacity evidence and limits

2026-11-04T08:40:28Z, kubelet summary via read-only Kubernetes node proxy on socrat-1: node filesystem capacity 396,323,180,544 bytes; available 230,032,089,088 bytes; used 146,083,983,360 bytes. This is shared node storage, **not** Loki directory usage or a dedicated allocation. Four aggregate Prometheus queries (24h/1h distributor byte rate, distributor cumulative bytes, ingester streams) returned empty vectors. No log bodies were queried. Therefore Loki ingestion rate, on-disk compressed size, growth, and severity distribution are **unknown**, not zero. Do not infer a 365d budget from free node space. No hard filesystem quota is implemented by these retention settings.

Before activation, obtain at least 7 representative days of per-severity/service stored-byte growth, Loki directory size from a separately approved host read, WAL/compactor peaks, shared-volume growth, and inode availability. Choose an explicit Loki budget from remaining space **after** reserving at least 20% filesystem capacity plus other workloads' growth and compaction/WAL headroom. Estimate steady-state sum(bytes/day per severity × retained days), add observed transient peaks and at least 2× growth uncertainty. Reject extensions that exceed budget. Short tests must not justify year-long retention. Add aggregate Loki metrics scraping if currently absent; never request raw log responses for capacity evidence.

## Safe rollout / pressure handling

1. Review generated diff and tests; verify pinned Loki binary accepts config with `-verify-config=true` and environment expansion in an isolated runtime. This checkout's unit tests are not a binary parser test.
2. Establish collection coverage and indexed severity correctness with synthetic non-sensitive canaries before shortening retention. Preserve a restorable filesystem snapshot including index/chunks/compactor marker files before any approved retention change. Keep compactor working directory persistent (current path is on Loki host storage).
3. Get separate approval for live reductions: debug/info become shorter than baseline. Increasing warn/error retention cannot restore already-deleted logs. Loki retention changes should not be treated as a reliable retroactive migration of already-ingested data; verify behavior with the pinned release and a disposable store.
4. Apply only approved backend config, verify readiness, compactor success/deletion metrics, query canaries, free bytes and inodes. Retention deletes asynchronously after compaction and 2h deletion delay; 24h TSDB index periods are required and configured. Do not expect a hard immediate disk ceiling.
5. Suggested operational pressure gates, pending actual budget: warn at 70% Loki budget or shared filesystem below 25% free; critical at 85% budget or below 20% free. Forecast exhaustion using observed growth. First expand/move **Loki-only** storage or explicitly pause/reduce debug ingestion with loss approval; queue/backpressure also consumes disk. Any emergency retention reduction requires explicit approval and is irreversible after deletion. Never arbitrary `rm`, truncate chunks, delete WAL/markers/index, or touch metrics/Thanos/application data. If capacity is exhausted, reject/pause ingestion deliberately instead of corrupting storage. Restore config to roll back future policy, but restore from snapshot for deleted data.

## Official sources (pinned semantics checked)

- [Loki retention documentation](https://grafana.com/docs/loki/latest/operations/storage/retention/): compactor, persistent marker directory, 24h index, minimum 24h retention, asynchronous deletion, selector precedence and filesystem limitations.
- [Loki v3.7.9 retention implementation](https://github.com/grafana/loki/blob/v3.7.9/pkg/compactor/retention/expiration.go#L186-L218): highest priority / shortest equal-priority match / global fallback (fetched and inspected).
- [Loki v3.7.9 validation](https://github.com/grafana/loki/blob/v3.7.9/pkg/validation/limits.go#L590-L610): stream retention minimum 24h (fetched and inspected).
- [Official OTLP ingestion mapping](https://grafana.com/docs/loki/latest/send-data/otel/): resource attributes to index labels, dots normalized to underscores, other attributes structured metadata.

Image remains pinned to the existing Loki 3.7.9 digest; no image, schema or storage relocation is included.
