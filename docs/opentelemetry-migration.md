# OpenTelemetry migration

## Status — production cutover 2026-10-31

**Production realtime metrics now use stock Collector → native Prometheus OTLP.** All 78 baseline source identities were fresh and healthy; their ordinary target labels matched the frozen pre-cutover baseline before subsequent legitimate workload rollouts. Prometheus no longer owns scrape targets, binds its native receiver only to pod loopback, evaluates at 5s and retains the original PVC/head/history. The stock Collector sidecar handles authenticated mTLS ingress on private WireGuard, never a custom compatibility gateway. Grafana datasource UID `prometheus` remains unchanged and its live Thanos query independently returned 78 fresh sources.

Persistent full host agents collect new journal/container logs on all four nodes. Loki (14 days) and Tempo (7 days) run on socrat-1 with native mTLS on private addresses. Real Traefik ingress traces are searchable in Tempo, with AlwaysOn ingress sampling and the tested tail-sampling gateway. This is not proof of internal SDK instrumentation for every application. Grafana has native `loki` and `tempo` datasources with certificate-authenticated backend access. The immutable production log cutoff is `1793447920650563000`; old log bodies were not imported. Native host sources replace the retired node-exporter DaemonSet, retaining explicitly frozen legacy aliases.

The operator explicitly accepted data-loss risk and authorized production cutover. Positive memory failures remain unresolved and source integrity is **not** falsely certified. Other unverified policy flags remain false. Original history was preserved; no isolated reimport has been published alongside an original. The older backup has six complete canonical roundtrips (17,456,856,414 samples), with the seventh still processing. This is not all-current-history certification. A dependent native-query continuation failed an SSH transfer, retained its failed artifacts, and was restarted as a single bounded keepalive-enabled retry; two native Query receipts had already passed.

A real persistent 72-hour production observation timer now runs on healthy socrat-1. It checks actual native ownership as well as fresh sources, backend mTLS readiness, log coverage, trace availability and managed service failures. Observation gaps/configuration changes reset its healthy window; elapsed time cannot be fabricated. The ownership-check upgrade intentionally reset the initial window. Consult `/var/lib/homelab-otel-soak/state.json`, not an old estimated finish time. **The production switch is done; whole migration/history verification and the full elapsed soak are not declared complete.**

Evidence: `migration-evidence/production-cutover-20261031.json`, `operator-risk-acceptance-20261031.json`. No commits.

The following implementation/history sections are chronological records, not claims that their older pre-cutover status is still current.

Implemented:

- A read-only live inventory and fail-closed cutover preflight.
- Versioned telemetry requirements and conservative initial resource budgets.
- Removal of automatic Prometheus PVC deletion from the stack deployment role.
- Refusal of destructive relocation even when the legacy `monitoring_prometheus_relocate=true` flag is set.
- Removal of automatic retired Thanos directory and object-store Secret cleanup.
- Regression tests for capacity, inventory privacy, prerequisites and preservation of historical storage.
- SHA-256 checked native block archives and a controller-restoring snapshot/backup orchestrator with a resumable replica-copy phase.
- Verified backup evidence and a second independent copy on socrat-3.
- An isolated TSDB/standard-OTLP/TSDB tool with synthetic and real-data pilot verification.

Existing unrelated and earlier changes in the working tree are not part of this implementation.

## Agreed contract

The target is OTel collection and OTLP delivery for metrics, logs and traces on existing nodes. Prometheus remains the recent-metrics TSDB and rule evaluator; Grafana keeps datasource UID `prometheus` pointing to Thanos Query. Thanos shipping, raw/5m/1h storage, downsampling, coverage checks and cascade retention remain unchanged.

Host collectors run as systemd agents, including on the VPS, independently of K3s. Third-party exporters may keep `/metrics` and textfile interfaces; their collection and delivery go through OTel. New owned applications use OTel SDKs. Third-party applications are not forked for tracing.

Default managed-source collection, rule evaluation and dashboard refresh are 5s; scrape timeout is 4s. These are migration targets, not claims about current configuration. Log retention is 14 days and trace retention is 7 days. Tail sampling retains errors and traces taking at least 2s, plus 10% of other traces, with a 30s decision window.

Raw historical metrics representable in standard OTLP are exported and reimported into isolated storage. Downsampled blocks and nonrepresentable raw semantics remain native, with explicit exceptions. There is no custom lossless OTLP profile, reconstructed historical tracing or production reimport of old samples. The original archive remains readable and is not deleted. Historical records containing secrets or sensitive personal data are excluded from searchable imports and remain only in protected originals.

The TV dashboard grid remains 24×15, with existing IDs and positions. No CSS/JS patches or new public telemetry endpoints are permitted. Existing Alertmanager configuration intentionally discards notifications; an alert is not a promise of delivery.

## Reproduce the preflight

Run from the repository root with working SSH aliases for all four nodes and read-only Kubernetes access via `socrat-0`:

```sh
python3 scripts/otel-migration-preflight.py collect --output /tmp/otel-inventory.json
python3 scripts/otel-migration-preflight.py check --inventory /tmp/otel-inventory.json --output /tmp/otel-capacity.json
```

Files are created exclusively with mode 0600. Existing output files are never overwritten. Use new filenames for subsequent runs. Collection executes only SSH read-only probes and Kubernetes/Prometheus GET requests; it installs nothing and does not restart services.

Exit codes: 0 means success, 1 means cutover prerequisites are not met, and 2 means invalid configuration or a failed inspection. Observations older than 15 minutes, missing nodes, unhealthy targets and invalid resource values fail closed.

The inventory deliberately omits raw effective scrape configuration, bearer credentials, Secret contents, query URLs and application log bodies. It records current capacity, target labels/health/intervals, monitor identities/auth requirements, Prometheus version/settings and metrics-directory byte counts. This is a preliminary source inventory, not the complete verified source registry or the secret-bearing backup manifest.

`deploy/monitoring/otel-migration-policy.json` contains conservative component memory budgets. They are initial planning envelopes, not measurements of this deployment. The gate requires their sum plus a host reserve to fit current available memory. It also requires the stricter of existing disk reserves and 20% filesystem capacity after projected additional storage.

`projectedAdditionalDiskBytes: 0` is intentionally incomplete: `diskProjectionVerified` is false and blocks cutover. It must be replaced with measured backup/export/import, queue, compactor and retention peaks before validation. Prerequisite flags are manual assertions, not proof that those operations ran; set them only with linked, verified artifacts. `backupVerified` links to the completed backup receipt. Disk projection, history roundtrip, current-history source integrity and cross-signal source-registry prerequisites remain false; the source-integrity gate was added after the 2026-10-30 incident described below. This script is an inspection gate, not a deploy authorizer or backup verifier.

## Original memory blocker: 2026-10-28

Read-only live inventory found 78 active scrape targets, all healthy. The Prometheus CR reports version `v3.15.0-distroless`, 5s scrape, 30s evaluation, 12h retention and disabled admin/OTLP receivers.

The reproducible memory gate failed on `socrat-1`:

| Additional component | Initial memory budget |
| --- | ---: |
| systemd agent | 256 MiB |
| cluster collector | 1 GiB |
| trace gateway / tail sampler | 1 GiB |
| Loki | 2 GiB |
| Tempo | 2 GiB |
| preserved host reserve | 512 MiB |
| Total | 6.25 GiB |

Available memory at collection was about 5.37 GiB. This fails the chosen budgets; it does not establish an irreducible memory requirement for these products. Do not silently lower budgets or deploy into swap. Resolve with measured workload profiles or an explicitly revised placement on existing nodes, then repeat the gate. Initial filesystem reserves pass before additional disk projections, but this is not a completed storage-capacity approval.

Local restricted reports:

- `/tmp/otel-migration-inventory-20261028.json`
- `/tmp/otel-migration-capacity-20261028.json`

These temporary files are not durable backup artifacts and are not committed. Their capacity observations expire after 15 minutes.

## Approved placement revision: 2026-10-28

The operator approved moving the cluster collector and trace gateway to `socrat-0`. Loki and Tempo remain on `socrat-1`; each node keeps its systemd agent. The initial placement decision did not reduce component budgets or host reserves. The real-source canary subsequently increased the cluster Collector budget to 1 GiB; the Thanos cascade is unchanged. These are planned allocations, not already deployed services.

A fresh live preflight passed the memory checks on all four nodes:

| Node | Components | Memory required including reserve | Observed available |
| --- | --- | ---: | ---: |
| socrat-0 | agent, cluster collector, trace gateway | 2.75 GiB | 16.68 GiB |
| socrat-1 | agent, Loki, Tempo | 4.75 GiB | 5.24 GiB |
| socrat-2 | agent | 0.50 GiB | 0.78 GiB |
| socrat-3 | agent | 0.50 GiB | 1.04 GiB |

The remaining margin on `socrat-1` is narrow. Capacity must be measured again immediately before deployment; this observation is not a permanent reservation. Initial filesystem checks pass, but measured peak disk projections are still unverified.

Fresh restricted reports:

- `/tmp/otel-migration-inventory-20261028T133316Z.json`
- `/tmp/otel-migration-capacity-20261028T133316Z.json`

At that placement check the overall result intentionally exited 1 because all four prerequisite flags were false. The later backup stage completed and only `backupVerified` was changed to true; peak-disk, whole-history roundtrip and source-registry prerequisites remain false. No prerequisite was bypassed to clear the memory gate.

## Verified backup and real-data pilot: 2026-10-28

Durable backup evidence: `deploy/monitoring/migration-evidence/backup-20261028.json`.

- Prometheus snapshot `20261028T135030Z-6f24d42ec4d8b52d` includes head (`skip_head=false`), seven TSDB blocks and about 1.43 GiB of uncompressed files.
- Thanos source archive contains 13 blocks and about 15.87 GiB of uncompressed files, preserving raw/downsampled resolutions and deletion marks.
- Both shelf archives are verified empty, matching their current state.
- Compressed archives total about 7.6 GiB. Every archived file is SHA-256 checked, and compressed archive SHA-256 values match the prepared source, local copy and socrat-3 replica.
- Local copy: `/tmp/otel-history-backup-20261028T1350`; replica: `socrat-3:~/monitoring-backups/otel-history-backup-20261028T1350`.
- Node-local staging archives under `/var/lib/node_exporter/textfile_collector/otel-history-backup/otel-history-backup-20261028T1350/` are retained, with private owner/named-user ACLs. Snapshot directories and failed-attempt partial copies are also retained; no automatic cleanup was performed. Account for them in disk projections.
- Snapshot API is disabled again; all three compactors are back at their original replica counts and the cascade CronJob is unsuspended. A post-backup read-only inventory found all 78 scrape targets healthy.

The first direct Kubernetes-exec archive transfer failed at its connection lifetime; its partial copy is not a backup. A second attempt encountered the hardened pod's lack of CHOWN capability. Both attempts restored controller state. The successful transport prepares verified gzip archives on node-local storage, grants read access only to the existing authorized host user through POSIX ACLs, and copies over SSH. macOS rsync compatibility and longer verification timeouts were corrected. Replica-copy retry does not create another snapshot or restart Prometheus.

Backup commands mutate temporary controller settings and can restart Prometheus. Run only after a fresh capacity check, not as a routine read-only inspection:

```sh
python3 scripts/otel-history-backup.py --execute --destination /tmp/NEW_UNIQUE_RUN --replica-host socrat-3
python3 scripts/otel-history-backup.py --execute --resume-copy --destination /tmp/EXISTING_VERIFIED_RUN --replica-host socrat-3
```

`restore-state.json` and `restoration.json` record the previous settings and restoration outcome. If restoration fails, the ConfigMap lock remains; manually restore the recorded state before any retry. A process killed with SIGKILL or loss of the control host cannot be guaranteed automatic cleanup. The backup is a verified cut of history, not continuous replication of later samples.

Pilot evidence: `deploy/monitoring/migration-evidence/history-pilot-20261028.json`; tool instructions: [historical OTLP tool](../tools/otel-history/README.md).

The earliest copied snapshot block successfully roundtripped the selected metric `node_cpu_seconds_total`: 483,840 samples, identical canonical labels/timestamps/float-bit hash. This is explicitly a subset, not a full converted block. The initial exporter refused the newest block because of stale markers. This was an implementation limitation, not a limitation of standard OTLP, and has been corrected using `NoRecordedValue`. The complete newest block now passes canonical verification; originals remain unchanged. A source block can contain over 235 million samples, so bulk OTLP conversion must be capacity-profiled rather than inferred from archive bytes. `historyRoundtripVerified` remains false.

## Metrics registry and archive-wide verification: 2026-10-28

New reproducible tools:

```sh
python3 scripts/otel-source-registry.py --output /tmp/NEW_PRIVATE_REGISTRY.json
python3 scripts/otel-history-migrate.py --binary /tmp/otel-history --backup /tmp/otel-history-backup-20261028T1350 --workspace /tmp/NEW_ISOLATED_WORKSPACE --classify-only
python3 scripts/otel-history-migrate.py --binary /tmp/otel-history --backup /tmp/otel-history-backup-20261028T1350 --workspace /tmp/EXISTING_ISOLATED_WORKSPACE --resume --max-blocks 1
```

The registry accounts for 20 monitors (17 selected), 78 healthy active targets, all four nodes' textfile producers, 270 live rules and 18 provisioned dashboards. It preserves target label names and hashes the actual monitor specifications and consumer expressions. Credentials, sensitive paths and URL parameters are redacted. Unknown jobs, active targets without selected monitors, invalid endpoint indexes and missing producers fail closed. Excluded Fleet monitors remain inventoried; they are not activated automatically.

Observed frequencies differ from global defaults: 64 targets scrape at 5s, ten Thanos/LLM targets at 30s, and four cAdvisor endpoints at 10s. GPU source refresh is 15s, disk measurement refresh is 30s, and VPN source refresh is 5s. These are current observations, not changes made by the migration. The registry also records that current node-exporter is a Kubernetes DaemonSet: host-independent VPN collection needs an independent exporter/source as well as a systemd OTel agent.

`source-registry-20261028.json` verifies the metrics inventory only. Cross-signal log/trace source coverage, complete metric-family label contracts, effective auth translation and live canary compatibility still need validation; the overall `sourceRegistryVerified` gate remains false. Provisioned ConfigMaps are inventoried, not unprovisioned dashboards edited directly in Grafana's database.

