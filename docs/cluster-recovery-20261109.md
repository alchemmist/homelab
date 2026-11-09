# Cluster recovery — 2026-11-09 (in progress)

Owner confirmed VPN and Telegram bot functional, then authorized full recovery,
root-cause analysis, DNS/IP resilience review and prevention. No subagents/new
checkout, cluster/etcd reset, database deletion, alert masking or broad restart.
Preserve unrelated dirty monitoring work and historical data.

## Confirmed baseline / risk gates

- All4 nodes Ready, no Kubernetes Memory/Disk/PIDPressure; Umami Progressing.
- Initial firing alerts: observer membership critical; Umami crash/replicas/service;
  LMS service503 and backup overdue; two old failed broker jobs; node3 I/O;
  Prometheus compaction failures (rule increase over3h, for4h). Watchdog firing is
  the intentional monitoring heartbeat, not an incident to disable.
- New broker jobs logged refresh_ok; historical failed Jobs are not proof of an
  ongoing broker outage. Pending observer(32Mi) and Thanos cascade(128Mi) explicitly
  unschedulable on node0: Insufficient memory requests, not actual exhausted RAM.
- node0 allocations31752Mi (99%); vLLM requests12Gi / limit24Gi. Measured7d max
  working set6.142Gi. Native authenticated current metrics: running0, waiting0.
  Reviewed request10Gi retains limit24Gi/model/image/GPU/PVC and frees2Gi.
  Existing deployment strategy Recreate; preserve proof-gated OTel overlay and
  graceful termination. This is a targeted vLLM lifecycle action, not cluster restart.
- node3 IO PSI some~41%, full~34%; free disk376Gi; available RAM~1.27Gi.
  3s per-process sample: otelcol-contrib wrote4.63MB, dominates physical writes.
  Disk pressure cause needs queue/fsync/traffic validation; do not disable fsync,
  discard queues, drop logs or move durable state into RAM as an expedient fix.
- Umami startup ERR_INVALID_URL input undefined; umami-env has no keys. DB pod
  still running since Oct30. Chart lookup-dependent Secret template is unsafe
  under offline Argo Helm render; exact time/cause of secret loss not yet proven.
  Recover original machine values from private preimages/runtime/snapshots; no
  password/key rotation or application database restore merely to fix env.

## Night control-plane incident (confirmed observations, not complete attribution)

node0 journal: lost leader at Nov9 02:30:51+03 and02:37:53+03; repeated raft/API
errors afterwards. node1 k3s NRestarts458, active only since12:37:20+03. Its log
repeatedly reports checkInitialHashKV failed / found data inconsistency with peers.
With VPS also unavailable/fenced, losing a second voter explains unavailable
quorum. File names containing corrupt.go are not alone proof of damaged data.
node1 journal also has suspend entry/exit; exact timing/causality still unverified.
Do not disable initial corruption checks or rebuild membership speculatively.

Fresh official etcdctl3.6.14 was verified against upstream published SHA256 and
used only for administrative read-only checks (no server upgrade/system install).
Current native member list: node0 at192.168.0.23, node1 at192.168.0.24, VPS at
10.250.0.2. All3 endpoint health true, same leader/term32, applied indexes caught up.
At common revision17021458 **all3 hashKV=2356663187**, compact revision17015772.
Thus no current same-revision inconsistency observed; underlying night cause open.

Consistent native snapshot before service repairs:158638112 bytes, SHA256
`2dfeeeecb1ed1bfd46cf5246c59ebb27b2ee451a984c3944849455aff6ae582b`.
Snapshot/bootstrap recovery material protected0700/0600 on node0 and verified
identical off-host private controller copy. No production restore or restore test.
Private index: node0 `/var/lib/homelab-recovery/20261109-etcd-audit/`; controller
`~/Library/Application Support/homelab/recovery-20261109-etcd/`.

## DNS / blocking / VPN scope

