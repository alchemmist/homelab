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