`history-classification-20261028.json` accounts for every archived occurrence. Seven non-overlapping active raw blocks contain 18,500,148,016 samples in XOR chunks and are representable using standard numeric OTLP. Three downsampled blocks stay native. Four bucket deletion marks and six snapshot ranges proven covered by active raw compactions using both compaction ancestry and time coverage remain explicitly recorded; bucket marks are not incorrectly applied to snapshot copies. Chunk capabilities are not canonical roundtrip proof.

`history-whole-block-20261028.json` records the first complete block roundtrip: 235,173,517 samples, 22,716 stale markers, unchanged canonical digest `7f7fac361193bea3f23f53bcdb40ceeef2495f724e3d0d86ecbc486fd371088f`. Compressed OTLP is 1,703,500,265 bytes versus 216,144,711 source bytes and 207,173,116 restored bytes. The seven-block estimate from this one ratio is about 124.8 GiB of OTLP, not 17 GiB inferred from native files. It is an estimate, not a verified final budget; logs, traces, queues, retained failed copies, index overhead and staging must be added. Do not put the entire export/import peak on socrat-0 without verifying its 20% free-space floor. Historical export storage and workers can be separated across existing nodes, with verified transfer before releasing any successful scratch copy; failed artifacts and originals are never automatically removed.

Stale markers use standard `DataPointFlags.NO_RECORDED_VALUE_MASK`, not a private extension or serialized TSDB chunks. A test passes the exported protobuf through the pinned Prometheus 3.15 OTLP translator and checks original labels, timestamps and exact float bits. Native histograms remain unsupported by this offline exporter and must be preserved as explicit native exceptions if encountered. The scanned active blocks contain only XOR chunks.

The initial full-block run timed out after 30 minutes during final verification. No worker remained running. The exporter and completed import were retained, then verified without reimporting or overwriting them. Profiling showed repeated per-sample label rendering/reflection and attribute allocation. Caching immutable per-series prefixes/attributes keeps the canonical format unchanged. On the 20,000-sample benchmark, walk time fell from 7.91ms to 1.08ms and allocations from 100,357 to 358; export time fell from 40.60ms to 28.52ms. These are fixture benchmarks, not whole-history throughput. The resumed full 235-million-sample verification completed in 40.38s with about 228 MiB maximum RSS; the complete coordinator recovery took 50.08s.

Archive coordination verifies source archives and every extracted file, excludes already-covered snapshot ranges, checkpoints completed blocks and validates a completed import after interrupted verification. An incomplete export can now be resumed explicitly: every reused gzip batch is decoded and compared with freshly reconstructed source protobuf before it contributes to a new manifest. A corrupt or different batch is retained and fails closed. Incomplete TSDB imports still require inspection; they are never automatically overwritten. `--max-blocks` bounds new whole-block roundtrips; the default export byte cap is 4 GiB per block. The multi-billion-sample blocks require a measured larger cap and an appropriately budgeted worker before bulk conversion. A changed binary requires `--revalidate-classifier`, which verifies completed roundtrips before replacing cached classifications.

Snapshot blocks do not themselves carry the sidecar's external labels. Before serving a restored snapshot through an isolated Thanos Store, explicitly bind and verify its original Prometheus external-label context. Current raw archives consistently carry the expected Prometheus/replica labels, but that does not substitute for a live shadow-query regression. No reimported block has been added to production Query. `historyRoundtripVerified`, `diskProjectionVerified` and overall `sourceRegistryVerified` remain false.

## Continued execution and resolved host access: 2026-10-29

The remaining six raw blocks are now running in an isolated background job. This is processing work, not a completed migration. The first operation exports `01M5P6GGQM3K9NAF43KP5JX3JW` (4,606,695,568 samples); one earlier complete block remains verified. Evidence: `migration-evidence/history-worker-20261028.json`. No production configuration has been changed by this continuation.

The job pins the Go executable by SHA-256, detaches its process session, logs privately and writes `result.json` with the actual exit code. The coordinator holds a nonblocking filesystem lock for the whole workspace so a second writer cannot corrupt progress. It preserves the 20% filesystem reserve before each block, allows at most 64 GiB compressed output per block, and has a 12-hour timeout per export/import command. `GOMAXPROCS=2` and `GOMEMLIMIT=2GiB` limit concurrency and set a soft Go heap target; they are not a hard RSS/cgroup limit. The observed export RSS was about 492 MiB. Final import peak memory is still unmeasured. A separate private `otel-history-observe.py` observer now samples only pinned Go children in the job process group every ten seconds, by phase/block, and stops when the supervisor disappears or publishes its result. `resource-observation.json` records sampled RSS peaks, not a hard limit or proof that short-lived peaks were captured.

```sh
python3 scripts/otel-history-job.py launch --binary /tmp/otel-history --backup /tmp/otel-history-backup-20261028T1350 --workspace /tmp/otel-history-classification-20261028
```

Do not launch another job into the active workspace. Active run: `/tmp/otel-history-classification-20261028/jobs/20261028T192732Z-07ee217d`; its request, log and final result are private. `state.json` records the current operation and verified block receipts. Verify process identity and the workspace lock when checking liveness: an old PID, missing result file or `currentOperation` alone does not prove that a worker is still running. The process survives command-session termination, not a control-host reboot. Partial export resumption verifies every reused batch against the original source. A controlled upgrade retained 535,574 existing batches, after checking the final batch CRC, to fix numeric ordering across the million-batch filename boundary. Partial imports and mismatched/corrupt batches still require inspection; no automatic cleanup or reboot recovery is claimed. Temporary control-host files are not durable archive replicas. Verified originals on socrat-3 remain intact; converted artifacts still need verified durable replication and the agreed retention period.

Read-only signal inventory (`scripts/otel-signal-inventory.py`) examined 136 container sources over a ten-minute window, with a maximum 16 MiB per-container read. It saved counts and tracing environment/flag names, never log bodies or environment values. 135 sources were readable without truncation; one old failed system-upgrade-controller container had no accessible API log. Observed container log traffic was about 8.95 kB/s, a lower bound rather than a peak or 14-day storage forecast. Privileged journal reads are now verified on all four nodes. Fresh journal counts are merged with container counts only from private, controller-owned, non-symlinked evidence younger than 15 minutes; truncated, malformed and unprivileged observations fail closed. The October 29 window observed about 8.96 kB/s of container traffic and 6.18 kB/s of serialized journal records. These windows are not a peak-rate or retention-capacity approval. Actual trace rates and delivered spans remain unmeasured. Latest evidence: `signals-20261029.json`.

Grafana MCP independently confirmed that the live dashboard database contains exactly the 18 provisioned UIDs, with no additional or missing UIDs. This closes the inventory gap for unprovisioned dashboard identities, not query-content equivalence or migration canary compatibility. Evidence: `grafana-consumers-20261028.json`.

The initial privilege-escalation blocker is resolved. All four nodes returned UID 0 with the operator-provided protected credential configuration; subsequent privileged journal probes also verified root. Evidence: `host-access-20261028.json`. Credential values are not in the repository or command-line arguments. The working controller file is private mode 0600; it is temporary task material, not a production credential-management solution. No privileged Kubernetes workaround was used.

Root access does not bypass resource, archive, source-registry or canary gates. The 72-hour soak has not started.

## Candidate configurations and isolated privacy smoke

`deploy/monitoring/otel-images.lock.json` pins Contrib 0.164.0, Loki 3.7.9 and monolithic Tempo 2.10.10 by verified registry digests, plus a validation-only Prometheus image. `otel-validation-binaries.py` checks manifest and layer hashes and extracts only expected regular binary files, not arbitrary archive paths. `ansible/playbooks/otel-validate.yml` validates all five candidate configurations with the real Linux binaries without starting production services. Discovery is an inert schema fixture, not the final translated source configuration. Evidence: `config-validation-20261029.json`.

Persistent exporter queues use byte sizing: 128 MiB per agent signal pipeline and 256 MiB per cluster/gateway pipeline. Logical queue limits do not establish physical bbolt high-water size, compaction space, inflight memory or retention capacity. Those remain separate deployment gates.

Filelog starts at the beginning so newly discovered pod files do not silently lose their startup records. Both agent and cluster filter against a mandatory, immutable `OTEL_LOG_INGESTION_START_NS` bootstrap boundary; pre-boundary and missing-timestamp records are excluded before Loki. Generate the production boundary once and retain it across restarts and rollouts, rather than resetting it to the current time. The timestamp in the validation playbook is a fixture only. Journald retains persistent cursors. Native originals are not deleted by the filter.

`ansible/playbooks/otel-privacy-smoke.yml` starts a transient logs-only Collector in a separate loopback-only network namespace. It removes production discovery, filelog/journald inputs and network exporters, and writes synthetic output privately. Evidence: `privacy-smoke-20261029.json`. The October 29 run verified authenticated OTLP HTTP delivery, rejection without a client certificate, exclusion of historical and zero-timestamp records, and redaction in plaintext, structured bodies, JSON text, log attributes and resource attributes. Initial test certificates failed Python's strict X.509 checks; corrected CA key usage and leaf authority/subject key identifiers fixed the fixtures without disabling verification. This proves the tested cases, not privacy for every real source, Loki delivery, trace sampling or production readiness. No public listener or long-lived service was created.

## Effective scrape translation and standard OTLP semantics

`scripts/otel-scrape-config.py` translates the actual Prometheus configuration and healthy active targets, not a hand-written approximation. The October 29 bundle covers 78 targets in 54 active pools; empty pools remain excluded. Cluster discovery, metric relabeling and pool names are retained, with source intervals/timeouts set to 5s/4s. External labels are not copied onto source TSDB series. Four local source configurations keep original target labels as explicitly declared compatibility aliases while removing Kubernetes discovery from their runtime source path. Legacy pod/container labels are aliases, not claims about a host process running inside those pods; their acceptance remains a canary gate.

Prometheus API masks inline authorization credentials. The translator resolves their original monitor SecretKeySelectors into three file dependencies without reading Secret values or using `<secret>` as a token. Cross-namespace secret materialization, refresh/rotation and Collector discovery RBAC still require implementation and runtime verification. Two existing TLS asset dependencies also need correct projection. All five effective scrape configurations pass the native Collector grammar check using inert token/CA fixtures; this is not authenticated source delivery. Literal Prometheus `$1`, `${1}` and regex anchors must be escaped for Collector confmap resolution. Evidence: `scrape-translation-20261029.json`.

The operator explicitly approved the standard native OTLP representation and rejected compatibility gateways. The path remains Collector → native Prometheus OTLP receiver, Collector → native Loki OTLP ingestion, and Collector → Tempo. The existing `NoTranslation` Prometheus option is a built-in naming strategy, not a custom wire format; existing Prometheus source metric names are already compatible. Numeric histogram bounds and summary quantiles are compared numerically, not by their string spelling. Ordinary labels, metric names, values, counts, sums and cumulative behavior must still match. No custom receiver, proxy, pull bridge or third-party fork is introduced. Decision: `native-otlp-decision-20261029.json`.

The prior synthetic comparison found native `le="1.0"` and OTLP `le="1"` with identical bucket values. This is an accepted normalization, not a migration blocker. `metrics-label-blocker-20261029.json` is retained as historical evidence but marked superseded and nonblocking. Earlier diagnostic runs observed counter resets and staleness after approximately five seconds; they do not establish real-source p95 latency. They are not presented as a newly executed canary under the updated assertions.

`scripts/otel-metrics-smoke.py` now compares the numeric meaning of the fixture's histogram and summary dimensions, rejects changed ordinary labels or values, and rejects normalization collisions instead of merging duplicate series. It also checks native PromQL histogram quantiles, sums/counts, compatible bucket selectors and counter resets. There is no diagnostic opt-in: this is the intended native OTLP acceptance contract. The revised synthetic runtime test passed, including native PromQL checks; production readiness remains false.

`scripts/otel-query-audit.py` inspected 869 expression occurrences across repository files and rendered pinned charts, including embedded Grafana ConfigMap JSON. The 31 numeric-dimension selector occurrences use either unchanged literals or already compatible stock patterns such as `le=~"1(\\.0)?"`; no query rewrites were needed. The real Prometheus 3.15.0 parser validated 263 rendered rules and eight synthetic canary expressions. This is repository/rendered syntax and selector auditing, not live Grafana content equivalence or live query regression. The stock API-server availability group still has a 3m evaluation override; global evaluation is currently 30s. Their alignment to the 5s contract remains required before acceptance. Evidence: `query-audit-20261029.json`.

The intermittent SSH problem was DNS routing, not a requirement to replace the trusted key. `socrat.alchemmist.xyz` resolves to two IPv4 addresses: port 2222 at `109.173.40.247` matches the existing trusted node key, while the other address presents a different key. A private runtime SSH configuration pins the verified address and retains the existing `[socrat.alchemmist.xyz]:2222` HostKeyAlias with strict checking. Neither DNS nor known_hosts was modified. This override is scoped to migration access to socrat-0, not a permanent inventory change.

## Native real-source and signal backend runtime checks

`ansible/playbooks/otel-real-source-canary.yml` uses a dedicated short-lived discovery ServiceAccount and temporary read-only RBAC, copies only inventoried source authentication and CA dependencies into root-owned files, and runs a loopback-only shadow Prometheus plus native Collector. Source bundles must be fresh and match both the source configuration and translated configuration hashes. The transient systemd unit has a hard aggregate 3 GiB memory limit and 200% CPU quota. Normal and failure cleanup remove this run's temporary RBAC and copied source tokens; originals are untouched.

The real cluster canary passed for 74/74 targets, with all `up` label sets preserved, all three auth references exercised, maximum observed up age 5.407s, no dropped export batches, no memory refusals and no failed scrape commits. Aggregate cgroup peak memory for the controller, Collector, shadow Prometheus and helper processes was 1,064,730,624 bytes. Four independent host sources are outside this check. This does not prove every metric family, all production rules, cross-signal registry completeness or frontend p95. Evidence: `real-source-canary-20261029.json`.

The initial 512 MiB Collector candidate refused real-source data, so its reservation was increased to 1 GiB after verifying about 15 GiB available RAM on the existing node; the memory limiter is 896 MiB with a 192 MiB spike allowance. The shadow backend uses native `storage.tsdb.out_of_order_time_window: 30m` to accept reordering from concurrent delivery. The earlier candidate produced HTTP 400 export drops; the updated native configuration observed none. Production must carry the native window setting and verify Thanos interaction before cutover. No receiver, compatibility gateway or application fork was added. Current Collector exporter IDs use canonical `otlp_http`, not the deprecated alias.