Both public authoritative NS currently answer matching SOA and dual HOME/NEW
vpn A records. Parent ns2 glue NEW was separately verified. One NS/IP loss can
leave DNS resolution available through the other, not ensure backend availability.
Renderer probes only TCP443 per entrance and independently renders each authority;
partition disagreement, service-specific failure, literal-IP VPN clients, single
VPS STUN/VPN and shared HOME power/ISP remain limitations. Both-down publishes
both addresses, not a live healthy failover. No demonstrated external quorum
publisher yet. No hard guarantee from TTL60, dual A or two NS.

No evidence yet establishes targeted blocking caused by our hardening changes.
Selective old-IP reachability was historically observed; renumbering/stale binds,
control-plane quorum and application faults are separate proven layers. No blind
Xray port/key/client rotation, plaintext downgrade, DNS-only failover promise or
claim that encryption prevents IP blocking.

## Remaining work

1. Recover scheduler headroom and observe natural jobs/backup catch-up.
2. Recover original Umami env, remove destructive ownership hazard, pin reviewed
   app image; preserve users/analytics/keys and prove API heartbeat.
3. Diagnose LMS503 and overdue backup against existing HA owner.
4. Validate real compaction health/history preservation, not merely erase alerts.
5. Diagnose and reduce node3 IO amplification without durability loss.
6. Correlate night hashKV/power/network timeline and install prevention gates.
7. DNS consistent publishing / external vantage and real independent VPN fallback
   require separate live acceptance; no testing by taking down the working path.
8. Natural successful jobs and stable cleared alerts, off-host restore exercise
   and mobile/HTTP/API acceptance before declaring full recovery complete.

## Service repairs and preservation receipts (Nov9 ~12:15UTC)

### Umami restored, not reset

Five scheduled snapshots (Nov6–8) already contained the empty Secret, so its loss
predates the Nov8 night outage/hardening. Nov1 worker-verified snapshot preserved
original3 keys. A private read-only bbolt reader (official Go module checksum
verification; no etcd server/restore) extracted only the target Secret into private
files. Original Secret UID matches live; recovered DB password matches running
PostgreSQL machine environment. No human credential login/bypass, role changes,
password regeneration or database restore.

Before restore, native pg_dump custom archive2222786 bytes, SHA256
`3a5f96e714fa7603b9904489437f2963574b667b0caec01200c91cf1ccf61651`.
Native Kubernetes API UID/resourceVersion CAS restored exactly original3 keys.
Externally owned Secret retained/Prune=false/IgnoreExtraneous. Removed destructive
Helm lookup/empty-placeholder rendering and pinned the already-running image digest,
not an application upgrade. App recovered on natural container retry. Root200,
`/api/heartbeat`200 `{"ok":true}`, Deployment1/1 and Argo Synced/Healthy verified.
Private source/recovery evidence on node0:
`/var/lib/homelab-recovery/20261109-umami-{snapshot-reader,restore}/`.
No raw secret or analytics dump in Git/controller output.

### LMS private Authentik path corrected without web restart

LMS root503 `Sign-in is temporarily unavailable`, healthz200, machine OAuth client
fields present and match running process. Its pod is on node3. DNS override from
Nov8 maps Authentik to192.168.0.250. From that actual LMS pod, VIP443 failed errno113;
strict-TLS metadata through existing TraefikService10.43.218.222 succeeded200 with
correct original issuer. Do NOT globally switch DNS back to ServiceIP: the restricted
observer network intentionally cannot reach that target (Nov8 accepted evidence).

