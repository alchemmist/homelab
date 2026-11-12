# Moscow native-primary gateway — 12 November 2026

## Accepted change, not CPU-alert closure

Moscow (`socrat-4`) is now a native network host, NOT a Kubernetes worker.
The five remaining Kubernetes nodes0/1/2/3/5 are Ready. Three etcd voters remain
unchanged on0/1/2. The Moscow host, IPs, keys, routes and network services remain.
No k3s/WG/control-plane restart elsewhere, cluster drain, uninstall script,
iptables flush, default-route rewrite, human account or subscription change.

This supersedes the Pod-primary arrangement in
[vpn-mesh-runtime-20261110.md](vpn-mesh-runtime-20261110.md) and follows
[socrat4-cpu-tuning-20261112.md](socrat4-cpu-tuning-20261112.md).

## Current architecture

```text
Public client → Moscow native Xray relay → wg-socrat → existing NL VPN / ingress
                               (fixed targets)           → NL internet exit
HOME0/1/3 ↔ Moscow native management relay ↔ existing NL transport
Public DNS → Moscow local authoritative Knot (independent of NL / Kubernetes)
Moscow private DNS relay → existing NL private authority (still depends on NL)
Moscow native node-exporter → native OTel → existing cluster monitoring
```

These are configured dependencies, not discovered traffic edges or independent
backup routes. Moscow still shares its VPS/CPU/NIC and the existing WG path.
Removing its worker role does NOT remove Moscow from the HOME↔NL failure domain,
make VPN independent of NL or repair provider CPU steal. Rancher no longer lists
it as a cluster node; Grafana host metrics/logs retain node/host_name=socrat-4.

## Controlled sequence and source

1. Read-only inventory found only the relay Deployment pod and node-exporter
   DaemonSet on4, no PVC workload. Native telemetry scrapes127.0.0.1:19100 and
   labels the series10.250.0.40:9100; it does not depend on the DaemonSet.
2. Published the late-native reconciliation fix plus guarded native-primary
   controller modes. `moscow-native-primary.yml` defaults to preflight, checks
   exact config/binary SHA, placement/owners, health and current mode. It saved
   private before-state/controller, validated and installed the reviewed tool.
3. Authenticated HOME baseline passed five protocols via literal public Moscow.
4. Explicit activate used the existing lock/marker/owned-PID handoff: persist the
   fence, stop only worker4, terminate only the identified relay, refuse unknown
   port owners, start the identical native Xray/config, validate real TLS/WS path.
5. The SAME five authenticated checks passed in native mode. Then fixture and
   temporary native API tokens were removed, original tokens/config preserved.
6. Explicit promote accepted native-primary. Timer remains active, native is
   boot-enabled, marker retained. An accidental failback/activate is rejected in
   this mode. Explicit demote is rollback preparation only, not an agent start.
7. GitOps changed vpn-transit replicas1→0; Argo confirmed Synced/Healthy.
8. `moscow-retire-worker.yml` required native acceptance and actual desired0.
   An exact reviewed pod snapshot bounded process retirement. The runtime helper
   identified pod cgroups, container IDs, shim namespace/IDs, PID starttime and
   command identity; unknown ownership aborts. Only remaining owned pod tasks/
   shims were stopped. No blanket cgroup kill, CNI reset or networking flush.
9. Disabled worker boot and deleted ONLY the retired Node object with a
   server-side UID precondition. Orphan pod objects subsequently disappeared.
   No runtime images, kubelet config, certificates, keys or other rollback data
   were deleted. Worker enrollment play now refuses an existing native fence.

Published commits: eabc39a6, c67b2b71,5fb87fba,7edd0e16. Source and runtime preserve
Xray SHA a27e3f95ab6ce270956d0cecd32eda4686a811afc71c64a6a734a3dede14883e and shared
user.json SHA c1e7d7cf08f43dc3bfd71ca87b08e339029c95d02115e533034a9ed2a8048e11.
Other unreviewed local recovery commits were not bulk-pushed.

## Verified acceptance