`ansible/playbooks/otel-signals-smoke.yml` and `scripts/otel-signals-smoke.py` test real pinned Loki and Tempo with two native Collectors inside an isolated loopback-only network namespace, under a hard 4 GiB systemd limit. Test executables copied from the verified node cache are rehashed against the controller's verified binaries before root execution. The accepted run demonstrated native OTLP logs into Loki, authenticated queries, log secret removal, rejection of pre-boundary/time-zero records, and native OTLP traces into Tempo. All 32 mandatory synthetic traces (errors, both HTTP-5xx conventions, and slow traces) were kept; 18 of 200 normal traces were retained under the 10% policy. The actual 30s tail decision wait was used. Backend connections without client certificates were rejected. Resource/span/event sensitive attributes and status messages were absent from retained synthetic traces. The gateway drops gen-ai input/output/system-instruction content, SQL query text and exception message/stacktrace fields using native transforms. Evidence: `native-signals-smoke-20261029.json`.

These are bounded runtime tests, not production deployment, proof of real application trace rates, 7/14-day physical capacity, rotation/restart acceptance or the 72-hour soak. Production log bootstrap time remains unset and must be generated only once at real bootstrap. Historical canonical verification and original/reimport Query isolation remain unchanged.

## Remaining implementation, in order

1. Extend the completed metrics inventory to verified cross-signal sources, full series label contracts and effective auth translation. Measure log/trace rates and final disk/memory budgets; recheck the approved placement immediately before deployment.
2. The initial consistent snapshot and second-copy verification are complete. Refresh the backup cut before eventual production cutover if required by the final migration window. A live WAL copy is not a backup. Temporarily stop archive mutation only for the consistent cut, with guaranteed restoration of previous controller state. Do not delete PVCs or enable cleanup.
3. Complete the remaining six raw-block roundtrips using the archive coordinator, with measured byte/worker budgets, and complete exception/compatibility checks (`capabilities`, `inventory`, `export`, `import`, `verify`). Read TSDB samples, not stepped query results. Test unknown types, reset semantics, histogram/summary series, stale markers, special values, overlaps and resumability. Import offline into an isolated bucket, never the live receiver. Keep original and reimported copies out of the same production Query path.
4. Pin and validate OTel Contrib, Loki and Tempo versions and configurations; deploy private authenticated/TLS ingress, systemd agents, bounded persistent queues and separated pipelines. Do not change production scrapes until backup/roundtrip gates pass.
5. Canary metrics into shadow Prometheus, preserving names, ordinary labels, numeric histogram/summary semantics, cumulative semantics and source freshness. Transfer each target to one production owner. Prove `up`, staleness, histogram and rule compatibility before disabling its original scrape. Preserve the rollback configurations.
6. Deploy log collection with persistent offsets, CRI/multiline parsing and privacy filtering. Add Loki/Tempo datasources without changing existing metrics UID or the TV layout.
7. Instrument owned applications in their source repositories and enable supported third-party tracing. Validate trace routing and tail sampling; document services without internal instrumentation. Existing trace data, if any, uses a separate historical pipeline.
8. Test network/backend failures, queue pressure, rotation and restart recovery; test VPN collection with K3s unavailable in an agreed maintenance window. Prove Thanos raw→5m→1h and shelf confirmation on fixtures and naturally eligible live blocks.
9. Require 72 hours of stable operation. Keep originals and rollback configurations. Retain isolated import/export artifacts for at least 14 days after acceptance; deletion requires a separate explicit action.

Cutover acceptance requires representable raw-history equivalence, explicit native exceptions, unchanged cascade policy, complete target accounting, no unexplained duplication or drops, and p95 managed-source change-to-dashboard latency at most 15s in healthy conditions. A successful Helm release or Running pod is insufficient.

## Verification

```sh
python3 -m unittest tests.test_otel_history_job tests.test_otel_signal_inventory tests.test_otel_source_registry tests.test_otel_history_migrate tests.test_otel_history_archive tests.test_otel_migration tests.test_prometheus_relocate tests.test_thanos_cascade tests.test_thanos_shelf tests.test_traffic_light
```

## Latest validation

- 123 focused Python tests for isolated job execution, workspace locking, signal inventory, source registry, archive coordination, archives, migration preflight, relocation safety, cascade and shelves pass.
- Fifteen Go tests, including the Prometheus OTLP translator integration test and race detector, and `go vet` pass with the pinned Go 1.26.7 toolchain.
- The complete 235,173,517-sample block and earlier CPU pilot have identical canonical digests after offline reimport, including standard OTLP staleness flags.
- The broader Python run currently fails six traffic-light checks because `charts/monitoring-k3s/dashboards/traffic-light.json` changed independently during this work: panel 907 is now a stat with height 3 at y=13, and panel 909 has height 3. This migration did not edit or deploy that dashboard. Do not silently overwrite the concurrent change to make tests green.
- Live restoration was rechecked: all three compactors are ready, the cascade CronJob is not suspended, and Prometheus admin/OTLP receivers are both disabled. The cascade has resumed its hourly runs.


## Resumed execution — 2026-10-30

The operator authorized completing the migration, production cutover and subsequent 72-hour soak. This does not waive preservation, exact historical verification, source integrity or resource gates. No production OTel cutover has occurred.

### Bounded historical import

A native macOS CPU sample of the long-running 4,606,695,568-sample import showed extensive GC work. The upstream `BlockWriter` explicitly retains its complete mutable Head until `Flush`; a multi-day source block therefore defeated the soft 2 GiB Go heap target. The profiler reported a peak physical footprint of 28.4G (not the same metric as RSS).

The verified offline Go child was deliberately stopped. Its coordinator recorded failure, released the workspace lock and retained the export. The empty incomplete destination was renamed, not deleted. The replacement importer uses upstream TSDB writers for 2,500,000-sample shards and upstream compaction with fan-in at most 16. Intermediate files remain private and retained; only the final exact canonical check can produce a verification receipt. The source OTLP encoding and canonical digest algorithm are unchanged.

The active pinned job is `jobs/20261030T101212Z-e8071694` in the existing controller workspace. Its initial observed RSS peak was 1,143,848,960 bytes; this is sampled progress, not a hard limit or a complete compaction peak. More than 997 million samples had committed to private shards at the last evidence update. The 4.61-billion-sample block is NOT yet roundtrip verified. Subsequent source changes add positive/maximum point-count checks and a conservative decompressed-input-byte estimate before shard flush; the active pinned executable is not modified in place.

Tests cover series spanning shards, more than one merge level, resets, exact stale/NaN/Inf/negative-zero bits, oversized/empty batches and impossible disk projections. `go test -race ./...` and `go vet ./...` pass. All 111 `test_otel_*.py` tests pass, including the new source-integrity readiness guard. This is not a claim that unrelated TV/dashboard work passes its tests.

### Current source-integrity incident — production cutover blocked

Production raw compactor failures exposed block `01M65MWZVAGM92C51JW43C3SZ7`, covering 2026-10-28 through 2026-10-30, with 6,383,044,052 samples. A read-only audit of a preserved copy examined all 53,139,089 chunk frames and located one invalid CRC: ref 26271230468, `node_scrape_collector_duration_seconds`, 2026-10-29 12:20:01.534Z–12:29:56.534Z. Expected CRC is `9a719326`, computed `46149fc7`. Native Prometheus reading, independent CRC32C and O_DIRECT reads agree. This is an existing source-integrity failure, not a new OTLP conversion exception. The backup cut from October 28 cannot restore that interval, and the live original parent blocks are no longer present.

Both source-bucket and compactor-download copies were preserved separately with per-file SHA256 manifests. An additional archive changed its SHA256 between reads: its first captured identity was `93d9a8878d4199a78e89fe0f93925fe8fc7c151d7fe8c5c29b8a9304ccd24920`, whereas a later source read and the initial controller copy both matched `046e45c6afcda3c13ba7f00a2edf5a84deab72a29f5f4eeaa7288a3d45115279`. One bit in the archive payload for `chunks/000002` differed from the preservation manifest. A separately transferred segment matched its original SHA256 on both hosts. Replacing that segment only in a new controller-side archive reconstructed EXACTLY the first captured full-archive SHA256. The mismatching artifact and originals remain retained. This recovered archive still intentionally preserves the original raw-block CRC fault; it is not a repaired production block.

A durable replica transfer of the verified preservation archive to `socrat-3:/srv/otel-history-preserved/incident-20261030/` is running separately, with full remote SHA256 required before publishing the final filename. Its result is under `/tmp/otel-integrity-preserved-20261030/replica-result.json`; do not claim success without checking it. Controller `/tmp` is not durable storage. Neither timestamps nor these observations establish the physical root cause. A bounded kernel probe found no matching hardware/EDAC/storage I/O errors among 826 messages; SMART tooling was absent. This does NOT establish hardware health.

`historySourceIntegrityVerified` is explicitly false and fail-closed in preflight, so a successful roundtrip of the older backup cannot inadvertently authorize cutover over a damaged current source. No checksums were rewritten, samples fabricated/dropped, production blocks repaired/deleted or historical verification relaxed. Recovery requires a known-good copy covering the affected interval or a separately agreed incident resolution; do not silently turn this into an OTLP unsupported-type exemption.

### Resource and remaining deployment work

Fresh preflight also rejects the `socrat-2` agent budget: available memory is below the planned 256 MiB agent plus 256 MiB reserve. Do not clear this by lowering reserves without measurement. Disk projection, complete historical roundtrips, cross-signal registry/instrumentation, all four independent host exporters/agents, durable TLS/credential lifecycle and failure tests remain incomplete. Restored raw blocks also need isolated Thanos tests for external labels, physical file inventories and compaction lineage before they can be served. Preserve UID `prometheus` and keep originals/reimports of a range outside the same Query path.

Evidence: `history-bounded-import-20261030.json`, `thanos-source-integrity-20261030.json`, and `preflight-20261030.json`. The 72-hour production soak has not started. No commits were made.


### Operator-approved historical loss and subsequent read-instability blocker

The operator explicitly accepted up to one day of missing historical metrics if no good backup exists. This resolves the missing-backup decision; it does not authorize ignoring new corruption. The implementation is narrower: one exactly identified chunk, 120 samples of `node_scrape_collector_duration_seconds`, approximately ten minutes on October 29. No whole day was removed.

A separate `recover-chunk` command pins the complete captured input SHA256 inventory and corrupt-chunk identity, checks that the original CRC mismatch is precisely the approved one, and writes a stock TSDB tombstone on a new private copy only. Upstream compaction produced `01M66BZJJH7AX3HTZFRZD02SXP`. Both independent canonical passes matched: 6,383,043,932 retained samples, SHA256 `0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209`. No unapproved samples changed, checksums were not rewritten, and originals remain retained. This block is not yet production-published or native-Thanos-query verified. The pinned offline recovery completed successfully; newer source code closes its source mmap before the target pass to reduce overlapping mmap residency, without modifying the already finished pinned binary.

The original preservation archive is now durably verified on socrat-3, including an independent repeated full SHA256 after the transferring client's final SSH timeout. Preserve that failed client result as evidence; reconcile it with the successful remote receipt rather than retransferring or claiming the original process returned success.

The newly recovered candidate archive has controller SHA256 `fa4a4d5ae5f6c1fdca7f4825fa32d0e83c5b1a5dc2e2f60e6715dcefa46f0c2e`. Its first ordinary cached read on socrat-0 instead gave `e2a115562cf1c49a077baaa3e00ea722a21bebb1fcf0252cbfbb566e1b1b17a0`; one member (`chunks/000006`) disagreed. O_DIRECT reading of the same archive matched the controller. File-scoped `POSIX_FADV_DONTNEED` restored the correct ordinary-read hash temporarily, without rewriting content or dropping global caches. The cached discrepancy recurred with SHA256 `0c44b06222905a79973559a809d5ea102ac499773b1de68cb5aa98e536a3d06f`, while direct reads still matched the controller and inode/size/mtime/ctime were unchanged during paired reads. Native compatibility execution therefore failed closed before extracting/publishing the candidate. Do NOT rerun with disabled hashing, assume transport success from file size, or clear `historySourceIntegrityVerified` on the basis of the loss authorization.

Read-only NVMe SMART reports critical warning/media errors/error-log count all zero. A separately allocated and mlocked 256 MiB anonymous-memory test completed one pass without failed comparisons, limited to 50% of one CPU and 768 MiB cgroup memory. Neither establishes whole-machine memory/storage health, and the physical/kernel cause is not established. Native diagnostic packages `smartmontools`, `nvme-cli`, `memtester` were installed with package-daemon startup prevented; no node/service reboot was performed. A full offline memory/hardware investigation needs an explicit maintenance window because socrat-0 also hosts critical services. Production replacement/cutover remains blocked on recurrent read integrity, independently of the permitted old historical gap.

The separate capacity precondition improved without changing retention or memory reserves: `otel-capacity.yml` moved only `gitjob`, `helmops`, `capi-controller-manager` and `rancher-turtles-controller-manager` to allowed large nodes (all selected socrat-1). Both destination nodes' required images were already cached. All four native rolling updates completed with `maxUnavailable: 0`; per-controller rollback state is private under `/var/lib/otel-migration/capacity-20261030T1225`. No PVC/hostPath/NFS workload, VPN, Traefik or user application was moved. Socrat-2 available RAM was 658,325,504 bytes afterward, above the current 536,870,912-byte agent-plus-reserve floor. This is not a complete RAM/retention/queue projection. Reapply managed placement after controller-chart upgrades and remeasure before deploying agents.

Evidence: `history-approved-recovery-20261030.json`, `source-read-instability-20261030.json`, `capacity-placement-20261030.json`. Tests: 115 focused Python tests, Go race tests/vet, capacity-playbook syntax and diff whitespace checks passed. The earlier older-backup import continues independently on the controller; neither that background work nor this approved native recovery is a production cutover or the start of soak.

### Authorized maintenance: expanded memory test FAILED — 2026-10-30