node3 routed VIP over enp2s0/src192.168.0.109, no VIP mesh prefix. HOME0 owns VIP
locally and serves strict-TLS metadata200. Corrected only node3 HOME0 peer AllowedIPs
with192.168.0.250/32 plus corresponding /32 route, persisted exact file scalar.
Private preimages/hash approval/full-static-peer verification: no key/endpoint/other
peer change, no WireGuard restart, no Mac/global DNS/corporate route modifications.
Native Authentik URL/Host/SNI/issuer/TLS/client credentials unchanged. Actual LMS
root now303 (normal login redirect), healthz200; service-unavailable alert cleared.
Previous DNS acceptance missed node3/LMS: this is our compatibility gap, not proof
of public-IP blocking. Private state node3 `20261109-worker-vip-route/`.
**Limit:** this mesh VIP route is anchored through HOME0. Not a full HOME0 power-loss
HA solution; do not claim independent-site resilience from this local repair.

### Effective request owner corrected; no second model restart

Initial chart10Gi changed Deployment/ReplicaSet, but CREATE-time native admission
still overrode new Pod to12Gi. Jobs briefly ran during the first rollout and then
became unschedulable again. Corrected authoritative catalog
`ansible/vars/container-resources.yml`: vLLM request10240Mi, limit24576Mi unchanged.
Only the corresponding scalar in existing native admission profiles expression was
CAS patched after server dry-run; no other profile/binding or blanket reconciliation.
Future-Pod server dry-run verifies10Gi. Native Pod resize subresource reduced only
running Pod memory request12Gi→10Gi; UID/containerID/full remaining spec unchanged.
No second model restart, eviction or GPU/model/cache/SDK changes. Updated7d peak
including startup9.257Gi; request is not a limit, retained limit24Gi.
Private state VPS `20261109-vllm-effective-budget/`. Kubelet/scheduler and natural
job freshness still require final readback before claiming scheduler acceptance.

Remaining at last Grafana read: membership freshness critical (before effective
owner correction), historical failed broker/Thanos jobs, historic Umami restarts,
Prometheus compaction, node3 I/O and fwupd-refresh. Watchdog intentionally firing.
LMS/backup and Umami availability alerts no longer firing. Full recovery NOT YET
accepted; do not replace root-cause work with deleting/silencing alerts.

## Night timeline and prevention gates

Native persisted journals on node1: Nov9 **02:30:45+03** logind received
`suspend-then-hibernate` from **upowerd**, then kernel entered s2idle; **02:31:02**
resume. node0 lost etcd leader at **02:30:51**, six seconds after suspend. With VPS
also unavailable, losing a second of3 voters explains loss of write quorum.
HashKV failures/restart loop after resume prolonged unavailability. Exact origin
of that hash mismatch remains open; current common-revision hashes agree.
UPower invocation is consistent with battery critical-power policy, not a lid event;
there is no retained UPower battery-percentage event in the queried interval.
Current node1: ACAD online1, BATT88%, not charging,981cycles. Do not disable critical
battery protection or initial etcd integrity checks. Owner should verify physical
adapter/cable/outlet and battery condition; software cannot promise power availability.

Added native source rules: voter AC loss2m warning; voter battery<20%2m critical
(even with a weak connected charger); fresh healthy-voter evidence<3 for1m warning,
<2 for30s critical. Existing node_exporter power/etcd metrics already delivered.
Missing/stale telemetry is explicitly health **unproven**, not proof of corruption.
No automatic resets/restarts/membership mutation. Native promtool7 scenarios cover
healthy, unplugged, low battery while online, one/two voters missing, no telemetry,
and stale third voter. Four new graph mappings generated through existing owner;
200 current rule entries/188 unique mappings/29 dashboards. Runtime activation and
quiet healthy evaluation still require fresh readback.

## node3 native persistent-state compaction

Rotating sda HDD. Six-second fsync-only trace:137 completed log-queue fsyncs,
47 filelog-cursor,12 metric-queue (including resumed-thread calls). Sustained disk
~80–93% busy/~42–47 flushes/s, despite small throughput. Metrics queue logically0
but file154763264 bytes; logs~25MB pending but file151031808 bytes. No compaction
configured. This is write amplification evidence, not proof of failing hardware.

