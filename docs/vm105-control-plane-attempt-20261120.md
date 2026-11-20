# VM105 control-plane-only trial, 2026-11-20 (rolled back)

First attempt: VM105 was restored to worker. See accepted retry below. Do not use the historical quorum rebalance
playbook to retry. No WAN ingress, fourth voter or new public address is needed.

- Snapshot on socrat-0: `vm105-before-control-plane-socrat-0-1795177133.zip`
  (ZIP integrity checked, not a restore test). Original config and trial units
  on VM105: `/var/lib/homelab-vm105-control-plane/` (root only). Server material
  remains in `/var/lib/rancher/k3s/server` and must not be copied to diagnostics.
- From VM105 all three advertised etcd client addresses route via `wg-socrat`.
  Five read-only HTTP/2 gRPC Maintenance/Status calls per address using the local
  etcd client identity returned grpc-status 0 after rollback; this does not
  exercise informer list/watch load. Plain HTTP /health returned 415.
- VM105 K3s journal (MSK): 15:20:14 connected to datastore, 15:20:22 health
  check failed for socrat-1 and the local LB closed 23 connections; 15:21:04
  failed for socrat-2 and closed 66. Informers were not ready before rollback.
- At 12:21:15 UTC, Thanos 2-minute histogram p99 WAL fsync / backend commit
  (seconds): 0=.114/.149; 1=.0034/.0038; 2=.467/1.229. No leader change in
  the 3-minute window. On 2, slow apply reached 11.86s. This identifies a
  performance problem, not proof that it caused both health-check failures.
- Before a retry, examine node 2 disk contention, establish baseline etcd read
  and fsync latency, exercise a bounded sustained read/watch path from VM105,
  and correlate LB health-check timings. Preserve the migration fence, mount
  guards, worker config/UID, snapshot and rollback deadline. Check API health
  independently via 0 and 1. Do not start destructive load tests on etcd.

## Accepted retry, 13:31 UTC

VM105 now runs `k3s.service` (enabled) with `disable-etcd: true`, node and
advertise address 10.250.0.41, preserving its worker kubelet config, service
drop-ins, mounts and Node UID. Agent service disabled; rollback timer stopped.
No public networking changes. Before the retry, all three voters were healthy
and the last 5-minute p99 fsync on voter 2 had fallen to 30 ms. Direct readyz
passed via .1, .3 and .41; all six nodes Ready. Actual etcd member inspection
after promotion: same three healthy voters, no learner. Rancher and Argo
application-controller Ready. DeeperSeeker was already partially unready before
this retry. No physical node-loss/reboot test performed. Do not apply the old
worker/rebalance provisioning to VM105. Check: `scripts/socrat5-control-plane-check.sh after`.