The operator authorized a maintenance window. Before quiescing writers, a native etcd snapshot was saved privately on socrat-3 (`pre-otel-maintenance-20261030T1338`); snapshot contents and server tokens were not exported. Original Prometheus/compactor/store replica counts and cascade suspension state were saved both on the controller and under `/var/lib/otel-migration/maintenance-20261030/state.json`. SSH/K3s boot enablement and independent SSH access to socrat-1 were verified. The original and recovered historical artifacts remain retained.

The first quiesce wait included terminal Succeeded pods incorrectly, timed out and restored saved controller state automatically. The wait was corrected to ignore terminal records, without deleting them. The second quiesce succeeded: Prometheus CR replicas 0, raw compactor/store replicas 0, cascade suspended. This is an explicit maintenance outage: new production metrics are not collected while Prometheus is stopped. Remote 5m/1h shelves and other node applications were not deliberately stopped.

With more than 8 GiB available (preserving a 4 GiB margin), stock `memtester 4096M 1` tested a separate 4 GiB allocation under a 6 GiB cgroup memory limit, CPU quota 200%, and 2400-second runtime bound. The whole allocation was successfully mlocked. It completed with exit code **6** and **14 FAILURE messages**, in 86.561 seconds, memory peak 4 GiB with no swap. These are reported comparison failures, not a count of unique defective DIMMs or physical cells. This is positive evidence of an unstable memory data path independently of file/network I/O. A specific DIMM, memory controller, CPU, motherboard or firmware cause is not yet isolated. The earlier negative 256 MiB test and zero SMART errors do not override this result.

Maintenance progression stopped at its explicit failed-test guard. The node has **not** been rebooted, BIOS settings were not changed, and metrics writers remain paused rather than automatically re-enabled over failed memory. Current desired state was checked from the live API after failure. Other applications on socrat-0 still operate and may also be exposed to the same integrity risk; this containment only pauses the explicitly scoped observability components. Do not describe the server or its application databases as healthy based on this limited containment.

SMBIOS reports two 16 GiB DDR4 modules in DIMM_A1/DIMM_C1 at 2666 MT/s and array Error Correction Type None. SMBIOS reporting is not an independent ECC test and is not proof of which module failed. A real boot-time memory test requires console access and an offline maintenance plan; do not install an unattended diagnostic boot entry or risk losing remote access. Recommended physical diagnosis is boot-time Memtest86+, test modules individually at supported stock timings, then inspect the controller/board if faults persist. A reboot alone is not a repair or permission to clear integrity gates.

Private raw test output, original maintenance state and non-public device diagnostics were copied to socrat-3 and the bundle SHA256 independently verified. Public evidence contains only non-identifying outcomes. `historySourceIntegrityVerified` remains false; recovered block publication, OTel cutover and soak remain blocked. The healthy older-backup import on the Mac continues independently. Restoring desired replicas requires an explicit decision if the memory fault is unresolved; do not casually run the saved restoration state as evidence of a successful repair.

### Subsequent explicit restoration request and controlled reboot — 2026-10-30

The operator explicitly requested reconnecting over verified SSH, restoring all services and continuing the migration despite the previously reported failure. The provided credential was not copied to repository files, command arguments or evidence; existing verified SSH keys and the pre-existing private become file were used.

A controlled reboot completed with verified SSH recovery in 117 seconds, changing boot ID `33da5430-c8f9-4958-a5a5-e60e91a75e2c` to `a9185e7e-58e8-4fa7-be3f-79097babccb3`. Kubernetes returned all four nodes Ready and the NVIDIA driver/GPU returned. Ordinary reading of the staged candidate archive then matched its expected SHA256 without file-cache eviction. The original raw chunk was separately rechecked: its CRC failure remained in both ordinary and direct I/O reads, so reboot had NOT repaired historical content.

A second 4 GiB memory test was attempted with the same bounds. The Ansible command timed out at 2460 seconds without returning complete stdout. Its systemd journal reports successful deactivation and 16min 14.946s CPU time, but no complete raw comparison receipt was retained (`--pipe` bypassed the service journal). No memtester process remained. Preserve both observations: do not mislabel the controller timeout as a positive memory error, and do not use a successful service-deactivation message as proof that all 32 GiB are fault-free or that the earlier 14 comparison failures were repaired. Future long-running diagnostics must write their raw output and result to private files on the target rather than depending on an SSH pipe.

Original Prometheus/raw-store/raw-compactor replica counts and cascade suspension state were explicitly restored on the operator's availability request. Normal collection resumed. This restored desired state, not a hardware-health certification.

The recovered block then passed production Thanos 0.42.4 `tools bucket verify --issues=index_known_issues` WITHOUT `--repair`, plus actual isolated Store/Query checks of the exact affected label set: count 1 before the approved gap, 0 inside, 1 afterward. The initial helper used the obsolete issue ID `index_issue` and failed before verification; it was corrected against the pinned binary's supported IDs, not by disabling checks. The executable was matched to the repository-pinned upstream release archive. All extracted candidate files matched independently recorded SHA256 inventories.

Only after this proof, original and replacement file inventories were rehashed, raw store/compactor were paused and cascade suspended. The original raw block was renamed to private `/var/tmp/otel-recovery-20261030/quarantine/01M65MWZVAGM92C51JW43C3SZ7`; the replacement `01M66BZJJH7AX3HTZFRZD02SXP` was renamed into the live raw bucket, with source/replacement on the same filesystem and ownership restored for native containers. The two raw copies were never co-served. Post-move SHA256 checks and raw-store rollout succeeded; original desired controller state was restored. Live Prometheus was NOT stopped for this replacement. Original block bytes remain quarantined and off-node preserved; approved loss remains exactly 120 samples, all 6,383,043,932 other source samples canonical-verified.

Fresh verification at the final inventory found all 78 Prometheus targets healthy, all four nodes Ready, and no nonterminal unready pods cluster-wide. The public Kuma page returned HTTP 200 with TLS verification. Existing unrelated alert delivery/retention/resource questions are not thereby declared solved. Preflight remains not-ready: disk projection, all historical roundtrips, source integrity/memory resolution and complete source registry are unverified. This was repair/restoration of the existing native Thanos stack, NOT an OTel production cutover or the beginning of 72-hour soak.

For the necessary console step, stock Debian `memtest86+` 7.20-1 is installed; UEFI is present and Secure Boot reports disabled. The prepared entry is **Memory test (memtest86+x64.efi)**. Saved GRUB environment was verified unchanged; no one-shot diagnostic boot was configured and Linux remains the normal boot. The operator must select the entry at the physical/remote hardware console and report actual Pass/Errors results. SSH cannot operate or observe this pre-OS environment without a separately configured hardware console. Do not claim that knowing a login password supplies such access.

See `source-restoration-20261030.json` and `preflight-20261030T1500.json`. No commits were made. The pinned older-history job continues on the Mac independently.


### Console result, continued offline history and four native sources — 2026-10-30

The operator reported **50 Memtest86+ errors / Failed before the first pass** on socrat-0, then selected normal Linux boot and deferred physical diagnosis. This is operator-reported boot-time positive evidence, not a tool-observed complete memory pass or a DIMM identification. Hardware health remains unresolved. Following that latest boot, read-only verification found all four nodes Ready, no nonterminal unready pods and 78/78 healthy production scrape targets. Existing collection is available; hardware/source integrity is not thereby certified. No additional diagnostic reboot was initiated.

The bounded older-backup job now has **2 of 7** full raw/snapshot OTLP export → native import canonical roundtrips, totaling **4,841,869,085 samples**. The large block alone has 4,606,695,568 samples and unchanged canonical SHA256 `d49a8367a81cdd9dfd626fdf13eded48063abdb37289669d5572a8f8c3821b1f`. It moved on to exporting the next block; all seven are not yet verified. Original exports and native intermediate blocks remain retained. This older-backup coverage does not certify subsequently collected live history.

Both completed outputs additionally passed isolated-copy native metadata normalization, including a second canonical read after copying: original time bounds and complete-source ancestry preserved, semantic Thanos context retained, physical inventories rebuilt, outdated upload/index statistics removed. Coordinator-owned originals were not edited. A pinned continuation follows only completed source receipts and normalizes later outputs in separate directories, stopping on failures. Native Store/Query compatibility of these historical reimports is still a separate gate; the previously verified and published approved recovery is not evidence for all these blocks. Snapshot external Thanos label context must also be proven before serving.

All four independent **exporter sources** passed a real native systemd canary using the exact official v1.12.1-distroless executable, matching the index digest of all four current Kubernetes exporters. Full family/type/help and ordinary-label sets matched (366/356/326/351 families); 12,911 stable series matched across the four nodes. Stable constants, filesystem flags/sizes, timezone and textfile mtimes were checked where unchanged across surrounding legacy scrapes. Ordinary labels/values were not rewritten. Two explicitly observed volatile legacy series on socrat-3 were separately accounted for, not silently asserted identical. Raw metric bodies were not persisted.

Each source ran outside Kubernetes/containerd cgroups, listened only on loopback, used a 64 MiB systemd memory maximum, and was stopped afterward. The old textfile path label contract was preserved with a standard read-only bind and supported native flags; there is no translation gateway. The first canary readiness request used an unsupported `/-/healthy` path and failed with 404; its stopped-unit receipt was preserved. It was corrected to the exporter landing route. A subsequent conservative bind check encountered TIME_WAIT, confirmed there was no listener, and was corrected with SO_REUSEADDR without killing or replacing another process. Final strengthened runs passed on all four hosts. This does **not** yet prove four complete agent → OTLP pipelines or a Kubernetes shutdown scenario.

Resource policy now explicitly adds **64 MiB per native host exporter**, outside each unchanged 256 MiB agent budget. Reserves remain unchanged. Fresh capacity preflight still passes all four memory floors, including socrat-2: 666,259,456 bytes available versus 603,979,776 required (320 MiB components + 256 MiB reserve). This is a narrow margin, not a measured whole-stack peak/retention projection. Disk projection, full current-history roundtrips/integrity and complete cross-signal source registry remain unverified. Four actual host agent pipelines, persistent production TLS/credential lifecycle, 5s evaluation/group alignment, native failure/rollback tests and the real 72-hour soak remain unfinished.

Validation: 119 focused Python tests pass; Go race tests and vet pass, including native metadata and source parser/comparator tests. No commits. No OTel production ownership switch or soak start is claimed. See `history-native-metadata-20261030.json`, `host-source-canary-20261030.json`, `source-console-return-20261030.json` and `preflight-20261030T1643.json`.


### Four actual host metrics agents and durable restart replay — 2026-10-30, follow-up

The next real canary progressed beyond the earlier exporter-only comparison: all four hosts ran the pinned stock Collector **metrics pipeline** under a 256 MiB per-agent systemd limit, with their separate stock exporter limited to 64 MiB. Frozen native scrape configurations preserve every legacy target label. All four agents delivered over mutually authenticated TLS through a temporary stock Collector gateway bound only to socrat-1's existing private WireGuard address, then to an isolated stock Prometheus 3.15 native OTLP receiver over mTLS. No source sent to production ingestion; the Prometheus datasource UID, existing scrape ownership and production placement were not changed. Logs/filelog/journald pipelines were deliberately absent from this canary, so no old sensitive logs were imported.

Three consecutive fresh `up=1` observations matched all four complete target label sets. The gateway was then stopped, all four persistent queues accumulated real metrics, and all four agents were restarted while delivery remained unavailable. After recovery, the shadow backend contained **raw range-vector samples** timestamped after the gateway stopped but before each agent restart: final managed run recovered 3/3/3/4 such `up` samples on socrat-0/1/2/3. This uses `up[10m]`, not interpolated query_range lookback samples. Queues drained; original production targets still matched frozen aliases and 78/78 remained healthy afterward.

The initial naive log scan reported `Exporting failed. Dropping data.` at intentional agent shutdown and was preserved as a failed unclassified-log gate. Inspection of pinned upstream 0.164.0 shows queue_sender logs that text for all Send errors, but persistent_queue.onDone deliberately keeps `IsShutdownErr` in-flight requests for startup replay. No generic errors were exempted: only the exact pinned-version shutdown signature, actual matching `Moved items for dispatching back to queue` request counts, raw outage-sample recovery and drained queues were accepted. Unexpected errors, missing replay, malformed diagnostics, metadata/storage errors and memory refusals still fail.

The first trial also exposed a genuine orchestration issue: parallel cleanup could stop the shared gateway before the final agent finished. One canary-only in-flight request on socrat-3 remained durable; a native drain-only agent restored it and delivered it before backend-last shutdown. Nothing was deleted to hide it. The maintained Ansible playbook now enforces an all-agent shutdown barrier, then stops gateway → shadow Prometheus, verifies termination, and removes temporary client/server TLS material. A complete managed rerun passed on all four hosts with this ordering.

Two failed preparation/orchestration attempts were retained: a cold Collector validation on socrat-3 exceeded its initial 20s bound (not a config pass; changed to a bounded 60s validation), and an Ansible delegation inherited the caller's host alias. Strict SSH host-key verification correctly blocked the wrong alias before any backend command ran. The playbook was corrected to execute backend tasks on their own inventory host, not by deleting keys, accepting new fingerprints or disabling verification. No reboot, route change or broad service restart was used.

Final measured agent cgroup peaks in the metrics-only run were 86,474,752 / 87,834,624 / 65,695,744 / 73,723,904 bytes on socrat-0/1/2/3. The 256 MiB budgets were NOT lowered: these observations exclude full journal/container-log workload. Systemd releases without MemoryPeak use native cgroup-v2 memory.peak for measurements. Post-drain allocated bbolt bytes were measured, but a partial outage is not full 128 MiB queue saturation, compaction high-water or a complete 14d/7d retention projection.

The historical job remains active on the next 5.96-billion-sample block; older-backup full roundtrips remain **2 of 7**, not complete. Updated native importer observation captures a **4,442,226,688-byte sampled RSS peak** during upstream compaction; the earlier ~1.14 GB observation was only an initial head/shard measurement. The 2.5-million-point mutable head bound does not hard-limit compaction/mmap RSS, and GOMEMLIMIT is not a hard memory cap. No competing importer was launched.

Current evidence: `host-metrics-agents-20261030.json` and `history-bounded-resource-20261030T1802.json`. All temporary canary processes are stopped and copied TLS credentials removed. Full agent **log** pipelines, durable production TLS/auth renewal, all family/rule semantics, current-history integrity, disk/retention projection, source instrumentation completeness, actual cutover/rollback and the real 72-hour soak remain open. Existing positive memory diagnostics remain unresolved; source integrity is not cleared by this canary. 128 focused Python tests pass; no commits.


