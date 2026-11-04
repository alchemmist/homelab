# Native agent logging contract and rollout

No deployment was performed by this change. Metrics pipelines, Thanos and application databases are unchanged.

## Coverage and identity

Each native agent reads **all** Kubernetes pod/container stdout/stderr files under `/var/log/pods` (except the existing OTel self-log exclusion) and the host system journal, including system and user units accessible to root. Container parser extracts CRI/Docker timestamps, stream and Kubernetes identity, and recombines runtime partial fragments. Journal receiver supplies journal event timestamps and persistent cursors; priority maps to severity. Container service falls back to container name; journal service is systemd unit (fallback `host-journal`); non-Kubernetes namespace is `host`. Host identity remains the inventory hostname. `severity` is normalized on each log then promoted by `groupbyattrs/log-severity` into separate resource groups, allowing indexed severity without mixed-severity resource mutation. Loki must explicitly index resource `severity` for stream retention; pod/container/systemd-unit fields remain structured metadata, not indexed labels. Canonical resource keys become `service_name`, `k8s_namespace_name`, `host_name` in Loki. Unknown severity stays `unknown`, not falsely `info`. Plaintext level inference is best effort, not a structured application schema.

This is not coverage of arbitrary application files, remote Docker hosts, external Kubernetes nodes or applications that do not emit logs. Inventory coverage must be compared with actual nodes/services before enabling. Do not add a second Kubernetes logging DaemonSet: native agents already own those files. The journal normally contains runtime daemon diagnostics rather than a second copy of pod stdout; verify this on each runtime. Applications configured to tee stdout into the journal or several files require explicit source exclusion, not content-based deduplication.

Runtime partial multiline records are recombined; arbitrary application stacktrace lines are intentionally not joined across stdout/stderr or unrelated requests. They remain timestamped individual records, avoiding unsafe cross-service merges. Source-specific application multiline rules require fixtures and per-stream routing before introduction.

## Delivery, privacy and disk bounds

Filelog starts newly discovered files at beginning, checkpoints offsets with fsync, and retries downstream failures indefinitely. Existing ingestion boundary still cuts pre-migration records; do not advance it on restarts or rollback. Journal starts at end only when no saved cursor exists. Keep the state directory and receiver IDs across upgrades; do not clear cursors or rename the old `otlp` metric exporter.

Logs now have a distinct 128 MiB byte-sized persistent exporter queue, infinite retries and blocking overflow. This isolates metric queue capacity. Removing the asynchronous log batch processor allows filelog backpressure to propagate rather than acknowledging a volatile batch. Privacy redaction occurs before this persistent log queue, as well as at the cluster tier. Redaction is defense in depth, NOT proof that arbitrary free-text secrets are removed: source suppression remains necessary. Never expose bodies in rollout evidence.

Two agent queues total **256 MiB logical payload capacity**, not a filesystem quota. Bolt storage overhead, checkpoints, fragmentation, WAL/free pages and pre-existing queue files can increase measured disk consumption. Do not present logical limits as measured physical bounds. No hard state-directory quota is installed: it could break checkpoints and metrics together. Before approval measure allocated `du` bytes at baseline, saturation and after drain/restart, queue size/capacity and node free space; provision headroom and alert before exhaustion. During longer outages, backpressure eventually reaches finite journal retention/kubelet rotation; loss remains possible. Delivery is at-least-once, not exactly-once: crashes around ack/checkpoint can duplicate events. Keep journal retention and kubelet file budgets greater than the measured outage window.

## Staged rollout and rollback (operator approval required)