- Five protocols before/after handoff: REALITY, Trojan, VLESS32083, VLESS32084,
  userspace WireGuard. Each authenticated, returned200/65536B/expected SHA and
  independent NL exitIP. Fixed HOME WAN, not mobile/Happ or AWG acceptance.
  These checks followed native handoff and preceded leftover-runtime retirement;
  the native service remained running without restarts through retirement.
- Temporary fixture removed; temporary tokens removed; original native tokens
  and proxy configuration preserved, verified by the helper's cleanup receipt.
- Six-host audit: all36including-self ICMP/SSH combinations passed, i.e.30directed
  inter-host paths. This is not full UDP/MTU or application acceptance. Collection
  initially failed for3 using stale NetBird/IP overrides; corrected only the
  diagnostic connection to the existing strictly pinned SSH alias through Moscow.
- Five cluster nodes Ready, no pod objects left assigned to4, desired relay0;
  no k3s-agent/containerd/shim processes left on Moscow.
- Native user relay, management relay, DNS relay, Knot, OTel and exporter active;
  native relay and Collector restart counters0 since their activation.
- Moscow public authority SOA over UDP AND TCP passed from Mac. HOME/Moscow
  authorities returned the expected Moscow VPN A. **Public NL UDP53 timed out
  from Mac during closeout**, an unresolved connectivity observation, not a full
  public-DNS acceptance. Existing NL/Moscow DNS-path issues are not closed.
- n8n→SPI service short-name health200 after final retirement. Thanos Moscow
  host metric age~1.3s; Loki865new Moscow records/5m, count-only/no bodies exported.
-32focused regression tests, Ansible syntax and Helm lint passed. No reboot,
  provider-console, whole-cluster-loss or independent DR proof claimed.

## Resource outcome and outstanding warning

At18:47:54–18:52:54UTC, a300s post-retirement sample recorded:

| Metric | Result |
|---|---:|
| Host MemAvailable |~544MiB (earlier baseline~350MiB)|
| Host used RAM |~423MiB (earlier~617MiB)|
| WG RX |4.56MB/s|
| CPU PSI some |41.7%|
| CPU user/system/softirq/steal/idle |9.1/18.7/18.7/3.5/49.5%|
| Collector CPU |2.04% of one core|
| Export queues |0|

**SocratNodeResourceContention remained firing**, latest rule ratio~41.5% versus
25% threshold. Current traffic was almost3× the earlier1.56MB/s baseline, so this
is not a controlled CPU before/after benchmark. RAM headroom improved; CPU-alert
elimination is NOT established. No alert threshold/routing/silence was changed.
Pre-existing cloud-init main/network failed-service warnings also remained;
no reset-failed or unrelated cloud-init repair was performed.

If CPU contention must be eliminated at this traffic level, evaluate more usable
CPU capacity or a separate, bounded reduction of transport processing. Removing
more tiny monitoring processes cannot be represented as a guaranteed fix. Do not
keep reshaping the alert solely to obtain green status.

## Custody and rollback

Root-private4 receipts/controller/state:
`/var/lib/homelab-recovery/20261112-moscow-native-primary/`.
API fixture/cleanup evidence on2 and before/after HOME proof on0 remain private
under `/var/lib/homelab-vpn-hardening/vpn83-native-*-20261112`.
Controller reviewed receipts initially `/tmp/socrat4-native-primary/`; selected
receipts retained in the owner's private Application Support evidence directory.
Temporary escalation file and local fixture configuration removed.

Rollback is a separate, narrowly reviewed operation:

1. Restore GitOps relay replicas1; leave native forwarding while the Pod waits.
2. With native healthy and fenced, explicit controller demote returns mode=native
   without starting an agent/removing the marker.
3. Re-enable worker boot (do not run enrollment/uninstall); explicit bounded
   failback stops native, releases fence and starts the preserved worker. Node
   re-registration and hostNetwork Pod recovery must be accepted afresh.
4. Inspect receipts on any uncertainty; do not replay activation, kill unknown
   port owners, remove the marker by hand or promise rollback is seamless.

A failed primary path keeps the fence; the native systemd Restart policy remains.
Normal watchdog ticks never restart the retired worker. Full reboot is untested.