Following the successful managed run, request creation was made repeatable in `scripts/otel-host-metrics-request.py`: original ≤900s contract timestamps, per-host source fingerprints, official OCI image receipts and executable SHA256 must all match. The remote prepare phase independently rejects stale/future observations and changed source configs. This hardening was validated with a fresh live bundle and the real pinned receipts. Native transient units additionally specify MemorySwapMax=0 for subsequent runs; this setting is not retroactively asserted for the already completed metrics-only canary.


### Overnight operator request — 2026-10-30 21:00 UTC

The operator requested autonomous overnight completion of the entire migration, cleanup and all production/history coverage. This is not evidence that the source-integrity, native-history capability or 72h timing constraints were satisfied. No commit or loss-of-history waiver was inferred.

A fresh privileged counts-only inventory distinguished actual container states (regular/init/ephemeral) rather than confusing unavailable completed-job logs with unreadable active sources. All **106 active containers** had readable log APIs, with zero truncation or unknown states; 239 total source entries and 118 unavailable historical/inactive entries remain explicitly accounted for. Ten-minute observed container throughput was ~814 bytes/s, a lower bound, not a peak or retention projection. All four system journals were measured privately. **Zero** container tracing environment/argument/annotation hints were found; even such hints would not prove actual trace delivery. No historical log bodies were persisted or imported. Full live trace instrumentation and measured trace capacity are therefore still open, not silently labelled migrated.

Verified duplicate Collector/Prometheus executables were removed only from the two completed/failed private metrics-canary workspaces after checking root ownership, exact SHA256 and absence of any process executing them. Queues, shadow datasets, receipts, original history and backups were retained. Temporary TLS directories were confirmed empty. This is temporary-artifact cleanup, not retention reduction.

The existing single pinned historical importer and separate metadata-copy verifier continue. Temporary native macOS idle-sleep assertions are tied to their existing supervisor/normalizer PIDs; persistent system power preferences were not changed. A finite **16-hour read-only audit** (`scripts/otel-night-audit.py`) was launched, producing private hourly current inventories, fail-closed preflights and source-job/normalization progress. It stops on command or history failures. It never clears prerequisites, enables production ingestion, starts a soak, or declares the whole migration complete. Readiness or older-backup completion alone cannot trigger an unimplemented/untested production cutover. It does not create an autonomous always-awake assistant session.

Public sanitized evidence: `signals-20261030-night.json`, `canary-cleanup-20261030-night.json`. Private nightly progress: `/tmp/otel-night-20261030/audit/progress.json`, final receipt `result.json`. Current source-integrity failures, unsupported native historical aggregation, missing full production deployment/instrumentation and actual 72h soak remain real blockers to the literal all-history/all-signals completion claim. 130 focused Python tests pass. No commits or production ownership changes.


### Native historical Store/Query proof — 2026-10-31

The overnight source job progressed to **3 complete older-backup roundtrips**, totaling **10,797,237,244 samples**. The next 6.137-billion-sample block reached final upstream compaction; this is not yet a verified fourth result. Metadata copies for the three completed blocks are independently normalized and canonical-checked.

A normalized 4,606,695,568-sample result additionally passed the actual pinned **Thanos 0.42.4** `tools bucket verify --issues=index_known_issues` and isolated stock Store/Query on healthy socrat-1, without `--repair`. Native executable and archive SHA256 matched the pinned upstream release. Three distinct real source families (boot time, memory total, uname) were queried at exact source milliseconds; every ordinary/external label and returned float bit matched, and `timestamp()` matched the original sample time. These anchors complement, never replace, full-block canonical verification. Production bucket/query paths were untouched; original and replacement never co-served.

`cmd/native-anchors`, `scripts/otel-history-native-compat.py` and `ansible/playbooks/otel-history-native-compat.yml` make the native proof repeatable with private staging, strict host keys, no public listeners, 20% disk reserve, 2 GiB cgroup memory with swap disabled and a finite runtime. A dependent `scripts/otel-history-query-job.py` worker follows only completed normalized outputs, checks canonical receipt identity, transfers hash-bound archives, and repeats stock native checks sequentially. It does not start another importer, publish blocks, clear policy or invent missing external labels. The snapshot's missing external-label provenance remains explicitly blocked pending independent proof.

The new native continuation is finite and stops on failed source/normalization/transfer/native checks. It has its own temporary idle-sleep assertion; source and metadata jobs remain separate single writers. The 16h nightly audit had completed 14 cycles by the morning. Fresh 11:15 UTC preflight still passes measured memory floors on all four hosts but remains not-ready on the same four independent prerequisites; a zero additional-disk placeholder is not full retention capacity. Positive hardware faults, trace instrumentation and production log/TLS deployment remain unresolved. No migration completion or 72h soak is claimed. Current public evidence: `history-native-query-20261031.json`; 133 focused Python tests, Go tests/vet pass. No commits.


### Durable ownership, lifecycle and rollback

- `deploy/monitoring/otel-production-values.yaml` captures native ownership, sidecar, loopback receiver, disabled legacy scrape selectors and retired exporter placement. The stack role detects an already native live owner and includes this overlay; a future Helm operation must not silently re-enable duplicate legacy scraping. The rule post-renderer retains 5s explicit group intervals.
- cert-manager owns the CA and 90-day leaf lifecycle. Host refreshers use named, limited ServiceAccounts, self-renew 24h tokens, synchronize required source credentials and refresh local TLS. Access to the CA private-key Secret was actually rejected on all four host credentials. Cluster TLS reloads projected leaves every minute; host services restart with durable queues on leaf changes. Traefik receives mirrored dedicated client certificates and rolls on their renewal; Grafana datasource certificate provisioning is refreshed. An outage longer than bootstrap-token lifetime can require authorized rebootstrap; do not silently fall back to administrator credentials.
- Credentials, TLS and durable queues live under managed `/var/lib` paths, not controller `/tmp`. Root-only rollback originals and a CRC/SHA-checked pre-readiness-update MariaDB dump are preserved in the controller Library support directory and `/srv/otel-production-rollback/20261031` on socrat-1. Original historical archives remain independently preserved on socrat-3.
- `ansible/playbooks/otel-production-rollback.yml` is explicit, not executed: stop all agent writers, replace the complete saved Prometheus and legacy exporter specs, wait for readiness. It deletes no TSDB data or native queues. It pauses native log agents until a healthy gateway is restored; do not mistake metrics rollback for an automatic all-signal rollback.
- Kuma's original single Prometheus monitor now checks the native sidecar readiness endpoint instead of the deliberately closed Prometheus pod-network HTTP port. A private consistent DB dump preceded the one-row URL change; the monitor ID/name and singleton deployment were retained. Latest heartbeat was UP. No active-active Kuma assumption or VPN routing change was made.
- Alert-link resolution uses the existing native Thanos Rules API and pinned upstream `promtool --experimental promql format` for formatting, not the retired pod-network Prometheus management endpoint. Read-only migration inventory queries native Prometheus with authenticated Kubernetes exec and validates fresh `up` instead of expecting a nonempty legacy targets API.


### Controller workspace recovery (2026-10-31)

The controller temporary workspace disappeared, including the old coordinator and its checkpoint. Its importer is **not** reported as still running. Six canonical-roundtripped and native-validated outputs were independently re-confirmed in protected durable staging on socrat-1: **17,456,856,414 samples**. Originals and rollback remain preserved. The entire 7,616,784,130-byte raw backup was re-read on socrat-3 and matched the original SHA256 before the final raw block was trusted. A single offline importer now runs on healthy socrat-1, with 3 GiB hard memory, zero swap, 150% CPU and 12h runtime limits. A separate finite root finalizer waits for that exact import, then performs pinned stock native index/Store/Query validation and same-filesystem durable staging. Neither worker publishes to production or deletes originals. Workers and state are independent of controller `/tmp` and do not require autonomous agent reasoning.

The new current-bucket inventory must still be reconciled against the older backup: completing seven backup roundtrips alone is **not** certification of all post-backup/current history, nor permission to publish overlapping snapshot and raw replacements. Only independently verified, non-double-served publication may replace an original. Actual unhealthy observations continue to reset the soak; the latest captured not-before time is 2026-11-03T17:35:29Z, not a promised completion date. Privileged controller credentials were restored to a private mode-0600 file outside the repository and `/tmp`; never place their values in evidence or commits.


### Historical scope reconciliation and observed soak lifecycle

`migration-evidence/history-coverage-reconciliation-20261031.json` is a read-only planning result, **not** publication approval. Six completed backup candidates include one exact-ancestry live raw counterpart, contained ranges requiring full source-sample subset proof, and old raw representations no longer actively present as raw. Time/ancestry overlap alone cannot prove coverage. `tools/otel-history/cmd/subset-check` compares every source ordinary label set, timestamp, float bit pattern (including signed zero/staleness) and sample multiplicity with a covering raw block; it explicitly does not certify the whole target or replace canonical verification. Race tests cover signed-zero changes, absent timestamps/labels, wrong context, downsampling, self-proof and incomplete counts.

Source canonical receipts lost with the controller workspace are being independently rebuilt from the complete SHA-pinned original archive on socrat-3, in a finite unprivileged 384 MiB/zero-swap/idle-I/O unit. Separately, the already approved repaired live block was captured without changing original files and copied off socrat-0 to a healthy host. Acceptance requires its complete 6,383,043,932-sample inventory to equal the previously established `0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209`; a successful copy is **not** yet that acceptance, and no additional sample loss is authorized.

The existing hourly cascade replaces the singleton raw compactor pod. Actual failed observation replay established 79 fresh scrape identities but 78 healthy current logical sources: the extra failed identity belonged to a terminating predecessor. The observer now excludes only this tightly scoped predecessor when fresh KSM data prove deletion/absence, an exactly one-replica ReplicaSet, and a ready successfully scraped successor of that same ReplicaSet. Live nonterminating failures, absent/unready successors, wrong owners and other endpoints remain failures. No metrics were deleted or altered, no old failed observations were erased, and changing observer code intentionally starts a new 72-hour window. Independent real historical replay is retained in `migration-evidence/soak-retired-compactor-proof-20261031.json`.


The finite full-subset queue and full preserved-stage canonical revalidation now run on socrat-1. The former waits for healthy-host acceptance of the exact approved repaired block, preserves that input under root-only storage by same-filesystem rename, and checks all 235,173,517 + 260,844,250 + 261,337,432 + 1,043,291,602 source samples. It does not approve publication and still requires the covering target's own OTLP roundtrip. The latter rebuilds complete CRC/canonical receipts of the six retained stages for comparison with original-source golden receipts. All are bounded read-only verification tasks; the original single importer remains the only importer. Real mount-namespace probes validated inode-preserving atomic moves, not just matching filesystem device IDs: separate systemd `ReadWritePaths` bind mounts had to be removed from the waiting finalizer's sandbox before validation began. Only that idle waiter was restarted, never the importer or production backends.

### 2026-11-01: durable tail backup and fresh staged-block verification

- The recovered seventh backup block completed the full canonical OTLP roundtrip,
  pinned native Thanos Store/Query checks and durable protected staging. This
  completes the seven-block **backup conversion scope**, not all current history
  or production publication. Independent rebuilding of the original-source
  golden receipts remains outstanding.
- A fresh full native canonical/CRC inventory of all six earlier protected
  stages succeeded: 17,456,856,414 samples. The report explicitly keeps
  `sourceGoldenHashComparisonStillRequired: true`.
- Nine immutable whole raw blocks intersecting the post-backup/cutover tail were
  captured without modifying production originals. Their 3,576,514,560-byte
  archive was copied to socrat-3 and independently SHA256-verified as
  `64d364074f13f6977cdc92f9117181340563c217f68de92a85c6cd5e6b48bac5`.
  Declared block sample count is 4,170,768,866; boundary blocks may include native
  post-cutover points. Archive transport verification is **not** a full native
  sample-integrity certificate, OTLP roundtrip or approval to serve overlaps.
- The second original-source canonical attempt on socrat-3 timed out after four
  hours on the first block with zero successful inventories. Both failed attempts
  and partial diagnostics are retained; transient-unit garbage collection can
  make `systemctl show Result=success` misleading, so explicit receipts/journal
  failures are authoritative.
- The same pinned full canonical-v1 reader is now scheduled on healthy socrat-1
  (Ryzen 7 7840HS with SHA acceleration), comparing each original source against
  the freshly revalidated restored digest. Only one private transport copy is
  present at a time. A 20% filesystem floor plus 16 GiB headroom for the current
  importer is required before each copy. A successful comparison removes only
  that verified temporary copy; original archive/extracted corpus remain on
  socrat-3, and failed copies/receipts are retained. No sampling or replacement
  digest algorithm is used.
- The independent full roundtrip of the 6,383,043,932-sample repaired current
  block is in its import phase. Its first attempt stopped at the exporter's
  production-output-path gate before processing data. That failed attempt is
  retained; v2 uses a root-only intermediate home workspace without weakening
  the gate. A finite native-validation/staging finalizer waits for complete
  canonical success, checks the trusted source digest and disk reserve, and
  never publishes to production.
- At 2026-11-01 06:14 UTC the real production observation showed 78 fresh sources,
  no errors and 39,609 healthy seconds (about 11 hours), not a completed 72-hour
  soak. Hardware failures, all-current-history acceptance, internal SDK scope,
  operational rotation/replay/rollback and full retention projection remain
  open. No new commits or historical production publication were performed.

### 2026-11-01 06:31 UTC: live scope refreshed, out-of-order blocks preserved

The refreshed inventory contains 37 blocks across native raw/downsampled tiers.
All nine archived tail originals are still present with unchanged semantic
identity (ULID, time range, complete declared stats, compaction ancestry/hints
and external labels). This is identity reconciliation, not sample equality or
publication authorization. Other live raw blocks are explicitly outside the
certification of this audit; their provenance must not be inferred from ULID or
interval alone.

Two small overlapping tail blocks are legitimate native Prometheus
`from-out-of-order` companions, not disposable duplicates of the larger 12–14 UTC
block. Original copies were selected from the already SHA-verified off-node
archive and fully inventoried on healthy socrat-1 with the pinned canonical-v1
reader, within a 192 MiB hard memory/zero-swap/50% CPU limit:

