# Socrat-3 converted back to a worker — 2026-11-01

## Current topology

- socrat-0: control plane + etcd voter + agent.
- socrat-1: control plane + etcd voter + agent, SSD-backed.
- socrat-2: etcd-only server + agent.
- socrat-3: agent only, Ready worker; local workload volumes retained.

All retain K3s v1.36.5+k3s1. Quorum requires two of 0/1/2. This intentionally
retires the previous external-voter topology: losing both home nodes now loses
quorum, even if socrat-2 and socrat-3 remain online. Socrat-3 is no longer an API
endpoint; the Kubernetes service endpoints were checked to exclude it.

## Executed sequence

1. Checked current member IDs, peer addresses, status and the health of the
   initial quorum. Confirmed socrat-1 had SSD storage and sufficient RAM/disk.
2. Saved `before-socrat3-worker-20261101-socrat-0-1793564114.zip` in the normal
   private K3s snapshot directory on socrat-0.
3. Backed up socrat-1 config/unit privately. Removed only `disable-etcd: true`
   from its config and restarted K3s with KillMode=process, preserving workloads.
   Its previous retired etcd directory was left intact; no active etcd directory
   was present before promotion. K3s joined and promoted the new member.
4. Verified four voters and the healthy, caught-up member identities of 0/1/2.
5. Backed up socrat-3 config, server/agent units and agent drop-ins. Staged worker
   configuration preserving node identity, flannel, kubelet reservations, labels
   and token-file. Removed server-only advertise-address/tls-san, and the obsolete
   bootstrap taint from the staged file (the live admitted node had no taint).
6. Disabled/stopped only socrat-3's server service. The three verified remaining
   nodes sustained the temporary four-member quorum. Rechecked exact membership,
   endpoint identities, health and absence of lag before committing removal of
   member `24459f49c332f4f8`.
7. Verified exactly three healthy voters 0/1/2. Only then activated the worker
   configuration and the existing standard agent unit. Removed server mode by
   moving its marker into the private incident backup. Renamed the retired etcd
   directory without deleting it. Enabled/started k3s-agent.
8. Confirmed the agent active, server inactive/disabled, node Ready and no
   listeners on 2379/2380/6443. Removed obsolete control-plane/etcd role labels
   and labelled the node worker. The etcd metrics DaemonSet may consequently
   remove its obsolete node-local etcd proxy; no monitoring configuration was
   changed. Other workload pods and their data were not drained or migrated.
9. Verified quorum health, public Wiki HTTP 200 and its unchanged socrat-0
   placement. Saved `socrat3-worker-verified-20261101-socrat-0-1793564552.zip`.

No K3s uninstall, cluster reset, etcd tuning, database deletion, reboot, desktop
cleanup or OTel configuration change was used in this conversion.

## Backups and guards

Private incident directories on modified hosts:
`/var/lib/homelab-k3s-worker-20261101` (root-only).

Retired socrat-3 database:
`/var/lib/rancher/k3s/server/db/etcd-retired-worker-20261101`.
It contains removed-member state and is not an automatic rollback source.
Do not enable the server using this data or restore a snapshot into a live
cluster as a routine rollback.

- `/etc/rancher/k3s/worker-mode` guards socrat-3 against server startup through
  `/etc/systemd/system/k3s.service.d/90-worker-mode.conf`.
- k3s-agent is enabled; k3s is disabled.
- Boot-service inventory now explicitly selects k3s-agent for socrat-3.
- `worker-topology` and updated `complete` markers under
  `/var/lib/homelab-k3s-rebalance` record the current topology on 0/1/3. Previous
  completion records were preserved in the incident directories.
- The historical `k3s-role-rebalance.yml` now refuses the worker-topology marker
  before attempting its superseded server promotion/removal workflow.

`ansible/playbooks/k3s-worker-topology-verify.yml` installs verification helpers
and performs read-only role, readiness, identity and quorum checks. It does not
reconfigure roles or membership. The new verifier was also executed live on 0.
The new source changes still need review/commit/push; they were not pushed as
part of the live role conversion.

## Initial before/after samples

These are short observational samples, not a controlled benchmark. Before was
after a recent reboot, and startup/cache effects can affect comparisons.

| Measurement | Before | After agent startup |
| --- | --- | --- |
| Server/agent RSS | approximately 1,200,000 KiB | approximately 222,000 KiB |
| Host available RAM | approximately 1.2 GiB | approximately 2.0 GiB |
| CPU iowait | 52–60% | 39–43% |
| Disk write await | 23–38 ms | 12–15 ms |

The gain in memory is substantial, but HDD saturation remains (approximately
88–91% utilization in the later sample). OTel, persistent queues and other
workloads were deliberately untouched. No claim of an 80% load reduction is
supported by these samples. Further changes require a separate decision.