Pinned existing collector **0.164.0** validated additive native `file_storage`
`compaction.on_start=true,on_rebound=true`, same-filesystem private temporary dir.
`fsync=true`, no recreate, same queues/IDs/retry/backpressure/privacy remain.
Only node3 agent was gracefully stopped, all original queue/cursor files archived
and every file hash verified in archive **before** native start. Backup26921436bytes.
Agent-only lifecycle26.66s, oldPID210358→2975087; no other unit/Prometheus/K3s/app restart.
Private evidence node3 `20261109-agent-native-compaction/` includes original config,
pinned-native validation, approval, consistent archive/hash receipt and lifecycle.

Native health13133/metrics8888 HTTP200. Metric file shrank to4194304bytes; log file
33579008bytes; original unused2MB queue preserved. Log queue21.68MB and decreasing,
new-process sent315 log records, filelog refused0. Initial I/O remained high during
warmup/backlog; do NOT claim contention alert fixed merely from smaller files.
Source config adds future native rebound reclamation without durability reduction.

## Prometheus WAL: pre-existing corruption, forensic stage only

Native logs every2h confirm segment00001786 CRC failure; fresh blocks continue to
be written successfully. This same segment was already documented **Nov7 09:00UTC**
in monitoring split acceptance, before this night. Do not attribute it to Nov9
suspend or to the DNS repair. Its PVC is **local on node0**, not NFS. Current image
Prometheus3.15.0-distroless; admin snapshot flag disabled. Do NOT enable it by a
restart: startup WAL repair could truncate later data.

Old sealed segment134217728bytes copied read-only and SHA verified:
`9f7a11ba33ced389ef70411989228ecf0fd323e1784c48f96c27b8f053542c93`.
Latest active segment2679, old segmentmtime unchanged. Offline CRC32C audit finds
exactly one invalid fragment. Unique one-bit candidate at byte129878544/mask1
restores its original expectedCRC; candidate has **zero** invalid physical CRCs,
SHA`8402d0e3a1ee44ccaf5a2bbb33f125f3f8b6a4fff37be59fbf100e9483c6157e`.
This is a **private candidate only**, NOT accepted production repair or guaranteed
semantic equivalence. Need pinned-native logical record decoding/cross-check,
off-host preimage, full sealed-file/identity/CAS plan and explicit preservation gates.
No production WAL write/truncation/deletion or Prometheus restart performed.
Private state node0 `20261109-prom-wal-forensics/`.

### WAL exact repair applied 13:34UTC; native checkpoint still pending

Pinned upstream Prometheus **v3.15.0/modulev0.315.0** reader accepted all6409 logical
records (CRC+Snappy) in candidate. Affected record type2:11716 distinct series,
all at **2026-11-04T04:07:20.560Z**. Resolved every internal ref from native preceding
`checkpoint.00001785` plus unmodified earlier Series records. Compared against
**raw-resolution Thanos** with `partial_response=false`, exact1ms range and exact
origin job/instance. **11716/11716 match exact labels/timestamp/float64 bits**,0
missing/different/conflicting, including +Inf; no NaN/stale-marker ambiguity.
Only constant operator external labels `prometheus`/`prometheus_replica` removed
for comparison; other labels fully preserved. Local direct Prometheus had no
samples this old; this was NOT treated as data loss or used as repair evidence.

Both128MiB original and candidate independently copied off-host to controller's
private recovery directory and SHA verified; Umami pg_dump/original machine-env
and agent consistent archive also copied privately with0700/0600 modes.

Approval`b08e1ad798d16fa584d1d7c08dbb4f87a9ea88718ddb54b44c56032501578667`.
Fresh full-file SHA/inode/mtime, same Pod UID/all container IDs, sealed segment
(latest much newer), exact one-byte/mask1 delta checked before replacement.
Fsynced temporary on same filesystem, retained ownership/mode/xattrs, rechecked
original SHA immediately before atomic rename, fsynced both directories.
Live readback SHA equals verified candidate. Same Pod and all processes; no
Prometheus restart, other WAL segment write, truncation, replay or sample insertion.
Original immutable preimages retained on node0 and controller. Write receipt
`20261109-prom-wal-forensics/one-bit-repair-receipt.json` accepted.