1. Regenerate artifacts from this checkout using the existing production bootstrap; keep boundary/TLS values unchanged. Back up installed agent YAML and service unit, not secret material in evidence. Run existing offline tests and pinned Collector `validate`.
2. Use production agent playbook with `--limit socrat-0` first. It validates installed config before restarting changed agents; serial=1 and any_errors_fatal stop advancement on task failure. This is **not** an automatic health-gated multi-host rollout: operator checks below are mandatory before each next node. The existing playbook also manages the node exporter and socrat-0 trace gateway; inspect its diff/check output before invoking.
3. Check health endpoint, process restart count, receiver accepted/refused counts, queue occupancy/export failures and metric freshness. Emit synthetic non-sensitive CRI partials, journal priorities and service identities; verify timestamps and schema downstream. Rotate fixture file, restart agent, disconnect test endpoint, fill/drain queue and verify expected IDs, missing IDs and duplicate count without bodies. These runtime fault tests remain an operator release gate, not satisfied by offline config validation.
4. Measure physical state disk and compare with the documented budget; verify active node/service inventory, journal permissions and container parser behavior before proceeding one node at a time.
5. Roll back agent config/unit and restart, preserving state/cursors and boundary. Drain the new `otlp/logs` queue before removing that exporter or queued records will be stranded. Do not delete the state directory. No metrics/backends/database rollback is needed.

Offline validation evidence for this revision: Collector contrib 0.164.0 `validate` exit 0 in a local network-disabled container with generated disposable certificates and a dummy scrape target. This checks schema/OTTL parsing, not journal execution, file rotation, queue saturation or live delivery.

## Reviewer-blocker runtime evidence (isolated, no rollout)

`python3 scripts/test-otel-log-runtime.py` runs the Collector image by **index digest from
`otel-images.lock.json`** (0.164.0), copying the production privacy processors and
agent severity processor, without production endpoints, credentials or source data.
It reports assertions/counts/IDs only. Docker/Podman and PyYAML are prerequisites.

Privacy now parses JSON object/array strings before serialization, recursively
flattens maps (including nested array members with collision resolution), removes
sensitive field paths, then serializes. The same treatment applies to resource/log
attributes. Nested headers are removed in full, since custom headers can carry
secrets without recognizable credential names. Useful non-sensitive event/status
fields remain. Top-level arrays have no field schema and are replaced with an
explicit redaction marker. JSON-looking malformed input fails closed through
`error_mode: propagate` rather than exporting an unsanitized payload. Ordinary
bracket-prefixed plaintext is not treated as JSON. Free-form labeled prompt,
completion, request/response body, header and cookie payloads are redacted through
the remainder of the record (including newlines); unlabeled arbitrary personal
text **cannot** be safely classified by these rules. Producers must suppress such
content or use reviewed structured fields before broad collection; this is not a
claim that all possible free-text PII is removed.

Observed runtime results:
- Agent and cluster: 8/8 records each, including native maps, JSON strings,
  nested array/map fields, custom headers, top-level arrays and multiline labeled
  free text. Synthetic sensitive sentinel absent; safe event/status values retained.
  Nested attribute headers/prompts are covered on every test record.
- Agent plain INFO/WARN/ERROR: 3/3 normalized correctly using escaped OTTL regex
  word boundaries. Numeric structured severity mapping remains unchanged.
- Isolated cluster-equivalent OTLP pipeline: persistent **two-request** queue,
  one consumer, sink unavailable; 12 concurrent requests, 2 acknowledged and
  10 blocked after four seconds. Forced Collector kill, restart with same state,
  then sink recovery: all 12 IDs received, total 12 records in this run.
  Client retries on interruption are required; duplicates remain permitted.
  The test changes queue size/sizer/consumer count, retry timing and transport to
  make saturation bounded and local. It is not a production byte-budget benchmark.

Cluster Loki queue now blocks on overflow and the asynchronous log batch processor
is removed, so queue pressure reaches the OTLP sender instead of a batch worker
losing previously acknowledged records. Metrics and trace batching/exporters are
unchanged. Runtime tests do not establish filesystem capacity, real Loki behavior,
long-outage rotation survival, journal/file checkpoint recovery or production TLS
health. Those remain release gates, as do measured disk reserve/retention approval
and the separate coverage-verifier review items. No deployment was performed.
