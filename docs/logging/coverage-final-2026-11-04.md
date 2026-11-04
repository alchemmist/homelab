# Final active-source logging reconciliation — bounded, not full coverage

Operator entry point: [logging operator guide](operator-guide.md). Prior [recovery acceptance](rollout-recovery-2026-11-04.md) remains intact.

## Exact window and denominator

Loki queries evaluated at **2026-11-04 10:02:24.777305 UTC**, fixed explicitly on both selectors (`k8s_namespace_name`, `host_name`), for 600s and 3600s; repeated at the identical evaluation time after further settling. All queries succeeded. Duplicate overlapping selector groups are deduplicated. Source stdout counts cover 09:52:24.777305–10:02:24.777305 UTC. Host journal counts use integer-second boundaries (09:52:24–10:02:24), so subsecond edge differences remain possible. Running-unit snapshots and pod snapshots are sequential, not atomic.

[Complete registry JSON](active-coverage-final-2026-11-04.json) / [TSV](active-coverage-final-2026-11-04.tsv): **258 identities = 141 running regular non-Job containers + 117 running system services on four hosts**. Each row includes canonical/legacy/unobserved normalization and evidence counts. This is not an installed-unit denominator. Jobs, nonrunning, init and ephemeral definitions are excluded and counted. Original historical artifacts are not overwritten.

| Classification | Identities | Meaning |
|---|---:|---|
| Fresh canonical receipt | 85 | 62 containers + 23 running host units; all observed fresh groups meet identity/severity contract |
| Explicit no-heartbeat window exclusion | 78 | Running containers with **zero source stdout records in aligned 600s**; not lost logs and not permanent silence |
| Collector self-log exclusion | 1 | Prometheus pod `otel-cluster`; six source records, deliberately excluded to prevent loops |
| Hour receipt, not fresh | 9 | Host units with no fresh matched receipt; no fresh source emission established |
| No receipt, emission unproven | 81 | Host units; unprivileged journal visibility insufficient for silence/loss conclusion |
| Journal emission without matched receipt | 4 | Open candidates below; not waived |

**62/62 naturally emitting non-collector regular containers have matched fresh canonical receipts.** All 141 stdout count commands succeeded. Zero-output containers have no imposed heartbeat contract: absence is explicitly excluded from loss acceptance for this window only, not hidden as coverage. File-only application logging or inaccessible earlier rotations are not established by a zero stdout count. This does not prove end-to-end delivery of every individual line. Loki and Tempo are included, not covered by a blanket `otel-*` self-exclusion.

Counts were computed from transient `kubectl logs --timestamps` output in process memory; application bodies were never printed or persisted. Loki queries returned only aggregate metadata/counts. Host journals requested metadata fields only.

## Remaining exact host candidates

| Host | Running unit | Visible source records / 600s | Matched Loki / 600s | Matched Loki / 3600s |
|---|---|---:|---:|---:|
| socrat-0 | user@1000.service | 1 | 0 | 2 |
| socrat-1 | iwd.service | 3 | 0 | 0 |
| socrat-1 | knot.service | 80 | 0 | 0 |
| socrat-1 | systemd-logind.service | 3 | 0 | 43 |

Host1 candidates have source host `socrat-1`, current boot, priority6; source-vs-journal timestamp lag below1ms where present. This rules out old boot, host-alias mismatch and ordinary source-clock skew. Actual readable host1 agent configuration has journald `storage: file_storage`, `start_at: end`, no unit/priority filter. Current counters showed no processor incoming/outgoing discrepancy (102959 each), both receiver refusals0; accepted journald2998/filelog99961. Queue observed9876 **bytes**, then drained0 on a later bounded sample; this is not a permanent queue-zero assertion. Fixed-window metadata repeat did not resolve the four matches. Do not reset checkpoints or replay journals wholesale. Receiver journal scope/checkpoint and record attribution remain possible causes, not proven defects; no speculative deployment was performed.

Zero journal counts on other rows do not establish no emission: SSH users have incomplete system journal visibility. A privileged-journal attempt did not establish usable access; no privilege changes were made. Most of the former 145 unproven gaps are now narrowed by actual source evidence, but the remainder cannot honestly be declared closed.

## Runtime and current owned workload health

Fresh controller snapshot: n8n, spi-triage, img-proxy, litellm, litellm-branding, open-terminal, Grafana, Loki and Tempo each ready1/desired1; socrat-home and private-gateway ready2/desired2; syncthing ready1/desired1. All observed generations equal desired generations. Existing litellm-postgres also ready1/1, observed read-only only. All four native host agents active/running. No application/chart/Collector rollout in this reconciliation. Original metrics/Thanos, databases, auth/model configuration and checkpoints were untouched.

Unrelated health exception: **harbor/harbor-jobservice desired1, ready0** in the same snapshot. Not repaired as a logging side effect.

Actual diagnostic cleanup timeout is preserved: existing metadata helper fetched successfully but 30s pod deletion wait expired; subsequent authorized check found the owned diagnostic already absent and ignore-not-found cleanup completed. Grafana image lacks `sh`: shell inspection failed; no alternate provider/CLI or UI-session termination was used.

## Grafana `provisioned:false` is expected version semantics

Actual `/api/health`: Grafana **13.2.4**, commit `0e79aef9d91abf3bdadae9af15763029072fb45b`; database health `ok`. Actual dashboard API: UID `socrat-unified-logs`, version1, editable:false, meta provisioned:false, externalId `socrat-logs.json`, canSave/canEdit:true. Actual provider ConfigMap: file provider `sidecarProvider`, path `/tmp/dashboards`, allowUiUpdates:true, refresh30s.

[Official v13.2.4 dashboard API implementation](https://github.com/grafana/grafana/blob/v13.2.4/pkg/api/dashboard.go#L209-L229) reads the provisioning **database record** with `GetProvisionedDashboardDataByDashboardID`, sets `meta.Provisioned=true` only when that provider's **allowUIUpdates is false**, and sets the externalId from the database record. Thus the nonempty externalId plus allowUiUpdates:true explains the API result; it is not evidence of missing provisioning. No dashboard owner/auth change is warranted. Provider ConfigMap/mounted configuration references and API database-backed behavior were inspected; live dashboard file bytes and direct database SQL were **not** independently read. Do not claim direct file/DB byte comparison. Browser visual/Explore interaction remains unvalidated because another UI session owns the browser; not terminated.

## External source-level work remains distinct

- LMS safe logging changes built in an external repo, but deployment CI failed SSH key authentication; **not deployed**, no auth workaround.
- Bot source logging changes recovered/tested in its external repo; upstream push/deployment status is owned by that lane, not established by this registry.
- `format-quorum`, `monori`, `wiki`, `cats/blog`: source-level logging improvements **not implemented** here. Collector normalization is best effort; no source JSON/privacy guarantee.
- Existing 98-service Loki scope/four-host receipt evidence is retained as backend/UI scope, not conflated with this active per-container/unit registry.
- Retention compactor errors/no successful compaction were separately identified by retention owner; configured retention is not enforcement acceptance. See supervisor's retention report before claiming deletion/capacity safety.

## Validation and ownership

Reconciler now accepts optional aligned stdout count metadata, fails closed on mismatched query windows, labels no-heartbeat exclusions explicitly and only excludes the real Collector identity (not Loki/Tempo). Three regression tests cover these distinctions. Logging test discovery: **39 passed**. No runtime config fix was justified by remaining evidence. This report intentionally does not claim completion of full-service logging, retention enforcement, rotation/restart acceptance or UI validation.