**Not yet complete:** native next scheduled checkpoint/truncation has to succeed
and scan subsequent segments; old counter-based alert naturally retains failures
for3h. Do not silence/reset it or restart Prometheus to speed acceptance. This is
an exact bit correction with independent historical-data proof, NOT attribution
of the physical bit-flip to disk/RAM/power or proof every later segment is sound.

### Effective memory, observer and power rule live readback

13:48UTC: vLLM Pod request **10Gi**, kubelet `containerStatuses.resources` **10Gi**,
`allocatedResources` **10Gi**, no resize conditions, Ready=true; same UID/container
as before native resize. CPU/GPU/24Gi limit unchanged, no second model restart.
Observer natural job `observer-membership-29903868` completed13:48:13 with0failed.
No critical firing alerts in13:47 query; observer critical naturally cleared.
Four new `socrat-control-plane-safety` rules exist live. Check actual rule engine
health/healthy evaluations separately before claiming prevention acceptance.

### fwupd and retained failed jobs

Node3 packaged `fwupd-refresh.service`: most recent failure13:13UTC, exit1. Exact
native metadata-only command later returned2 (`Metadata is up to date`). Existing
packaged `SuccessExitStatus=2 101` already handles that case. Starting **only** this
metadata service naturally completed with Result=success/exit2; no unit change,
`reset-failed`, software upgrade or firmware installation. Original metadata error
mechanism still not proven from retained quiet output; do not claim an I/O cause.

Three failed terminal Job objects remain intentionally unchanged, preserving
failure evidence; Pods already absent when investigated. Native deadlines:
Thanos3600s, both brokers120s. All owners have successful **natural**, not forced
replacements: Thanos13:30:07; SPI and Wiki broker13:40:05. Failed objects and current
CronJob preimages stored privately on node2 `20261109-failed-jobs/`. Do not delete
objects/change their failure status or alert conditions just for green. Exact
historical scheduling cause should be checked against retained earlier inventory.

Node3 after warmup: log queue8.98MB vs~25MB before, sent27512, both receivers refused0;
metrics queue0. HDD still83–88% busy/~37flush/s; IO full5m~34%. Catch-up continues.
Compaction alone is **not** sustained I/O acceptance. Native sending-queue batching
was source-reviewed: persistent enqueue/dispatch/ACK still fsync per original
request, so do not add it/restart agent claiming it solves the HDD IOPS limit.

### 14:06UTC safety engine / VPN / DNS review

Native `/api/v1/rules` returned all4 new rules **health=ok,state=inactive,no lastError**,
lastEvaluation14:06:14UTC. Actual fresh unique healthy-voter expression=3. This
accepts evaluation, not delivery of a test notification or physical UPS protection.
WAL checkpoint still1785 at14:06; no new native compaction logs in prior30min, so
next normal cycle is still required (expected15:00UTC). Do not claim completion.

Fresh online SQLite backup-to-memory integrity audit:17 identities/91 links now,
not the earlier16/85. Exact projection against private Nov8 baseline proves **all
original16 identities and85 bindings still present and completely unchanged**;
only1 identity/6 links added by an external/concurrent activity. Origin of that
addition was not attributed in this recovery; no deletion/rollback authorized.
Transport targets remain Yahoo/Sony/AMD;32063 disabled; encrypted WG/AWG unchanged.
Trojan backend has no TLS itself by design behind strict-TLS443; do not mislabel
this as an exposed plaintext listener. No speculative port/key/client rotation.