- `01M690QQG8K9TQ5WBE7W573CW0`: 38,731 samples, canonical SHA256
  `f7f081130c485e7df717ce76254e30b6efb6020da39fc0ae366c05faa38a4234`.
- `01M697KFH379N839ZYW5VM28J5`: 4,279 samples, canonical SHA256
  `87ff7eba08390b39dab7aaa0d4824560270a61e4d683545edf9a0d44787f15fc`.

Both retain `otlpRoundtripStillRequired: true`. Neither production originals nor
these verified source copies were removed or published. No second importer was
started. The larger current-block importer and sequential six-original verifier
continue independently; a sample-subset proof is still required if later
compaction replaces any frozen source identity.

### 2026-11-01: application signal registry / SDK stage started

The operator requested moving to the next stage while finite historical workers
continue. This does **not** close historical reconciliation or authorize publishing
unverified/overlapping blocks. The first original-to-restored golden comparison
on healthy socrat-1 completed successfully: 4,606,695,568 samples, canonical SHA256
`d49a8367a81cdd9dfd626fdf13eded48063abdb37289669d5572a8f8c3821b1f`.
The verifier moved to copying the second original; only the successful temporary
transport copy was removed, never the preserved original archive/corpus.

A new metadata-only registry observed 100 container-template sources and 240
pod/container incarnations including actual image IDs, plus service-unit metadata
for all four hosts (167/145/116/151 units). These are source-discovery counts, not
SDK/log delivery success counts. No environment values, command argument values,
credentials or log bodies were saved. Mounted config files and opaque envFrom
sources remain outside the hint detector, so absent OTEL variables do not prove
that instrumentation is disabled. The two configuration-hint records do not
certify any internal application traces.

Read-only runtime package/source probes found:

- LiteLLM 1.105.1: OTEL SDK/exporters 1.33.1 installed; native callback source
  contains message-content disable controls. Existing Prometheus callback and
  metric ownership must remain intact. Source privacy and TLS behavior still
  require proof before enabling traces.
- vLLM 0.31.0: OTEL SDK/exporters 1.40.0 installed. Both versioned upstream and
  installed source show **hardcoded `insecure=True` in the gRPC exporter**.
  Enabling that path to an unauthenticated network receiver is unacceptable.
  HTTP/protobuf support exists; an authenticated mTLS path or stock loopback
  Collector sidecar is required, with no changes to inference/model settings.
- Open WebUI 0.12.3 slim: SDK/exporters 1.42.1 and FastAPI instrumentation installed.
  Versioned source declares OTEL enable controls; actual initializer/entrypoint
  and privacy/delivery still need verification. Custom services sharing the same
  base image are not automatically covered.
- Harbor 2.15.4 / chart 1.19.4: versioned native source/chart expose OTLP HTTP
  tracing and sample_rate. Dedicated client credentials, authenticated HTTP
  transport and renewal/reload must be proven before enabling it.

`otel-application-scope.json` records the pending version-specific gates, not a
production deployment or a blanket unsupported exclusion. SDK coverage still
requires internal spans correlated with W3C parent/child context; existing
Traefik ingress traces are insufficient. No application deployment was changed,
no unauthenticated listener was opened and no SDK coverage was declared complete.


### 2026-11-01 — full original goldens, raw/sidecar boundary repair, application transport

- All **six** original raw-corpus comparisons completed on the healthy host using
  the unchanged pinned `legacy-full-canonical-v1` reader: **18,264,974,499 samples**
  have exact independent original/restored canonical equality. Each receipt binds
  the preserved archive SHA, count and digest. Only successfully verified temporary
  transport copies were removed; the source archive/corpus and failed slow-reader
  attempts remain. This closes original golden verification, **not** all-current
  history publication or current-block roundtrip certification.
- Found a real query boundary gap caused by raw Store `--max-time=-12h` versus
  actual sidecar minimum time. Removed only that read clamp, live and in maintained
  chart values. The formerly empty 2026-10-31 19:50 UTC query now returns 78 `up`
  sources with both dedup=true and dedup=false; adjacent reference queries also
  pass. No samples/retention/datasource UID changed; Prometheus and the Collector
  were not restarted. Soak now fails closed on unhealthy raw/sidecar discovery or
  an advertised gap and keeps checking after an earlier completed state.
- Bound the real continuous soak to script/configuration fingerprints. Preserved
  earlier failures and explicitly reset for the boundary repair, then again for
  the new application HTTP transport. Earlier accumulated hours are not added to
  the new window; no fixed completion date is promised through further changes.
- Four dedicated 90-day client-only cert-manager leaves are Ready. A bounded
  non-root half-hourly CronJob may get only the four source leaf Secrets and
  get/patch only four named namespace-local mirror Secrets. Real SAR checks deny
  CA private-key access, Secret listing, unrelated application Secret patching,
  certificate creation and application Deployment patching. Its initial probe
  failed closed because HTTP2 ALPN was missing; failed status/logs were retained.
  Explicit `h2` ALPN fixed the probe without weakening verification. All four
  actual leaf pairs completed native gRPC client-mTLS handshakes and were mirrored.
- Added a separate **stock Collector** HTTP-only trace receiver on healthy socrat-1,
  private `10.250.0.3:44318`, minimum TLS1.3/client CA required. Node2 was not chosen:
  its measured ~484MiB available memory would not preserve a 20% host reserve after
  a 192MiB allocation. Socrat1 had ~6.5GiB available and ~102GiB disk free. The new
  service has MemoryMax192MiB/zero swap/CPU50%, a separate fsync-backed64MiB queue,
  the same privacy transform **before** durable queueing, loopback-only health and
  metrics, and private-address systemd network restrictions. It forwards to the
  **existing single global sampler**, never directly bypassing sampling to Tempo.
  Metrics/logs routes return404; anonymous TLS is explicitly rejected. Measured
  service memory was ~39.2MiB. Existing owners/global sampler were not restarted.
- Maintained Ansible playbooks reconcile the PKI/mirror and native HTTP service;
  host-leaf renewal now includes the new receiver's reload hook. Routine playbook
  execution does not overwrite populated target Secret data. Actual application
  SDK credential reload remains a separate gate: reload target lists deliberately
  stay empty while no production SDK rollout has passed its source-specific gates.
- Pinned installed LiteLLM1.105.1 image passed isolated **library** canaries through
  both native gRPC/mTLS and native HTTP/mTLS. Tempo proves a correlated parent and
  real `litellm_request` child. The HTTP canary's SDK SpanProcessor audit proved
  synthetic prompt/response/API-key markers absent **before export**, independently
  of downstream redaction, and the backend negative check also passed. SDK metrics
  and events stayed off; SDK sampler was AlwaysOn. Only a mock response was used:
  zero real LLM API calls/tokens. These are **not production application SDK
  coverage** and do not replace proxy-route/entrypoint/per-source log checks.
- The repaired current-block importer remains active and memory-bounded; observed
  cgroup pressure was file cache (~1.9GiB) with ~1.0GiB anonymous memory and zero OOM
  events, not permission to relax its3GiB ceiling. The nine-block tail archive
  transfer completed; its single-importer queue still waits for current native
  finalization. Nothing in the queue publishes to production.
- Acceptance is still open: all-current history/publication, source-specific SDK
  rollout and logs, real certificate/token rotation and all-signal replay/rollback,
  measured retention/capacity, genuine continuous72h and final owned cleanup.
  Socrat0's positive RAM faults remain unresolved and outside the risk waiver.

- Follow-up isolated LiteLLM **actual proxy ASGI** `/v1/chat/completions` route
  also returned200 with a synthetic mock model and authenticated synthetic key.
  Seven native spans were audited before export with no prompt/response/key
  markers; Tempo independently returned seven spans including the native
  `Received Proxy Server Request` child. This exercises more than the library
  completion callback, but still is **not a production SDK rollout or network
  W3C acceptance**. Its evidence is `litellm-proxy-sdk-canary-20261101.json`.
- Prepared a minimal fenced LiteLLM rollout tool that preserves existing model,
  database, GPU, Prometheus and long-request drain settings. **It was not applied**:
  production apply refuses before any cluster access until independent renewable
  SDK credential reload proof is recorded. No broad Deployment patch permission
  was granted to the mirror reader merely to make this gate pass. Remaining
  applications still require their own native initialization/privacy/lifecycle
  proof; shared image packages are not an unsupported-source exclusion.


### 2026-11-01 — real leaf/key renewal, first production application SDK, capacity observations

- Exercised native cert-manager manual renewal using the same Issuing status
  transition as cmctl2.3.0. No Secrets were deleted, Certificate spec/90-day
  duration did not change, and no CA private key was read/distributed. LiteLLM
  revisions1→2 and2→3 completed; the latter independently verifies changed
  **public key** as well as changed certificate, native mTLS and mirror equality.
  Valid old leaves were not claimed revoked.
- A **single unchanged native HTTP SDK/provider/exporter instance** sent one
  mocked completion before and one after the projected Secret changed. With
  `OTEL_EXPORTER_OTLP_HEADERS=Connection=close`, transparent test-only observation
  of the real SSLContext loader proved that each leaf was loaded by normal TLS.
  Both parent/child traces are independently present in Tempo; source privacy
  audit counted4spans with no synthetic prompt/response/API-key content. No
  Deployment patch rights were granted to the mirror ServiceAccount, no SDK
  restart was needed, and no private keys were saved/logged. The production
  configuration uses the tested fresh-handshake/header and file-mount mechanism.
- Enabled native **LiteLLM production SDK** only after these gates. Minimal fenced
  ConfigMap/Deployment updates preserve all model/DB/GPU settings, existing
  authenticated Prometheus callback, and long-request drain behavior. SDK sampler
  AlwaysOn; SDK metrics/events/log exporters off; source message logging off.
  The new pod became Ready and the old replica **naturally drained**; none was
  force killed. Maintained values and `otel-litellm-sdk.yml` reconcile this setup;
  a subsequent maintained reconcile succeeded without replacing the pod or
  changing the SDK soak fingerprint. Private rollback preimages stay in CROOT.
- Tested an actual production HTTP process from a **separate process** with W3C
  traceparent. One deliberately nonexistent-model request returned400: no real
  inference, model switch or paid API request. A clearly synthetic ERROR root
  retains the trace without misrepresenting a genuine application failure.
  Tempo returned6spans across `homelab-live-sdk-probe` and real service `litellm`,
  including `Received Proxy Server Request`, `auth`, `proxy_pre_call`,
  `litellm_request`, and `Failed Proxy Server Request` under the client parent.
  This proves the **production HTTP auth/router error path**, not inference
  success, all applications, or ingress-only coverage. The new pod has exactly
  one native metric target UP and535 log entries in its measured10m window;
  only aggregated log counts were queried, never bodies.
- Bound the genuine soak to the live SDK configuration hash. An initial private
  controller epoch-command quoting error failed before any file write; retained
  its log and corrected it. Do not add earlier healthy intervals to the new
  configuration window. Receiver maintenance now preserves independent SDK
  epoch bindings instead of overwriting them.
- Started an isolated **metadata/counter-only capacity timer** every5m on socrat1,
  MemoryMax128MiB/zero swap/CPU25%. It reads no history chunks, log bodies or trace
  payloads, records no metric labels, and never changes retention. Initial native
  allocation: Loki121,749,504B; Tempo13,705,216B; HTTP queue32,768B allocated,
  queue size0/capacity67,108,864B. Available filesystem109,059,043,328B and
  MemAvailable6,759,235,584B at observation. Loki has received1,294,957,876B and
  Tempo18,204,402B since their actual process starts. These are **measured inputs,
  not peak-window or full metrics/log14d/trace7d capacity acceptance**.
- Read-only Open WebUI0.12.3 review now proves the real initializer is called,
  but reveals source privacy blockers: its native hooks serialize Redis command
  arguments into db.statement, put full outbound URLs into span names, and record
  raw aiohttp exceptions. **Do not enable that native profile as-is**. Downstream
  attribute redaction is not source privacy and does not remove raw URL span
  names. This is a security remediation gate, not a blanket unsupported exclusion.
- Full-current history roundtrip/publication, remaining source SDK/log coverage,
  production inference-success path, all-signal outage/replay and rollback,
  full retention projection and genuine continuous72h remain open. Positive
  socrat0 RAM faults remain unresolved. No new commits.

### 2026-11-01 — installed vLLM HTTP/mTLS and source exception privacy canaries

- Pinned installed vLLM0.31.0 / HTTP SDK1.40.0 passed a **CPU-only** native
  `OutputProcessor.do_tracing` canary: no engine/model startup, GPU allocation or
  real inference. Its actual `llm_request` child and W3C parent were independently
  found in Tempo over the dedicated vLLM client leaf/private HTTP mTLS route.
  The selector must be **OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf**;
  generic protocol alone does not exclude this vLLM version's insecure gRPC path.
- Native request tracing ignored synthetic prompt/response fields at source.
  A separate **in-memory-only** default-decorator error test found raw synthetic
  exception content in status description and exception events. No network
  exporter was created for that negative test. Do not enable the default profile
  as-is or count this as production SDK coverage.
- Added an **opt-in prototype application SDK guard**, using public SDK
  ReadableSpan/SpanProcessor/TracerProvider APIs and an explicit early provider
  factory substitution. It sends a redacted copy to downstream processors
  **before BatchSpanProcessor queue admission**. It does not modify installed
  SDK files, create a compatibility gateway or fork Collector. Original exception
  data may transiently exist inside the application's SDK: this is deliberately
  not a claim of zero in-memory materialization or permission to enable unsafe
  Open WebUI Redis/body-capturing hooks.
- The installed native decorator's negative exception test passed with the
  prototype. A second actual native HTTP/mTLS canary passed with the guard, with
  both spans again independently found in Tempo. Pinned-runtime invariants prove
  context/parent identities, timestamps, kind/error code, ordinary values,
  negative zero/NaN, instrumentation scope, resource schema, links and event
  timestamps are preserved while private fields are removed before downstream
  processors. Maintained fail-closed application bootstrap, actual vLLM SDK leaf
  renewal and production inference/drain gates **remain required before rollout**.
- Four completed owned test Jobs/ConfigMaps were removed only after durable
  result/source preservation. Production GPU Deployment, client Secrets,
  model/DB settings and existing metrics ownership were untouched.
