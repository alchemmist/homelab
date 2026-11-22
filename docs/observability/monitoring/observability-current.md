# Observability: sources and owners

[Report: the sudden loss of `socrat-1`, November 21, 2026](../../records/incidents/socrat-1-loss-20261121.md): the migration to NFS, what came back during and after the loss, alert delivery, and the Descheduler.

## Metric collection, downsampling and node migration (21 November 2026)

| Flow | Computations → physical disk | Condition and result |
|---|---|---|
| Collection | OTel Collector → Prometheus on `socrat-0` | The only scraper, base interval 5s; OTLP ingestion into local WAL/TSDB. Retention 12h; do not enable a parallel scrape of the same targets. |
| Closed raw blocks | Sidecar on `0` → TLS S3 `thanos-workshop` on `socrat-1` | Usually 2h blocks; the shipper journal tracks sent ULIDs. The main Store on `1` reads S3. This is asynchronous shipping, not synchronous WAL replication. |
| Compaction and downsampling | The main Compactor and its working directory on `0` → the same S3 on `1` | Compaction merges blocks of one resolution; downsampling creates raw → 5m → 1h aggregates as blocks age (the usual Thanos thresholds: 40h and 10d). This is not a deletion deadline and not a promise of publication exactly at that moment. |
| Hourly archive | `thanos-cascade` on `3` reads the S3 on `1` → a local 1h archive on `3` | Every hour at `:30`. Only finished 1h blocks; staging, hash verification, atomic publication without overwriting. A separate role reads S3 and writes only markers, without DeleteObject. The separate hourly Compactor has retention 17 520h (730 days). |

**Working-archive policy:** raw ≥5 days while 5m coverage on `1` is readable;
5m ≥90 days while 1h coverage on `3` is readable; 1h on `3` — 730 days. Age counts
from the end of the block, not from upload. An hourly source is released without
waiting 90 days after checking files, metadata, reads through the specific Store
and protecting the parent 5m from re-downsampling/compaction. Migration =
publish → verify → deletion mark; the physical S3 cleanup is done by the
Compactor after 48h. The native retention parameters in the working S3 stay
`0d` deliberately: a deadline without coverage verification does not grant the
right to delete. On a missed interval, label/source mismatch, absent response or
disk pressure, the deadline is not shortened. The separate old NFS archive is
not part of this cleanup.

Implementation: [publication and receipts](../../../charts/thanos/files/hour_copy.py),
[conditions and markers](../../../charts/thanos/files/tier.py), [tests](../../../tests/test_thanos_tiers.py).
To stop new markers set `APPLY_TIER_MARKS=false` in the CronJob template; this will
**not** cancel markers already created. After Store load or compaction, another
pass may be needed. Look for `mark deletion <ULID>` and check the remaining block;
do not treat a successful empty Job as a confirmed deletion.

**Per-segment verification.** For a fresh graph, compare direct Prometheus, the
Sidecar and Thanos Query with identical parameters (see below). For shipping to
`1`, check the new ULID in the journal and the object in S3: this is confirmed by
the stock block `01M7ZQNKDF9JW6PX0TH142HGHX`. For the transfer to `3`, check the
count of confirmed hourly blocks in the `thanos-cascade` log, not just the Job
status: `hourly blocks confirmed 0` means a successful run without a transfer.
The hourly archive is not a replacement for a raw backup.

**One-time migration result.** The old `/var/lib/socrat-thanos` on `0` is empty;
49.58 GiB freed. On `3`, separate from the readable hourly history, lies a
verified compressed copy of 148 original files (13.43 GiB); the temporary copy on
`0` was deleted. This is a pre-cutover snapshot, not a backup of later writes.
[Restore verification and the archive path](../../../deploy/storage/thanos-retire/README.md).

Sources: [Prometheus](../../../charts/prometheus/values.yaml), [Thanos placement and retention](../../../charts/thanos/values.yaml), [cascade schedule and permissions](../../../charts/thanos/templates/warm-cascade.yaml), [hourly block verification](../../../charts/thanos/files/hour_copy.py).

## Gaps in recent Thanos metrics (19 November 2026)