Read-only backend check isolated a compatibility defect: NetBird inserts exactly
one `iifname nb-host counter accept` into this input hook chain. It cannot match
eth0 and is redundant with existing chain accept policy. Two original owned eth0
rules remain exact. Validator now accepts **only this complete expression**, at
most once; rejects different interfaces/extra expressions/duplicate/missing or
modified public deny/foreign owner.47 tests+3 subtests pass. Only validator Python
file replaced with matched-source preimage backup; no nft mutation, `--ensure`,
unit reload/restart or NetBird change. Fresh live read-only validation accepts5
objects, owned rules byte-semantically unchanged. HOME→NEW443 open,12096/32087
explicitly refused after change. Receipt node2 `20261109-vpn-final-review2/`.

Thanos failed Job scheduling cause now directly confirmed by retained earlier
inventory: `thanos-cascade-29903670-5qm7q` at10:30 had `Unschedulable`,1 insufficient
memory/3 wrong node selector; requested128Mi on node0. Do not extrapolate this as
proven exact cause of both broker deadlines where old Pods are already absent.

DNS review: `public_dns_zone.py` probes only TCP443, each authority refreshes its
own zone independently (local loopback/LAN for itself, public IP for peer). During
partition they can publish inconsistent answer sets; when both checks fail the
renderer deliberately keeps both addresses. TTL60 and2 NS improve lookup and IP
publication availability, **not service readiness or coordinated failover**.
A living Traefik443 can still serve502/503 when Authentik/DB/etcd/backend fails.
NS1/NS2 glue is correct; no new REG.RU write needed. Seven subscription endpoint
addresses remain literal VPS IPv4: DNS changes cannot move existing clients.
HOME forwarding to same VPS, shared stateful services and VPS-only relay are not
independent backup sites. Same-prefix address change is not proof of TSPU blocking.

For a future separately accepted HA phase: one fenced authoritative publication
owner with native signed primary/secondary transfer, independent-vantage HTTPS
SNI/issuer/backend checks per service (and real VPN/STUN/TURN checks), failure
hysteresis and tested client retries; independently available stateful dependencies
and a genuinely independent VPN endpoint. Do not replace working literal addresses
with round-robin DNS or claim that alone solves single-VPS loss. Current scope did
not purchase a second provider, redesign DB/storage HA or change client credentials.

### Durable queue fully drained; rotational-worker checkpoint fix accepted

14:16 native logs and metrics queues **0**, new-process43482 logs delivered,
filelog/journald refused0. Native Loki metadata-only mTLS query confirmed412 fresh
node3 records/5m (no log bodies fetched). Empty queue alone did not fix host PSI:
after-drain60s mean HDD38.87% busy/18.78flushes/s, PSI some~15% remained above10%
alert threshold. Do not alter that threshold or turn off fsync.

Native old frozen filelog config had implicit default200ms polling and neither
receiver had effective infinite retry (common source already had filelog retry).
Applied **only node3**: explicit filelog polling1s (still below kubelet rotation
check cadence), native infinite retry for both receivers. Files/journal remain
original durable sources until downstream persistent acceptance; no asynchronous
pre-persistence batching, storage/cursor reset, privacy/scope/queue-ID changes.
Existing collector0.164.0 validated full candidate with original environment.
Approval`aa2f0d66bc6fbe3ca6e2f312b13d496a7c3fb4e9e20d01a26558c4e3debd0eee`.
Graceful agent-only stop, all original state archived/hash-verified offline before
atomic config/start; backup3393222bytes, lifecycle5.22s, newPID3027074 (historical).
Receipt node3 `20261109-agent-checkpoint-cadence-v2/`. No other unit restarted.
Both consistent agent archives also copied off-host and SHA verified.

