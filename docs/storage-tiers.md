# Storage tiers and operational contract

## HDD-first continuation

The owner selected HDD as the normal runtime/data tier. The static classes below
are an initial source-only draft, not the final dynamic solution. Current
preflight, blockers, maintenance steps and rollback boundaries are in
[HDD-first maintenance](socrat5-hdd-first-maintenance.md). Runtime has now moved to HDD; see [completion receipt](socrat5-runtime-hdd-complete-20261120.md). Application PVC tiers remain unchanged.

## Status and ownership

This change implements explicit **static** local classes and monitoring source.
No existing PV/PVC is reclassified, moved, resized or deleted. No new provisioner
is installed. Git source is not runtime acceptance: verify Argo after publication.
Inventory: [read-only receipt](storage-inventory-socrat5.md).

- `storage-tiers` Application owns only new classes in `deploy/storage/tiers`.
- `monitoring-k3s` owns filesystem dashboard and storage rules.
- K3s still owns existing local-path provisioner/configuration and local-path SC.
- Existing Ansible NFS owner retains responsibility for nfs-shared/default policy.
  Both existing defaults are a known runtime conflict; do not silently co-own them.
- Host mounts remain Ansible-owned. socrat-5 host vars already require /mnt/files
  and the n8n bind mount. Runtime `systemctl show k3s.service` confirms
  `RequiresMountsFor=/mnt/files /var/lib/rancher/k3s/storage/n8n-socrat5`.
  This is dependency evidence, not a tested cold-boot/DR acceptance;
  filesystem metrics are not a startup barrier.

## Selected first-stage design

| Class | Backend | Provisioning | Default | Reclaim | Capacity enforcement |
|---|---|---|---|---|---|
| local-ssd | Verified SSD path on an explicitly named node | Static PV | No | Retain | None for directory PVs |
| local-hdd | Verified mounted HDD path on an explicitly named node | Static PV | No | Retain | None for directory PVs |
| nfs-shared (existing) | Existing NFS server | Existing dynamic provisioner | Intended sole default; drift unresolved | Retain | Not established by this change |

Static classes are deliberate: a new PVC remains Pending until an operator
prepares a matching PV. They do NOT automatically create directories or select
a disk. Every new local PV must have `local.path`, exact hostname node affinity,
matching storageClassName, Retain, and a path whose actual mount identity has been
verified. Use a dedicated application directory, not the disk root. Pin the claim
with `volumeName` when selecting a particular static PV. Never mutate the class
of an existing bound claim as a substitute for a migration.

No SSD/HDD label is inferred for other nodes. Classifying them requires their
own physical-media, mount and capacity audit. Dynamic provisioning is deferred:
local-path v0.0.37 supports per-class configuration but ignores requested capacity.
Changing its shared K3s-owned configuration would affect existing legacy classes.
Do not install a second provisioner just to avoid an ownership review.

## Dataset classification (intent, not relocation)

| Dataset | Recommended tier | Reason / acceptance needed |
|---|---|---|
| OS, K3s/containerd, management state | SSD / system budget | Required system headroom; inspect runtime disk use first |
| Small latency-sensitive SQLite/Postgres state, agent queue/state, browser profiles | SSD candidate | Confirm I/O sensitivity and measured size; not all databases need SSD |
| Wiki content, uploads, WebUI/Terminal user files, attachments | HDD candidate | Capacity-oriented; separate embedded databases where supported |
| Monori sync-debug, format-quorum artifacts, branding files | HDD | No demonstrated requirement for low random-I/O latency |
| Grafana database and n8n database | Review, currently HDD | Existing operation is not proof of optimal tier; move only after measured need |
| OpenHands backup/archive claims | HDD candidate + independent off-node copy | Current local backups share SSD failure domain; no move/backup performed |
| Shared application files requiring multi-node access | NFS candidate | Application compatibility, network performance and server availability required |
| Caches, build workspaces, emptyDir, logs | Explicit bounded ephemeral budget | Do not consume root unboundedly; move only if lifecycle permits |

An application may need multiple tiers. Database and blobs should be separate
claims only where the application supports separate paths. No fabricated universal
SSD benefit or database-on-NFS compatibility guarantee.

## Capacity and safety gates

- Current system SSD is shared with root. Do not advertise 100 GiB to apps.
- Privileged inspection attributes about 58 GiB to containerd and 5.4 GiB to
  local PVC directories. Admit **no additional SSD allocation** until runtime
  growth/image-GC and upgrade headroom are assessed. A numeric application
  budget cannot be based on PVC requests alone. Initial operational target: keep at least 20 GiB and
  20% available on root; this is a guardrail, not an enforced quota.
- PVC requests do not enforce directory quotas. Retain prevents deletion by
  reclaim policy; it is not a backup. Local volumes cannot fail over to another
  node merely by rescheduling a Pod.
- For new HDD writers, verify mount identity and boot dependencies before launch.
  A directory existing at /mnt/files is not proof that HDD is mounted.
- Monitor bytes, inode availability and forecasts separately per filesystem.
  Do not sum bind mounts or combine root and HDD into one healthy percentage.

## Inspection and verification

`python3 scripts/audit_storage.py --node socrat-5` emits bounded inventory JSON
without reading file contents or using sudo. It joins PVC consumers, node affinity,
mount identity, statvfs and du completeness. Store operational output privately.
An inaccessible directory remains unknown; prefix-based mount resolution is
clearly distinguished from successful canonical lookup.

Owner-authorized privileged disk inspection is now recorded in the inventory.
Containerd is the dominant SSD consumer (~58 GiB); existing PVC directories are
~5.4 GiB. No cleanup occurred. Further runtime GC policy and active-image/snapshot
inspection is required before authorizing deletion or assigning an SSD app budget.
Repeated du totals must not be summed across kubelet bind mounts.

Dashboard UID `socrat-storage` shows each filesystem, including bind-mount labels;
it is not a deduplicated capacity total. Traffic Light retains its root-only safety
indicator, renamed to make that scope visible. New alerts cover required HDD
identity missing for 5m (+2m pending), <15% available and <10% free inodes.
Existing node-exporter predictive/critical rules remain owned and unchanged.
Check missing exporter vs missing mount before reacting. No destructive remediation.

Publish via normal Git workflow; verify only `storage-tiers` and `monitoring-k3s`
reconciliation, two classes, dashboard served by Grafana, and rules loaded by
Prometheus. Do not blanket sync/prune. No production workflow, paid inference,
backup run, service restart or application data migration is part of this change.