**Reading rule:** the live sidecar Prometheus serves the last 6 hours. Only the
raw Store Gateway (`thanos-store`) has `--max-time=-6h`; the local Prometheus
stores 12 hours, so about 6 hours of overlap remain at the boundary. This is a
read filter, not block deletion. If the sidecar is unavailable, do not rely on
the raw archive as a fallback for the last 6 hours. If retention changes,
re-verify the overlap. Sources: [Thanos](../../../charts/thanos/values.yaml),
[Prometheus](../../../charts/prometheus/values.yaml); fix `69a0a2bf`.

**What happened.** Traffic Light graphs for n8n (920) and VPN (907) showed gaps
in the morning. At 08:00 MSK a `from-out-of-order` block for 07:00–09:00 had
already reached the archive: its boundaries covered two hours, but inside it had
only late points. At the time of the investigation, no regular block for that
period existed in the archive yet. The same panel query with a 60s step gave
different results:

| Source | Result before the fix |
| --- | --- |
| Directly in Prometheus, or through Thanos to the sidecar only | No gaps |
| Raw Store Gateway only | Incomplete series |
| Sidecar and raw Store Gateway together | The gaps reproduce, including without deduplication and downsampling |

**How to check reproduction.** Take the exact panel expression from
[Traffic Light](../../../charts/monitoring-k3s/dashboards/traffic-light.json)
without dropping the freshness check. With identical `start`, `end` and `step`,
compare `/api/v1/query_range` directly in Prometheus and through the Grafana
datasource `prometheus` (it reads Thanos). If the answers differ, in Thanos
restrict `storeMatch[]` first to the sidecar address, then to the raw gateway
address from `/api/v1/stores`, then query both. Compare the values and
timestamps of each series, not just the HTTP status or the presence of a series.
If the series is already missing in local Prometheus, this is a different case:
check collection and delivery; do not substitute zeros.

**Acceptance after rollout:** for 07:15–08:00 MSK, all 46 minute points of each
series of both panels through Grafana matched Prometheus; in the two-hour window
around the read boundary all 121 matched. At a depth of 19–20 hours the archive
returned all 61 points of each series. The panels and their queries were not
changed.

**A separate problem:** in the same hours OTLP senders logged `DeadlineExceeded`;
the n8n exporter reported dropping 673 metric points (not workflow runs). This
is a real delivery error, but not an explanation for the gaps, whose local series
was complete. The cause of the timeouts and the separate VPN skip at 09:16 was
not established.

## Current placement delta —16 November 2026