- Capacity trend analysis now uses **11 actual observations /2670.594s** in one
  configuration, without resets. Measured Loki ingress mean19,874.9B/s,
  observed-interval peak20,298.0B/s; Tempo mean200.6B/s, peak327.1B/s.
  Allocated storage Loki123,817,984B / Tempo13,508,608B; filesystem available
  108,574,797,824B. These are not peak-hour, compression, compaction, replication,
  full metrics/WAL/history or log14d/trace7d retention acceptance. The analyzer
  resets its measured window on errors, clock gaps, configuration changes or
  backend counter resets; it never emits full retention acceptance.
- Latest production observation: **3300.455healthy seconds (~55m),78fresh sources,
  errors[]**, all four log hosts, searchable traces and private HTTP readiness.
  Genuine72h remains incomplete, not-before2026-11-04T09:15:27.062188+00:00.
  Current6,383,043,932sample roundtrip remains in import; native finalizer and
  nine-block tail queue still wait. No publication, extra loss or history deletion
  is inferred from active units. **206 focused tests pass**, py_compile/diff-check
  pass. No new commits. Prior RAM faults and remaining acceptance gates persist.

- Owned-canary cleanup initially hit a response-parser error after a successful
  delete, then an unsupported kubectl delete JSON-output mode. Both failures and
  preimages were retained privately. The helper now treats successful wait/delete
  output as text/status, still rejects nonzero exits without exposing responses,
  and does not confuse a resource named delete with the command. Three regression
  tests cover this. All four owned Jobs/ConfigMaps were independently verified
  absent; no production workload/Secret/history data was removed.

### 2026-11-01 — steps 2–4 continued; no acceptance or history publication

- vLLM installed native HTTP SDK passed same-provider/exporter certificate **and
  keypair** renewal, exact early `sitecustomize` bootstrap without manual fallback,
  and independent Tempo parent/child checks. A maintained, fail-closed source guard
  precedes every downstream processor/BatchSpanProcessor queue. Insecure native
  gRPC remains forbidden; trace-specific HTTP/protobuf environment is mandatory.
- Model-switcher model transitions now preserve only the approved private native
  trace endpoint/protocol. Production vLLM SDK rollout followed three idle
  `running=0,waiting=0` observations. Old workers drained naturally; model, DB,
  cache, GPU, image and existing metrics ownership were preserved. A real
  synthetic one-token successful inference produced native `llm_request` with a
  cross-process W3C parent in Tempo. Existing metrics/log delivery passed and
  the synthetic prompt was absent from the bounded application log check.
  Maintained reconcile is `ansible/playbooks/otel-vllm-sdk.yml`; Helm deployments
  must retain `deploy/monitoring/otel-vllm-sdk-values.yaml`. SDK configuration is
  bound into the genuine soak epoch. Rollback exercise is still required.
- Open WebUI default native instrumentation remains **unsafe as-is**. The maintained
  HTTP-only source profile disables Redis command/SQL statement, duplicate system
  metric and logging instrumentors; it does not disable app DB/cache functionality.
  Real native FastAPI/requests/HTTPX/aiohttp instrumentation, synthetic source
  privacy checks, same-instance leaf/keypair renewal and both Tempo traces passed.
  Exact early-bootstrap canary also passed with no manual activation fallback.
- Open WebUI production rollout preserved single-replica **Recreate** SQLite
  semantics, tool-guard init/volumes, image, DB, auth, models and metric/log owners.
  Graceful request drain was extended to 7200s; no forced termination or concurrent
  SQLite replicas. New pod `open-webui-998794559-4fhk8` is Ready. A separate-process
  HTTP 200 `/api/version` request produced native **SERVER** span with the exact
  W3C parent independently verified in Tempo, not an ingress-span substitute.
  This is a real production API path, **not successful Open WebUI inference**.
  Individual container log delivery: 36 events in the initial one-hour count
  window; bodies were not fetched. Maintained no-restart reconcile passed via
  `ansible/playbooks/otel-open-webui-sdk.yml`; Helm must retain the maintained
  `deploy/monitoring/otel-open-webui-sdk-values.yaml` overlay. The SDK hash was
  added to the soak epoch without overwriting the receiver/other SDK bindings.
- The privacy guarantee is a redacted span copy **before downstream processors
  and export queues**. It does **not** assert that an original transient native
  SDK span can never contain sensitive exception content. Native unsafe Redis/SQL
  capture hooks are disabled, not accepted on the strength of exporter redaction.
- Retained failures: Open WebUI canary source-tree PYTHONPATH correction, TestClient
  inherited-context fixture correction (SERVER requirement retained), Kubernetes
  ConfigMap defaultMode and empty EnvVar.value canonicalization fences, and backend
  re-verification output-directory collision. The empty-env fix accepts only exact
  Kubernetes empty-value canonicalization; `valueFrom` conflicts remain forbidden.
  No failed evidence was erased or accepted as production success.
- New metadata-only Loki delivery matrix observes **53 pod/container series and
  68 host/unit series**, all four host identities, in one hour. Counts are native
  aggregation results, not log bodies. They are **not** full source coverage:
  registry join, absent/quiet/init-container classification and remaining app SDK
  paths (including Harbor and successful LiteLLM/Open WebUI inference) remain open.
- Added metadata-only storage/WAL/head/block observers: native numeric `meta.json`,
  stat/statvfs and memory, never chunks/index payloads or series labels. Initial
  measurements cover all four hosts; raw metrics ~18.67GB, Prometheus ~4.84GB,
  WAL ~1.03GB/head ~224MB on socrat-0; staged history ~21.02GB on socrat-1.
  Five-minute and hourly stores were empty at this observation, not assumed
  unnecessary. Hourly store placement is socrat-3, not socrat-2. Native Prometheus
  PVC remains 10Gi. History importer/publication were not touched.
- **Capacity gate refused socrat-2**: measured MemAvailable after observer pause
  was **303,226,880 / 2,062,471,168 bytes (~14.7%)**, below the required 20% memory
  reserve even without a new observer. Only the owned storage-observer service/
  timer were stopped/disabled there; existing agent remains active. Proposed
  observer budget was reduced from 128MiB to 32MiB but was **not enabled through
  the failed reserve gate**. On socrat-0/1/3 the bounded observers remain active.
  Maintained preflight now pauses only an existing owned observer before refusing
  inadequate reserve. No workloads were evicted, no VPN/Kuma/routing changed,
  no retention shortened, no history deleted. Tiny stateless blog/worker candidates
  were measured (~6MiB/~14MiB) but not blindly relocated: insufficient remedy.
- Full retention/peak/duration/metrics-history/WAL/compaction/replica projections,
  memory reserve remediation, all-signal outage/replay/recovery, rollback exercise
  and remaining credential lifecycle proofs are **not accepted**. The final 72h
  window cannot include pre-SDK-change epochs. No final acceptance, extra history
  loss, new commits or RAM certification is claimed.

### 2026-11-01 — trusted socrat-0 operational rehearsal and real LiteLLM inference

- Explicit operator update: treat **socrat-0 as healthy/trusted**, prefer new work
  there over socrat-2/3, and do not require an extra independent verification solely
  because of the old RAM findings. This is recorded as the operator's deployment
  policy, not a newly performed hardware diagnostic. Ordinary transfer hashes,
  exact history comparisons, nonoverlap and no-extra-loss requirements remain.
- Added `otel-operational-replay.py` and `ansible/playbooks/otel-operational-replay.yml`.
  Pinned stock Collector/Loki/Tempo/Prometheus copies execute on **socrat-0**, in a
  loopback-only network namespace, 3GiB cgroup/zero swap/CPU100%/420s deadline.
  Measured 20% memory reserve beyond the complete test budget is required first.
  All state is durable under `/var/lib/homelab-otel-operations`; no production
  process, scrape owner, queue, retention or historical importer is modified.
- Successful v4: all three synthetic backends stopped; input accepted once;
  native fsync queues retained data while Collector and the single global sampler
  restarted; all backends recovered. Native queries prove **9 exact metric
  timestamps/values at 5s cadence, 24 exact log records without multiplicity change,
  and 9 mandatory traces**, with no fixture POST retry/resend after restart.
- Successful v5 additionally changes the Collector batch timeout while stopped,
  restarts with queues still pending, stops again, restores the **exact original
  configuration bytes/SHA**, restarts, then recovers all three backends and the
  same exact dataset. Queue bytes remain metrics812/logs1059/traces1233 before
  restart, after restart and after rollback. Native preimage/restored SHA:
  `8da1de0793bc1f93a6c944ab7b978fbd2109def788c7dd2818854ffc2dacaa08`.
  Three Collector generations, two sampler/backend generations; outage-to-recovery
  ~80.03s. Anonymous TLS clients rejected on 29090/3100/3200/4318. Strict CA/client
  verification and TLS1.3 query client remain enabled. This proves an **isolated
  configuration rollback with pending queues**, not production scrape-owner rollback.
- The 30s tail decision completes before sampler restart. Durability of undecided,
  in-memory tail-sampling state is **not** claimed. Earlier failed synthetic runs
  are preserved: v1/v2 test leaves lacked required Authority Key Identifier under
  strict OpenSSL; corrected CA/SKI/AKI/KU/EKU profiles pass `openssl verify
  -x509_strict`. The curve restriction did not solve certificate validation and
  was removed. v3 omitted the native Prometheus 30m OOO setting: concurrent replay
  produced HTTP400/drop errors and failed exact recovery. Adding the production
  OOO profile, not weakening integrity assertions, yielded v4/v5. No production
  data loss is inferred from or excused by failed synthetic fixtures.
- Switcher now forwards **only a validated version00 W3C traceparent** alongside
  its existing backend auth/content headers. Zero IDs, malformed/uppercase/future
  headers are rejected; baggage, tracestate and arbitrary caller auth are not
  forwarded. Live predecessor SHA was verified before source-only rollout; old
  CPU pod drained naturally, GPU Deployment/model/profile/image/auth unchanged.
  A stale initial-receipt fence stopped subsequent vLLM reconcile (retained).
  Reconcile now passes an explicit protected current source receipt, validates
  that receipt against maintained source/live ConfigMap and completed drain,
  and succeeds without restarting vLLM. Source change updates the soak epoch.
- Real production LiteLLM **successful local inference** now verified: fenced
  single model route to the local switcher, already loaded qwen3.8-27b (no model
  switch/external provider), HTTP200, one completion token. Tempo trace
  `b96b829c9af1ac47b6895b4a81c31f4c` contains 9 spans, including native
  `Received Proxy Server Request`/auth/router/`litellm_request`, correctly descended
  from the separate-process synthetic W3C root. Sensitive synthetic markers absent.
  **No vLLM descendant in the same trace**: do not claim cross-app propagation.
  Installed LiteLLM callback source review finds incoming-context extraction and
  span creation; outbound propagation still needs a safe supported profile.
- Post-inference delivery queries executed on **socrat-0**: LiteLLM/vLLM each have
  one existing metrics target UP; exact container log counts619/326 over10m;
  synthetic prompt marker count **0 for both** over2h. Log bodies were not fetched.
  LiteLLM inference is no longer an open path, but all-app coverage is not accepted.
- Existing native host-memory gauges queried from socrat-0, without executing new
  observers/work on socrat-2/3: socrat-2 current available22.08%, last-hour minimum
  **13.84%**; socrat-3 current27.87%, minimum22.75%. Instantaneous recovery does not
  erase the reserve failure; socrat-2 observer stays paused. Existing 5s source
  counters show719–720 samples/hour; no blanket gap-free claim is made from counts.
- Validation: **232 OTEL tests +22 switcher tests passed**; local fixture's initial
  uppercase test used only numeric IDs and was corrected to genuinely uppercase
  hex IDs without relaxing validation. History/importer untouched, no new commits.
  Harbor, Open WebUI inference, full source classification/cross-app propagation,
  production ownership rollback/remaining credential lifecycle and complete peak/
  retention/compaction/WAL/replica capacity remain open. Final acceptance is not
  claimed; pre-source-change soak/capacity windows must not be summed.

### 2026-11-01 — accelerated metrics/history execution; SDK expansion deferred

- Operator prioritizes **production metric cutover and one-time complete supported
  historical replay**, not more SDK canaries. The final72h acceptance window is
  not a prerequisite to execute cutover/publication; exact canonical proof,
  nonoverlap, original preservation and unsupported-type exceptions remain.
  `otel-migration-policy.json.executionPriority` records this execution policy.
- Fresh live production ownership audit: native Prometheus OTLP receiver enabled,
  listenLocal=true; all four legacy ServiceMonitor/PodMonitor/Probe/ScrapeConfig
  selectors retired; Ready stock `otel-cluster`; sole metrics exporter is
  `otlp_http/metrics` to loopback `/api/v1/otlp`. NoTranslation, native OOO30m,
  scrape/evaluation5s and timeout4s preserved. Native queries: **78fresh/78UP**;
  successful native OTLP HTTP request counter increases over5m. Existing source
  exporters may expose Prometheus/OpenMetrics to the **Collector input**: this
  is not a second legacy scraper or a claim every application directly emits OTLP.
  OTLP is the transport; native TSDB/Thanos remains historical storage.
- Found actual history blocker: current **6,383,043,932-sample full OTLP roundtrip
  already succeeded**, canonical SHA unchanged. Native finalizer on socrat-1
  failed the20% disk reserve; dependent tail queue failed before any block import.
  Do **not** redo this completed roundtrip or call a failed waiting queue progress.
- Prepared sealed **8,918,220,800-byte** replica of the completed block, canonical
  receipt/manifest, six golden receipts, immutable nine-block tail archive and
  pinned tools. Source archive SHA:
  `9edcbb69a6d1eadbe3bbb315c26de9a0a3f0b2468f1e28ffed1c12fe6766e7ee`.
  Destination socrat-0 extraction requires exact SHA and a fixed safe destination
  allowlist, rejects links/traversal/devices/existing targets. No original deleted.
- Transfer failures retained: multi-host global ansible_host override caused a
  strict host-alias/port mismatch; fixed per-host mapping, **no known-host entry
  replaced or verification disabled**. Initial destination parent missing;
  corrected protected parent creation. Controller stream timed out after1500s
  at5,012,226,048bytes. Preserved and resumed exact remainder over direct private
  WG SSH using an ephemeral key restricted by source IP and forced exact archive
  tail command, no PTY/forwarding/arbitrary commands. Whole SHA matched before
  extraction; exact one-time authorization removed and private key deleted.
