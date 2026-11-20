# Socrat storage: HDD-first operational contract

## Policy

On socrat-5, containerd already runs on HDD. New ordinary local application data
uses HDD; SSD is explicit opt-in for a measured latency requirement. Existing
bound PVCs do not move when a StorageClass or provisioner configuration changes.
The cluster-wide default is **nfs-shared**, not a disk attached to one node.

| Class | New data on socrat-5 | Other nodes | Reclaim / binding |
|---|---|---|---|
| local-hdd | /mnt/files/homelab/volumes | Refused | Retain / WaitForFirstConsumer |
| local-ssd | /var/lib/rancher/k3s/fast-storage | Refused | Retain / WaitForFirstConsumer |
| local-path (legacy) | HDD, same parent as local-hdd | Original /var/lib/rancher/k3s/storage | Existing Delete / WaitForFirstConsumer |
| specialized legacy classes | Original mapping, including pg-local-retain | Original mapping | Existing policies unchanged |
| nfs-shared | Existing NFS server | Existing NFS server | Existing Retain / Immediate |

Use `storageClassName: local-hdd` for new ordinary local workloads, `local-ssd`
only with a documented reason. Both new classes constrain topology to socrat-5
and use local PVs with hostname affinity. Existing node5 local-path templates
also become HDD-first for newly provisioned claims without rewriting bound ones.

## Owners and transition

Argo Application **storage-tiers**, `deploy/storage/tiers`, owns the EXISTING
local-path provisioner, its existing ServiceAccount/RBAC, config and local-path
class plus two new tier classes. No second provisioner, broad RBAC grant or
unsafe helper-template option is added. Live image/placement/RBAC are preserved.

Ansible `k3s_storage_owner` creates `local-storage.yaml.skip` on nodes so K3s's
packaged manifest cannot revert the Git source on restart. It does NOT use
`--disable=local-storage`, uninstall an Addon or delete resources. Baseline site
and HA preparation include this guard for future nodes/promotions. The old
workload-offload role no longer patches Git-owned provisioner placement.

Transition is two-phase: publish Application with auto-sync disabled; capture
UID/config receipts; install .skip and verified roots; then enable scoped Argo
reconciliation. Keep existing claim/PV/SA UIDs. Rollback is coordinated owner
handoff, not deleting the Application with prune or removing storage resources.
NFS installer verifies the Git-owned non-default local-path instead of silently
patching it. NFS class remains owned by its existing Helm installation.

## Fail-closed disk selection

Helpers mount the volume parent using the provisioner's standard hostPath bind.
The setup AND teardown scripts validate its actual `st_dev` AND the preinstalled
filesystem UUID sentinel before any mkdir/rm for either new tier. socrat-5 root
is device2049/UUID60fd0998-0598-4672-88b5-3bec59f697c9; HDD is device2065/
UUID3ec3263e-32e3-4b38-84e6-17cd168244b9. A missing HDD falls back to root2049,
so a copied sentinel alone cannot pass. Device renumbering fails closed and
requires re-audit, not blind edits. No hostPID/privileged helper is required.

This guards **provisioning**. Existing HDD writers still depend on the host mount
and their service/application dependencies. Runtime has a separate persistent
bind-source/device-inode guard before K3s startup.

## Capacity, retention and backups

These are directory volumes. **PVC requests are not enforced quotas**; a requested
1Gi directory may grow beyond1Gi. Retain prevents automatic data deletion, not
node/disk loss. Local data does not fail over merely by moving a Pod.

SSD exception budget: plan no more than40GiB of new application data, preserve
at least20GiB/20% root headroom, and review measured growth before admission.
This is an operational budget, not an enforced limit. HDD also needs growth and
inode monitoring. Guest2TiB is not proof of physical hypervisor capacity.

Prefer SSD for measured database/index/queue latency needs. Prefer HDD for
uploads, attachments, artifacts, archives, ordinary agent workspaces and logs
that must persist. Split database/blob claims only where the app supports it.
Caches, emptyDir and logs need bounded lifecycle/rotation independently of PVCs.
Backups must be independent; a second directory on the same disk is not DR.

## Monitoring and checks

Dashboard `socrat-storage` shows capacity, available bytes, inode availability,
space-growth rate and forecast separately per node/mount. Bind mounts must not
be summed. Traffic Light root indicator remains independent and is named
`Disk / (system)`. Missing telemetry stays unknown, never zero/healthy.

Three Git-owned alerts cover absent/changed expected HDD identity, <15% available
and <10% free inode. Existing predictive/critical node-exporter rules remain.
New alerts are integrated into the append-only graph-ID ledger and SPI links.

Acceptance requires positive HDD and SSD PVC provisioning/write/read/recreation,
Retain behavior, legacy class compatibility and a negative helper test on root
with a copied HDD UUID marker. Never unmount the production HDD for a test.

Native DeepSeek account reauthorization and physical Proxmox capacity evidence
are separate owner/external prerequisites; do not bypass authorization or claim
them green from storage checks. Historical runtime handoff:
[socrat5-runtime-hdd-complete-20261120.md](socrat5-runtime-hdd-complete-20261120.md).


## Existing SSD exceptions and archive move

Keep the small active agent SQLite/work-state claims (OpenHands, SWE Mini,
mutation intake), browser profile state and node identity on SSD for active
state/interactive responsiveness; critical PostgreSQL placement remains owned by
its explicit database policy. These are bounded exceptions, not a policy that
all future databases or workspaces need SSD. Reassess actual growth against the
40GiB budget; quota enforcement is not claimed.

The existing OpenHands cold/upgrade archive claims are capacity data, not fast
state. They are handed off to `/mnt/files/homelab/openhands-archives/...` with
binds at original PV paths, preserving claim identity. No backup Job is run or
replayed. Day-2 playbook refuses absent/unaccepted archive mounts and requires
them before K3s can start. See the followup receipt for actual acceptance.