After change60s mean HDD **17.04%** busy/7.37flushes/s; PSI some avg60 **7.97%**.
14:40 actual recorded5m I/O ratio **0.06915** and contention alert **naturally cleared**.
Post-change native Loki confirmed **522** fresh node3 records/5m. This accepts this
observed load, not a guarantee an HDD handles arbitrary future bursts. Keep native
fsync/durable queues/retry protection. Source tests assert1s/retries/no async batch.

### Fresh post-recovery preservation

All3 etcd voters healthy/common leader and **common revision17146862 hashKV equal**.
New native consistent snapshot159092768bytes,
SHA`d4ebdd595f8db0820845d880b8ab81d73480159a8db09ebcd73394778616cb5e`;
includes original restored Umami Secret and current admission/rule state. Existing
SHA-pinned3.6.14 client used; no reset/restore/skip-integrity flags. Original baseline
snapshot retained. Current panel native online backup401408bytes,17/91 intact,
SHA`d3a5d0a010c92cb456e46a321204a73f6c440c355eb14d7a3270921b83ef7516`.
Both copied privately off-host and SHA verified. This is preservation acceptance,
**not an isolated full restore exercise or hourly automatic shipping acceptance**.

Scoped independent-history witness11716 samples and every WAL repair/decoder/plan
receipt now also off-host; witness
SHA`8a4bb7de653b88c4accb5d49fae86c3fb85fa947a4627f7822db2052d6d0eb6e`.
One multi-host fetch timed out *after* all WAL proofs arrived; existence/full witness
SHA checked, only missing node2 receipts subsequently fetched. No production write
was repeated. Native snapshot, panel backup, both agent archives and bootstrap
credentials stay outside Git in0700/0600 recovery storage.

14:40 firing non-housekeeping conditions now only3 historic `KubeJobFailed` objects
and `PrometheusTSDBCompactionsFailing` historical counter. Native next checkpoint
still awaits normal cycle; do not manufacture a green result before it runs.

## Final functional gate: native checkpoint accepted 15:10UTC

Read-only native log-follow awaited the **normal** cycle, no sleeps/polling/restarts
or admin mutation. At **2026-11-09 15:10:03UTC** Prometheus emitted:
`WAL checkpoint complete first=1786 last=2388 duration=9m54.8148835s`.
New native `checkpoint.00002388` exists; original1785 boundary advanced. No new
compaction failure in watch. Same Pod UID and **all original container IDs**.
This accepts the repaired segment and subsequent scanned range through2388 with
standard native checkpoint/retirement; no manual WAL truncation/deletion/replay.
Immutable original/candidate and scoped historical proof remain on node/controller.
Read receipt `20261109-prom-wal-forensics/native-checkpoint-functional-receipt.json`.

15:14 native alerts: **no critical**, I/O contention absent; node3 actual5m I/O PSI
**5.43%**. Remaining warnings:3 terminal old `KubeJobFailed` objects and compaction
counter's **historical3h window**. Do not reset counters, rewrite terminal statuses
or silence alerts. Old Job objects have no configured TTL; do not promise they'll
expire automatically. Their later natural successful jobs/consistent cluster-state
snapshot and diagnostic archives are preserved; a deliberate retention/archival
policy is separate from pretending they never failed.

15:15 fresh native checks: all4 nodes Ready, **no active nonready Pods**. Native
strict-TLS LMS root **303** and Umami `/api/heartbeat` **200 {ok:true}**. Latest
natural observer success15:15:12, SPI broker15:00:07, Wiki broker15:00:04,
Thanos cascade14:30:08. No manual workflow execution or test mailing.

Remaining limits: exact historic node1 hashKV mismatch cause/physical bit-flip
mechanism not established; UPower battery threshold event not retained; owner
must inspect laptop power/battery. No full isolated cluster/data restore exercise,
automatic hourly off-host shipping, mobile-network VPN or NetBird interactive
login acceptance is implied. DNS consistent failover/stateful/site HA and an
independent second VPN provider were not silently implemented. Functional recovery
is accepted; claiming every warning/history/independent blocked project is green
would be false.