- Native verification on trusted socrat-0 passed stock Thanos index/query, but
  relocation initially lacked the fresh host's `staged/` parent. Native result and
  bucket were already verified; failed receipt retained, no importer rerun.
  Fixed maintained parent creation and added fenced `otel-history-resume-native.py`.
  Initial256MiB resume limit OOMed while loading the large manifest; retained
  journal, bounded2GiB retry completed. Exact canonical/native/source gates and
  untouched waiting-tail state required. Same-filesystem inode/size/mtime inventory
  verified during relocation. Completed block durably staged on socrat-0 as
  `01M6BBYTZHHWT579DX99J3S7EF`; failure receipts archived, resolved unit failure
  acknowledged only after verifying the success/native/durability receipt.
- **One tail importer is active on socrat-0** for9 immutable original blocks,
  4,170,768,866declared samples. New `socrat0-fast` profile: **6CPU/6GiB/zero swap**,
  GOMAXPROCS6/GOMEMLIMIT4GiB, vs conservative2CPU/3GiB. Fast profile rejects every
  other hostname. Combined finalizer+queue budget must preserve20% host memory;
  per-phase deadlines and disk floors unchanged. Uses same pinned converter,
  complete-source counts/canonical digests, native checks and single-importer lock.
  At last observation: active inventory of`01M66G9HT3YJ4W6TSADWG305M6`, completed0.
  No duplicate source import exists on socrat-1; its failed receipts remain.
- Maintained launch: `ansible/playbooks/otel-history-fast-socrat0.yml`; completed or
  failed result files block blind reruns. Success requires all9 canonical/native/
  durable receipts. Original OoO companion identities remain in the exact scope.
  Historical results are **staging, not production publication**. Nonoverlapping
  publication and full scope reconciliation remain required after replay; the
  retained failure is never counted as a migrated block or extra allowed loss.
- **236 OTEL tests pass**, compile/diff checks and accelerated playbook syntax pass.
  No commits, retention reduction, extra approved sample loss, blind routing/VPN/
  Kuma changes, or false complete-history/72h acceptance claim.

### 2026-11-01 — operator requests maximal safe socrat-0 resource budget

- Measured20logical CPUs, load~5, MemTotal33.326GB/MemAvailable17.31GB.
  Tail export consumes~1.13CPU cores; CPU quota has **zero throttled periods**,
  Go RSS~492MB, cgroup~2.77GB including cache; no OOM/memory-limit events.
- Raised the **running** service via persistent `systemctl set-property`:
  CPUQuota600%→1600%, MemoryMax6GiB→9GiB, IOWeight50→100, swap remains0.
  Capacity preflight reserves the full new9GiB against MemAvailable, leaving
  at least20% physical RAM+512MiB for production.16/20logical CPUs is a ceiling,
  not exclusive CPU ownership or a starvation guarantee.
- MainPID unchanged; no restart, no second importer, no discarded work, no
  production application changes. Preimage and effective-cgroup receipt retained.
- **No throughput gain claimed:** current export is primarily serial and was not
  CPU/RAM throttled. Its running Go process retains GOMAXPROCS6/GOMEMLIMIT4GiB;
  altering systemd ceilings does not mutate child environment. Maintained future
  fresh launches use16/9GiB and Go16/6GiB; interpreter source copied without
  restarting its active controller. Do not restart just to apply env: current
  queue is intentionally not blind-resumable. A genuinely parallel converter
  would require separate engineering/proof, not an unsafe mid-run binary swap.
- Evidence: `history-live-resource-increase-20261101.json`. Single importer,
  canonical integrity, disk reserve, originals and publication gates unchanged.

### 2026-11-01 — implemented and deployed real converter acceleration

Supersedes the prior resource-only change: operator explicitly requests converter
engineering to utilize trusted socrat-0, not just higher cgroup ceilings.

- `tools/otel-history/parallel_export.go`: bounded1..16workers, one canonical
  ordered source reader, stable sequence numbers; parallel protobuf/gzip/SHA
  writes with private compressor reuse. Immutable ownership, bounded backpressure,
  first-error propagation, failed/over-budget exports never get a manifest.
  Byte-for-byte identical serial/parallel files, full manifests, full roundtrip,
  infinities/NaN payload/stale markers, sparse resume and corruption refusal tested.
- Import previously allocated/sorted labels and used SeriesRef0 **per point**.
  Cache only contiguous equal validated attribute vectors and native SeriesRef;
  reset each batch/appender/Head boundary. Per-point semantics and final complete
  canonical verification unchanged; no concurrent importer/Head or unbounded cache.
- Benchmarked **on socrat-0**, bounded12CPU/1GiB/zero swap/300s, own synthetic500k
  points, no real-history imports: export1worker1.780082178s vs16workers0.334099707s
  (**5.33x**); full import uncached2.100894676s vs cached1.675226976s (**1.25x**).
  Not whole-job ETA, not a retention or complete historical acceptance claim.
- Built/tested with pinned Go1.26.7, no Collector/Prometheus/Thanos fork or changed
  dependency versions. `go test -race ./...`, `go vet ./...`,238Python OTEL tests,
  py_compile, Ansible syntax and diff checks pass.
- Guarded handoff playbook `otel-history-parallel-export.yml`: exact old/new SHA,
  exact active first-block export and no imported blocks, full inventory/native
  prerequisite, capacity guard, private binary/controller preimages **before**
  SIGINT to the owned migration controller. Python finally terminates/waits its
  export and preserves interrupted result. Old cgroup/MainPID required empty
  before atomic executable installation and replacement controller launch.
- New `--resume-export` accepts only first source`01M66G9HT3YJ4W6TSADWG305M6`,
  847,811,515samples, export phase, completed0, failed/interrupted receipt and no
  import/native stage. Reuses original full canonical inventory/extracted source;
  retained compressed batches must match original protobuf on replay. Incomplete
  last serial transport may be quarantined (none needed for actual handoff).
  Does not redo completed6.383Broundtrip or source inventory, never deletes history.
- Global importer lock now acquired **before all startup mutations**; duplicate
  controllers fail before touching receipts/cleanup. Failed resume preflights
  preserve previous receipts. Original interrupted result/logs archived; resolved
  legacy unit acknowledged only after replacement/lock proof. Base launch detects
  explicit handoff unit and cannot accidentally launch legacy controller again.
- Actual service `otel-history-tail-parallel-20261101.service` active with explicit
 16workers/--resume;16CPU/9GiB/zero swap and native guards. Initial actual measurement
  **5.34CPU cores** vs previous~1.13, zero throttles/OOM/limit events; processes are
  rechecking retained prefix batches before emitting further output. This measured
  CPU use is not a promise every stage saturates16cores or all stages speed up5x.
- Parallel-only executable SHA`bf1be9bf38af717ded209fd6f4776e6fe75a9b09e729145f35a53d5d01453bb3`
  runs the current export. Tested combined import-cache SHA
  `235650012ba0f062c27f6be701a6be9e72e5f8454237e176034f3193b81fa848`
  atomically installed for **subsequent** subprocesses, predecessor inode retained;
  controller PID/current export inode not restarted/modified. Updated maintained
  explicit pin and retained promotion receipt; no silent binary fallback.
- Production unchanged and fresh after handoff: **78fresh/78UP**, native OTLP
  requests continue. No SDK expansion, source history deletion, extra loss,
  receiver configuration change or commit. Historical publication still pending.

### 2026-11-01 — explicit50-worker request; no false speedup claim

- Implemented/tested1..50 bounded export pool;16CPU/9GiB/zero swap remain unchanged.
 50workers are goroutines, not50cores/importers. Fresh maintained fast profile
 selects50; root-only protected exact-workspace override makes the live
 controller's subsequent export select50 despite its cached16argument.
- Measured on trusted socrat-0 before selection: initial12CPU test16=0.32015s,
 32=0.33391s,50=0.37690s. Confirmation with16CPU,3repeats×5iterations:
 mean16=0.32081s,32=0.32062s,50=0.32722s (50range0.300..0.360s).
 **No stable improvement demonstrated**;50 selected by explicit operator request,
 not called a measured optimum or a whole-job acceleration guarantee.
- Current block already in **import** when requested. Did not interrupt/discard
 its Head/shards, reimport samples or claim50currently-active export workers.
 Atomically promoted tested executable for future subprocesses; predecessor
 executable retained, controller PID and current import inode unchanged.
- New converter SHA`ca3cf860b7735459fe5097caa5330e8f69478dc189b12a4d236b8dc2388422e0`;
 maintained pins updated. Effective settings validated from new binary using
 `--show-export-workers`: effective50/GOMAXPROCS16, samplesRead=false/exportStarted=false.
 Live cgroup caps16CPU/9GiB/swap0 verified, no OOM/limit events at transition.
- Exact serial-vs50 compressed-file/manifest test, race/vet suite and override
 owner/permission/symlink/schema/bounds tests pass;238Python tests unchanged.
 No production restart, source deletion, extra loss, retention/receiver change,
 second importer, commit or historical publication/complete acceptance claim.
 Evidence: `history-workers50-20261101.json`.

### 2026-11-01 — real import pipeline acceleration and checkpoint-preserving transition

- Operator again prioritizes actual throughput over idle-node/worker-count changes.
  Read-only inspection confirmed import at187.5Msamples,~1.55CPU, no quota/OOM
  constraint: inline gzip/protobuf read/decode and ordered native appends serialized.
- Implemented bounded16lane import prefetch, parallel file-SHA validation, single
  ordered native appender, unchanged all-point validation. Each lane at most one
  ready+one decoding batch, cancellation waits all workers. SHA/CRC/size/path/type
  errors reject input. No additional native mutable Heads or second importer.
- Overlapped **unchanged canonical-v1 SHA256 byte stream** with source traversal
  using one SHA worker/four256KiB buffers. Added up to4independent upstream native
  compactions per wave, separate compactor instances, combined20%disk reservation,
  conservative metadata-memory fan-out and serial fallback under reserve pressure.
- Real socrat-0 synthetic full-import benchmark500kpoints:1lane1.962623578s,
 4lanes0.729118472s,16lanes0.453936330s (**4.32x** vs1). Not whole-job ETA.
- To accelerate the **current** block without restarting from zero: read-only
  Native/OTLP prefix comparator verified147closed shards/**367,500,000samples**,
 73,500batches, all canonical digests/stale bits/counts exact. Whole source manifest
  SHA and native size/mtime/device/inode inventories bound proof. Newest live
  receipt excluded; unproven/count-only checkpoints never adopted.502.27s proof
  while old import continued; verifier ran inside existing16CPU/9GiB cgroup,
  GOMEMLIMIT512MiB, no independent capacity addition or second importer.
- Guarded `otel-history-pipeline-resume.yml` checked every native inventory before
  SIGINT to **only** old migration controller, preserved preimages/old native work/
  interrupted logs+receipts, required old cgroup empty and new pinned binary before
  replacement. New `--resume-import` only first source/importphase/completed0;
  source canonical inventory/export not redone. Rechecked proof and source/batch
  SHAs, adopted367.5Mprefix, reconstructed only remaining/unproven suffix into
  `restored-fast`. Old `restored` and all unadopted/failed artifacts retained.
- Actual active service **`otel-history-tail-pipeline-20261101.service`**, one Go
  importer+controller/one global lock;16CPU/9GiB/swap0 unchanged,50export workers
  retained for later exports. New converter SHA
  `c2b4fd258ebffb1f31d9caec4c05cbc803dce52b0365fb69f7efa74ba411a077`.
- First actual post-transition sample: **14.09CPU cores vs1.55before**, zero quota
  throttles/OOM/memory-limit events, GoRSS~908MiB, cgroup7.04GB including reclaimable
  file cache, MemAvailable15.53GB. Checkpoint **430,000,000samples** (367.5Madopted+
 62.5Mnewly appended). Do not confuse CPU utilization with measured end-to-end
  speedup; later ordered digest/native verification can still have serial limits.
- Confirmed actual executable/prefix flag/adoption log, old work retained, singleton
  lock held, resolved legacy unit failure acknowledged without erasing failures.
  Fresh native production metrics checked again; receiver/source config unchanged.
- Race suite/vet cover exact prefix adoption/full restored canonical equality,
  changed-native-shard refusal, canonical streaming byte equivalence, prefetch
  order/cancellation/corrupt-input failure and >16shard concurrent compaction.
 **239Python OTEL tests** pass; no production app/SDK restart, extra loss, original
  deletion, retention reduction, second importer, commit, false historical
  publication or72h/final acceptance claim.

### 2026-11-01 — offline publication ledger and serving/rollback preparation

- Added `scripts/otel-history-publication-plan.py`, a controller-only, read-only
  planner: no production network calls, TSDB chunk scans, moves, serving changes,
  importer restarts or publication authorization. Fresh metadata, exact canonical
  receipts and input-file SHA bindings produce an exclusive private output.
- Lightweight observations on socrat-0/1 found nine staged candidates and 55 live
  raw-bucket metadata entries. The 17-source planning ledger classifies four
  fully proven contained copies as **do not publish separately**, two missing old
  originals as requiring coverage/retention reconciliation, three completed
  candidate mappings as requiring a serving barrier, and eight tail sources as
  still waiting for completed roundtrip/native/durable receipts.
- Of 44 other live identities, four are native downsampled aggregates and 40 start
  after the frozen conservative legacy-boundary upper bound. All remain preserved;
  time classification does not certify native ingestion or full source integrity.
- First tail block has completed 847,811,515 exact samples, native query and durable
  staging. The second block has moved through append checkpoints into native
  compaction; it is not counted complete before the final receipt. Live metrics
  still show 78 fresh / 78 UP sources and successful native OTLP requests.
- `docs/otel-history-publication.md` defines pending execution gates and the reverse
  serving barrier. Cached Store identities mean filesystem rename/deletion marks
  alone cannot prevent co-serving originals and replacements. Historical writers
  must be fenced, queries drained and all affected serving routes withdrawn before
  any bucket mutation. This may need an explicitly approved historical-read
  maintenance window; uninterrupted historical availability is not claimed.
- The offline report is
  `migration-evidence/history-publication-preparation-20261101.json`. Validation:
  14 planner tests and all 253 OTEL Python tests pass. Existing production-owner
  rollback, unsupported-type scope, capacity/SDK and genuine 72h acceptance gates
  remain open. No extra sample loss, deletion, retention change, commit or
  production publication was performed by this preparation.