Grafana and Grafana MCP were accepted on `socrat-5`, the new Grafana claim
`grafana-socrat5`, the old claim on `socrat-1` stale/Retain. Native SSO, existing
identities and a real read-only MCP→Grafana→Thanos query were verified.
[Full acceptance and downtime](https://github.com/alchemmist/homelab/blob/2fd1179442b3c7b05c9049dfa4bbaa47bfbc3790/docs/vm105-grafana-20261116.md).
Prometheus/Thanos and the other backends were not moved by this change. The
owners table below remains useful, but the November 7 snapshot's runtime
statements are not a new acceptance of every component. The Grafana source also
includes `deploy/storage/grafana-socrat5`; current references are in the
Application.

## Historical split checkpoint —7 November 2026

Updated **November 7, 2026**, after the completed Grafana/backends handoffs
(`f4020d1`), the five Prometheus components and runtime checks. This replaces
the early read-only intermediate-split snapshot. It does not declare a new
browser-MFA acceptance, every producer healthy, or independent DR.

## Argo ownership after the split

| Application | Source | Responsibility |
| --- | --- | --- |
| `grafana` | `charts/grafana`, `deploy/platform/grafana/public-entry` | Native Grafana, datasource provisioning, public policy and TV assets |
| `prometheus` | `charts/prometheus` | Only Prometheus, its storage/configuration, shared rules and cluster monitors |
| `alertmanager` | `charts/alertmanager` | Only Alertmanager, routing/config, its own Service/SA/rules |
| `prometheus-operator` | `charts/prometheus-operator` | Controller, CRDs, admission webhooks and operator/reloader rules |
| `node-exporter` | `charts/node-exporter` | Per-node DaemonSet, Service/monitor and its own rules |
| `kube-state-metrics` | `charts/kube-state-metrics` | Kubernetes state export, RBAC/Service/monitor/rules |
| `loki` | `charts/loki` | Logs backend and scoped retention resources |
| `tempo` | `charts/tempo` | Traces backend |
| `pyroscope` | `charts/pyroscope` | Profiling backend and its Grafana integration |
| `monitoring-k3s` | `charts/monitoring-k3s` | Dashboard JSON, rules, probes and related monitoring resources |

All the listed apps are Synced/Healthy. Loki/Tempo auto-sync was restored: the
temporary `automated.enabled=false` was removed; `prune=false/selfHeal=true`
preserved. The old `kube-prometheus-stack`, `prometheus-stack`, `otel-backends`,
`profiling` apps were removed from Git/cluster after clearing finalizers and
handing over ownership. 103 UIDs of existing objects were preserved (including 10
shared CRDs: after the final split their scope is `prometheus-operator`, without
forced tracking annotations). PVC/Secret/Certificate UIDs did not change. Only
the unused ConfigMap `otel-backends` was deleted with UID/resourceVersion
preconditions after checking references. Do not repeat the retirement or re-enable
the old owners. Map and full protocol:
[monitoring-service-split.md](monitoring-service-split.md).

In Grafana, the private agreed SQLite snapshots were reconciled: users/org/
memberships, datasource identities, dashboard UIDs, OAuth links and public shares
preserved. Native OIDC redirect works; public regression 134/134 and TV24/24 over
two IPs passed. Loki/Tempo verified-mTLS `/ready`200, refusal without a client
cert, fresh logs and stored traces verified without printing contents. This is
not a re-acceptance of the physical TV/browser MFA. The new TV layout/JS from the
parallel `832e341`/`757dc18` was preserved.

An app name is not a Helm release or Service name: the pod/service name
`kube-prometheus-stack-grafana` does not return ownership to the old app. Current
manifests:
`deploy/argocd/apps/{grafana,prometheus,alertmanager,prometheus-operator,node-exporter,kube-state-metrics,loki,tempo,pyroscope}.yaml`.

The last aggregate `prometheus-stack` was also taken apart: all 77 resources were
transferred to five independent Applications; the render payload matches fully.
All 8 runtime Pods kept UID/node/readiness/restarts; all 4 PVCs kept their bound
volumes; the 3 target Secrets (including webhook TLS) kept UID **and content**.
Prometheus still finds the previous Alertmanager endpoint. No WAL repair,
operator reinstallation or data migration was needed. Details and source
provenance: [prometheus-service-split.md](prometheus-service-split.md).

## A recorded closeout, not a new migration command

Final split: disarm `652e286` → handover to five owners `78a9336` → aggregate
deletion `bcc93ca` → checkpoint **`0bb4e31`**. On the final snapshot all
**49 Applications**, including `root`, were Synced/Healthy. Meanwhile
`PrometheusTSDBCompactionsFailing` remained firing: Argo Healthy does not mean
WAL integrity. The Watchdog is a separate expected heartbeat.

Final-stage acceptance: **104 profiled tests + 24 pytest subtests**, Helm lint of
the five component charts, an Ansible syntax check; public-access regression
**134/134**. The earlier TV24/24 belongs to the previous Grafana acceptance, not
to a new physical TV test. Do not add up stage results into an invented common
test suite.

The last handoff's private UID/Pod/PVC/Secret-hash/render receipts are kept 0600
in `~/.config/homelab/monitoring/migrations/2026-11-07-prometheus-components/`.
This is rollback evidence without printing Secret contents, not an off-node
backup/DR. Handing ownership back again requires a disarm and removal of the
deletion finalizers;

**do not blanket git revert**, which would delete the new Applications with
active finalizers: it could cascade-delete workloads. An ordinary version
rollback is a new commit in the current owner's source, with data preserved.

## Data and pipeline

- OTel Collector — the sole scraper; Prometheus accepts OTLP with the agreed
  out-of-order window of 30m and NoTranslation. Do not add a second scrape path
  for the same targets and do not “fix” duplicates by deleting historical data.
- Loki3.7.9 / Tempo2.10.10 — Kubernetes workloads, persistent nonroot storage,
  protected backend entrances; the old host units are not the main pipeline.
- Loki retention intent: debug3d / info7d / other14d; scoped marker/temp cleanup,
  not blanket bucket/PVC deletion. Verify versions/settings against the current
  charts.
- The historical metrics migration is finished; the accepted minor loss does not
  license inventing backfill. Thanos raw/5m/1h storage and compaction have their
  own runbooks; a full hourly shipping/DR acceptance was not declared complete.
- Grafana refresh and dashboard range are presentation, not proof of ingestion
  completeness. Do not turn missing telemetry into zero/green and do not hide
  gaps with interpolation.

Sources: [monitoring](monitoring.md),
[logging operations](../logging/unified-logging-operations.md),
[retention](../logging/otel-loki-retention.md), `deploy/monitoring/otel/`,
`deploy/monitoring/migration-evidence/`, current chart values and resource budgets.
Old references to otel-history runbooks absent from this checkout are not
sufficient grounds to run migration/delete scripts.

## Software update alerts

Third-party images are compared with the newest stable GitHub release by `monitoring-update-watch` in `charts/monitoring-k3s` (`updateWatch.targets`). The Prometheus rule is `SocratSoftwareUpdateAvailable` (`for: 15m`, severity warning). It uses the same Grafana alert graphs, Alertmanager, n8n workflow and socrat-bot `POST /v1/messages` path as other warning alerts. This is one cluster-wide alert, not one instance per app: its value counts apps with an update. The primary graph shows one step line per catalog app (0 = checked and current, 1 = newer stable release, missing = unknown). Version changes do not create new lines. A new release appears after the next successful lookup, not at publication time. While the alert is already firing, another app switching to 1 changes the graph and count, not the alert identity. Nothing in this path upgrades a workload.

Installed version comes from the running container tag when the tag contains `x.y.z`. Digest-only images use `updateWatch.targets[].current`, which must be changed in the same commit as the chart pin. Open WebUI and 3x-ui are in the catalog. Xray is not a separate Deployment; it ships inside the 3x-ui image. Apps released from this homelab's own repositories are not in the catalog.

`SocratSoftwareUpdateCheckFailed` fires when a lookup stays unsuccessful for 6 hours. A failed lookup does not emit an update alert. SearXNG releases do not currently expose a stable `x.y.z` tag, so that target stays on the failed check rather than an update alert.

## Placement — an observation, not an eternal contract

At the read-only snapshot: Grafana/Loki/Tempo/Pyroscope and Grafana MCP on
socrat-1, Prometheus on socrat-0. The wiki and Authentik are also on socrat-0.
Do not use the old “all monitoring on1 / wiki on3” tables for disk work or
restarts. Scheduler/nodeSelector/PV affinity must be checked per application.

## Dashboard, TV and APIs

Dashboard JSON: `charts/monitoring-k3s/dashboards/`; datasource configuration —
`charts/grafana/values.yaml` and templates. Alerts/probes — monitoring-k3s. Do not
confuse native per-app authorization with the infrastructure namespace and the
read-only MCP identity.

The public traffic light is the only explicit share, not an anonymous org Viewer.
Headerless TV geometry was updated in `832e341`; the former hard-coded panel
positions from the October notes are not the current layout specification. The
sources are the dashboard JSON,
`deploy/platform/grafana/public-entry/files/traffic-light-inset.js` and
[TV design](../../applications/android-tv/traffic-light-tv-design.md), not JS
injection into Fully. The later documented acceptance (`29f41d9`): dashboard
`832e341`, kiosk parity `757dc18`, four real-browser cases (public/authenticated
kiosk ×1920×1080/1440×900), 40 targeted tests and24 public access checks. This is
evidence of a different completed acceptance, not a repeated browser test by this
doc task. Physical remote/cold boot and an independent external ISP were not
verified here.

Grafana MCP — a public verified-TLS endpoint with a separate bearer and a
Viewer/read-only native identity. The Secret must not be committed/printed;
browser MFA does not fit a machine API. Use MCP/API for reads; the browser is
for visual acceptance.

[Deployment](../../platform/delivery/cluster-deploy.md) · [network](../../network/README.md) · [TV](../../applications/android-tv/README.md) ·
[SPI](../../applications/spi/spi-incident-triage.md) · [n8n](../../n8n/n8n-workflows.md).


## Separate incidents noticed while closing the split

- **PrometheusTSDBCompactionsFailing**: in the 2026-11-07 09:00 UTC logs, checksum
  corruption of WAL segment `00001786` during checkpoint/truncation. That is
  before the 10:20 UTC disarm of the split; the Prometheus Pod was not restarted
  by the migration. Ready/Argo Healthy does not prove WAL integrity. The alert
  was not silenced, WAL/blocks were not deleted or rolled back; a separate safe
  investigation with a backup before repair is needed.
- **Blog**: the parallel robot release `8b3e079` recorded the Harbor digest
  `sha256:c476e069de95fd3daafaac09f1f1fcf58f65230deaecb6740b5b9cf84aae8c99`,
  which the registry returns NotFound. The new pod is in ImagePullBackOff; the
  two old ones keep serving. This is a separate release incident, not a result
  of the Grafana/Loki/Tempo move. Soon the independent robot release
  **`f485c74`** recorded an available digest; re-check after `4124691`: blog
  **Synced/Healthy**. This incident was closed by a parallel release, not a
  monitoring repair. The foreign release during the split was not rolled back
  and the image was not manually substituted.
- Root showed a separate Rancher metadata drift: Argo-managed PostDelete
  finalizers were missing in Git. The manifest declares the **already existing**
  finalizers; hooks were not removed and no ignoreDifferences were added. Rancher
  runtime, MCM/Fleet and chart values were not changed by that.

The Watchdog with severity=none is an expected heartbeat, not proof of the
absence of other alerts. Do not declare the whole cluster healthy from green new
Applications.

### Public status redirect repair

`status.alchemmist.xyz/` was incorrectly redirecting to
`http://status.alchemmist.xyz:8080/status/socrat`: the stock nginx policy proxy
built an absolute redirect from the internal listener8080 after TLS termination.
`absolute_redirect off` was added to `charts/uptime-kuma/files/kuma-policy.conf`:
Location is now the relative `/status/socrat`; the HTTPS/public origin is kept.
Only the policy config and the checksum-triggered proxy rollout changed, not the
Kuma DB/PVC, native auth or UI gateway. The reviewed ownership fixture updates
only the policy ConfigMap and the proxy Deployment; the original handoff version
remains in Git history.

### socrat-2 watchdog incident and recovery — 2026-11-07

[Forensic report](../../records/incidents/vpn-incident-2026-11-07.md): four failed TLS/WebSocket
checks from20:02:22 MSK caused the VPN watchdog to stop k3s at20:03:56 and fence
VPS Pods. This was an explicit stop, not a proven k3s crash/OOM. Exact first
handshake error was discarded by the old helper; timeout/certificate/false-positive
explanations remain unproven. Native fallback became healthy but intentionally did
not auto-failback.

Corrected stale live `agent_unit` (agent→server); isolated Kubernetes-start timeout
from40s to180s after first controlled failback timed out. Added safe probe error
classification, without private paths/tokens. Threshold4, TLS verification and
fencing safety retained. Controlled second failback succeeded: all4 nodes Ready,
x-ui/Traefik1/1, native units stopped, timer resumed. Authenticated public Trojan
TLS/WebSocket → HTTPS200 verified. Pods were replaced after fencing; DBs were not
reset/restored. Private backup/journal paths and limitations are in the report.


### Watchdog hardening after the incident

Role/Python defaults now select `k3s.service`, consistent with socrat-2's etcd-only
server role. Legacy `k3s-agent.service` remains only a compatibility fencing/guard
reference or historical context; do not delete it from the safety lists.

After4 scheduled failures, watchdog requires2 further bad samples1s apart before
fencing; recovery cancels activation and resets failures. Native startup has30s
monotonic/boot-scoped warm-up (still unhealthy if checks fail), and native restarts
also require confirmation. Failback checks target identity before stopping VPN;
failed server startup attempts immediate native rollback. No automatic failback,
TLS weakening or alert muting. Safe last-failure receipt retained outside Git.
See [current protocol/defaults](../../network/vpn-egress/vpn-failover.md#hardened-detection-and-service-identity).

Hardening applied live without restarting k3s, x-ui or Traefik; their current Pod
names were retained, all4 nodes Ready, native primary/Caddy inactive, timer active.
Post-update scheduled probes healthy/failures0.63 focused tests +2 subtests and
Ansible syntax-check pass. Error/confirmation/warm-up/rollback branches are unit
and fault-injection tested; no additional production outage was deliberately
triggered to exercise the new fencing policy. Private installation receipts are
under `/var/lib/homelab-vpn-failover/hardening/2026-11-07/` on socrat-2.

### 2026-11-09 recovery continuation

Full receipts: `docs/records/incidents/cluster-recovery-20261109.md`. Old WAL00001786 checksum fault
predates night outage (already Nov7).13:34UTC exact one-bit repair applied atomically
without restart/truncate/replay: pinned native decoder6409 records valid and all
11716 affected samples independently match raw Thanos history exactly; off-host
original/candidate SHA verified. **Next native checkpoint and3h alert expiry still
pending**; no restart shortcut. Physical bit-flip cause unproven.

vLLM actual kubelet allocation/request10Gi,24Gi limit, same process; natural observer
13:48 success and critical alert cleared. Four power/fresh-quorum safety rules live
(source has native promtool tests; verify actual evaluation). Node3 native durable
storage compaction preserved all queues/cursors with consistent backup/off-host
copy; queue25→9MB, delivery continues/refused0, HDD I/O pressure remains under watch.
`fsync=true` retained. fwupd metadata service naturally success/no firmware install.
Three historic failed Job objects retained; current natural replacements succeed;
no alert masking or deletion solely for green.

14:40 continuation: node3 queues fully drained; explicit1s filelog polling and
infinite receiver retries validated/applied only there with5.22s agent-only lifecycle
and new consistent archive. fsync kept. HDD mean60s17% vs39% after-drain baseline;
actual5m PSI I/O6.9%, contention alert naturally cleared; native Loki522 fresh
records/5m. Three healthy etcd voters/common-revision hash agreement rechecked;
new159MB consistent snapshot/current17-client native panel backup both off-host SHA
verified. Original16 identities/85 bindings unchanged;1 external addition not
attributed or deleted. Backend validator now accepts only exact redundant nb-host
allowance; public eth0 deny untouched and externally re-proven. Next native WAL
checkpoint remains the remaining functional gate;3 old failed Jobs retained.

**15:10UTC final WAL gate accepted:** normal Prometheus checkpoint1786→2388 completed
in9m54s; checkpoint2388 exists, same Pod/all container IDs, no new compaction error
in native watch. No forced restart/truncate/replay. Historical3h counter alert still
visible;3 old failed Jobs have no TTL and remain intentionally unchanged.15:15:
all4 nodes Ready/no active nonready Pods; strict-TLS LMS303, Umami heartbeat200;
observer/SPI/Wiki/Thanos natural successes fresh. Node3 I/O5m5.4%, alert cleared.
Native checkpoint/functional receipts supersede earlier pending-gate notes above.


## Wishlist — 2026-11-16

Private8001 metrics via the existing native Collector; own renewable mTLS leaf
and browser/backend OTel are live. Actual anonymous15-span browser→Traefik→app→DB
trace, Loki correlation and Thanos up/inventory success1 accepted. Dashboard
`wishlist-performance`; no second sampler/scraper, public OTLP or CA key copying.
Exact Collector egress to Wishlist8001 is required. Existing extraneous
ConfigMap/wishlist is NOT pruned; desired resources reconciled, not blanket Argo
health. Real user slow upload/production login remain outside canary acceptance.
[Runbook](wishlist-observability.md) and its JSON evidence are authoritative.
