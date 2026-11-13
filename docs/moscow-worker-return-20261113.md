# Moscow worker restored —13November2026

## Owner-directed correction

The owner rejected permanent removal of socrat-4 from Kubernetes as a resource
optimization. Moscow MUST remain a worker; capacity upgrades are preferable to
retiring membership. This supersedes the native-primary target in
`moscow-native-primary-20261112.md`. Native systemd is a local fallback, NOT the
normal architecture. No worker uninstall or reenrollment was required.

## Source and bounded operation

-30091cb7 restores vpn-transit desired replicas1 and adds
  `ansible/playbooks/moscow-return-worker.yml`.
- Default phase is read-only preflight. Apply requires explicit confirmation,
  reviewed controller/Xray/config hashes, healthy native-primary, preserved
  kubelet certificate/containerd database, inverse boot fences and actual live
  desired relay1 assigned to4.
- Existing locked controller demote retains live native forwarding/fence. Enable
  agent boot without starting it; controller failback then stops native, checks
  free ports, releases the marker and starts the preserved worker. It accepts
  real local TLS/WebSocket relay health plus identified Kubernetes relay process.
  Controller failure has native rollback; do not blindly rerun an uncertain phase.
- No etcd/WG/management/DNS/native OTel restart, node deletion, CNI/table flush,
  token rotation, PVC change, broad admission or alert threshold change.
-467c7e95 restores actual Kubernetes Ready/pressure semantics to TV panel926.
  The new independent HOME public-IP probes remain unchanged.

## Accepted runtime

At06:41–06:42UTC:

- All six nodes0/1/2/3/4/5 Ready. New socrat-4 Node registered from preserved
  runtime. Its profile remains transit-worker, with the bootstrap NoSchedule
  admission taint: not a general application/storage worker.
- vpn-transit-655857b776-mvm9q and the reviewed node-exporter DaemonSet are both
  Running1/1 on4, zero restarts in the acceptance sample. No other pods assigned.
- k3s-agent active AND enabled; native user relay inactive; fallback marker absent;
  controller mode=kubernetes, healthy=true, failures0. Inverse boot fences retained.
- Native management relay, private DNS transit, Knot, OTel and independent host
  exporter remain running. Shared relay config SHA unchanged.
- Argo vpn-transit AND monitoring-k3s Synced/Healthy at467c7e95. Provisioned Grafana
  API matches panel926 readiness and panel9 mode queries. Both actual queries
  return0 (green/K3S). Kube Ready1; MemoryPressure/DiskPressure/PIDPressure0.
- Authenticated fixed-HOME tests passed REALITY, Trojan, VLESS32083, VLESS32084,
  userspace WireGuard via literal public Moscow. Each transferred65536B, HTTP200,
  SHA25634dd6758c2908cf5be0e411173f61877f8faf2dcdcfed135b5a5fa90577447bc,
  NL exit109.120.141.60. No overlay transport from HOME to the VPS. No mobile/AWG
  or whole-cluster-loss/reboot acceptance claimed.
- Owned temporary fixture/tokens removed; original tokens and proxy config
  preserved, verified by cleanup receipt. Probe binary/config removed from HOME
  and controller. Temporary sudo file removed; no copy found in operation logs.
-40focused tests passed (with pytest, PyYAML, Jinja2), Ansible syntax and both Helm
  lints passed. PromQL tests evaluate actual restored panel926 including healthy,
  NotReady, memory pressure, missing and stale states.

## Capacity and limits

Immediately after return, MemAvailable~434MiB vs~533MiB in this turn's native-only
preflight. CPU PSI avg60~33%, avg10~46% at one later sample: pressure is NOT solved,
not a controlled load comparison. Existing GOMAXPROCS1 Collector tuning, limits,
reservations, telemetry and warning thresholds remain intact. No further service
removal is represented as a capacity solution. Evaluate more usable CPU/RAM with
the owner; do not remove this worker again to make the dashboard green.

This operation does NOT implement the separate Moscow→HOME ingress failover or
its automatic return. The existing local fallback is retained, not re-proven by
a destructive outage test. Physical TV reload/visual acceptance is separate from
the verified provisioned model; no TV preferences were modified.

## Private evidence

Host4 root-only before/after receipts:
`/var/lib/homelab-recovery/20261113-moscow-return-worker/`.
Owned probe session2:`/var/lib/homelab-vpn-hardening/vpn83-worker-return-20261113`;
HOME receipt0:`/var/lib/homelab-vpn-hardening/vpn83-worker-return-home-20261113`.
Selected controller receipts retained privately in the operator's Application
Support custody; no credentials or unreviewed raw logs are published here.
