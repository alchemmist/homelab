# socrat-5 HDD-first: preflight and maintenance runbook

## Completion update

Containerd relocation subsequently completed through an approved reboot and
boot-time cold handoff. See [completion receipt](socrat5-runtime-hdd-complete-20261120.md).
The failed process-freeze attempt below is historical, not the final outcome.

## Scope/status

**Attempted, not migrated.** Owner authorized an SSH maintenance attempt.
Container quiescence did not complete; runtime stayed on SSD. Node was cordoned
and later uncordoned; application restarts occurred. See the
[attempt receipt](socrat5-hdd-first-attempt-20261120.md). Do not replay the failed
process-freeze technique. No runtime copy or data relocation occurred.

Machine-readable contract: `deploy/storage/plans/socrat5-hdd-first.json`.
Offline check: `python3 scripts/check_storage_migration_plan.py`.
The pre-existing static class manifests are not the final dynamic HDD-first design;
do not publish them as if they provided automatic directory provisioning.

## Read-only preflight receipt — 20 November 2026

- Node Ready, K3s v1.36.5+k3s1, containerd 2.3.4. socrat-5 is an API server,
  not an etcd voter. Voters are socrat-0/1/2. Labels alone do not prove quorum.
- Kubernetes service advertises surviving API addresses 10.250.0.1 and
  10.250.0.3, as well as 10.250.0.41 and 192.168.0.23. Verify independent
  `/readyz` with normal authorized TLS before maintenance; endpoint presence
  alone is not readiness or proof every client can fail over.
- Runtime root: `/var/lib/rancher/k3s/agent/containerd`; transient state:
  `/run/k3s/containerd`. Containerd generated config version 3.
- 47 CRI images; reported sum ~15.3 GB includes shared layers and is NOT unique
  reclaimable bytes. Digest-only images are not evidence of garbage.
- CRI image filesystem reports ~43.65 GB snapshot use. Directory allocation:
  ~58 GiB total runtime, ~41 GiB overlayfs, ~13 GiB content, ~4.6 GiB CRI.
- Live kubelet configz: image GC high 85%, low 80%; minimum age 2m; maximum age
  disabled (0s). Hard eviction: imagefs available 15%, nodefs available 10%,
  nodefs inode free 5%, memory available 200Mi. Logs rotate at 10Mi x5.
  Root currently ~79% occupied, below the configured image GC trigger.
- Guest available root ~20.6 GB; HDD ~2.134 TB. Guest capacity is not host capacity.
- No current Proxmox endpoint/SSH alias/authorized connection was found in the
  project or configured SSH aliases. Historical 4.8 TiB physical free is stale.
  Physical backing capacity remains unverified. Owner authorized proceeding
  without hypervisor access; guest df is not proof of physical free capacity.
- Singleton workloads include Grafana/MCP, n8n, Argo application-controller,
  Rancher and application state. LMS PDBs currently allow zero disruptions;
  do not force drain or use deletion/eviction overrides.
- Existing service RequiresMountsFor covers /mnt/files and n8n bind mount.

## Final intended storage policy

HDD is normal for socrat-5 runtime and application data; SSD is opt-in for
measured latency-sensitive datasets. Keep OS, K3s server identity/state and small
system files on SSD. Do not move the entire K3s data-dir merely to move containerd.
The source runtime path remains unchanged via a persistent bind mount; kubelet,
containerd metadata and existing PV paths keep their original coordinates.

Dynamic tiers should reuse the K3s-owned local-path provisioner, not install an
unreviewed parallel provisioner or adopt its objects into another owner. Prepare
an owner-compatible configuration with `storageClassConfigs` preserving EVERY
legacy local-path-derived class (local-path, lms-db-retain, rustfs-retain,
socrat-bot-retain, venice-browser-retain), plus exact node5 mappings for local-hdd
and local-ssd. Unknown nodes must be refused for the new tiers. Use
WaitForFirstConsumer, local PV node affinity and Retain. A missing per-class map
must never break provisioning/teardown of legacy classes.

Before production dynamic use, establish a tested fail-closed check of actual HDD
mount identity in the helper's host mount namespace. Merely mkdir-ing a path,
checking filesystem type, or testing mountpoint in a helper's unrelated namespace
is insufficient. Validate with a disposable claim after approval; never test by
unmounting production HDD. If this gate cannot be implemented safely, retain
static provisioning temporarily and state that limitation explicitly.

Do not make a single-node HDD the implicit cluster-wide default. The intended
cluster default remains nfs-shared through its existing owner; socrat-5 application
values must explicitly use local-hdd. SSD use requires an app-specific reason.
No directory quotas are implied by requested PVC capacity.

## Required operator inputs before the window

1. Authorized current Proxmox endpoint/access, or operator output of VM105 disk
   mapping (`qm config 105`, redacting unrelated secrets), `pvesm status` and
   backing filesystem/thin-pool data + metadata capacity. Check qcow2 snapshots
   and competing consumers. Physical capacity must cover copy and rollback margin.
2. Explicit maintenance start and accepted singleton application downtime.
3. Active job/queue/writer freeze plan, including autonomous agent jobs and n8n
   callbacks. No workflow execution/replay or paid inference for tests.

## Ordered maintenance procedure (not an executable unattended script)

1. Capture private 0700/0600 receipts: exact node UID, Ready Pods/controllers,
   PVC/PV UIDs, mounts, fstab/drop-ins, runtime config and capacity. Verify hashes
   where meaningful. Do not collect or print dataset contents or secrets.
2. Confirm surviving API readiness and all three voters' native health via
   existing authorized read-only route. Determine operator access independent
   of node5/Grafana/Argo controller. Stop if quorum/transport is uncertain.
3. Confirm HDD source identity /dev/sdb1 ext4 and physical PVE space. Budget at
   least current runtime allocation + 20 GiB headroom, including inode demand.
4. Agree writer quiescence. Cordon node5 to prevent new scheduling, but do not
   force drain through PDBs or reschedule local-PVC singletons elsewhere. Suspend
   only explicitly reviewed jobs/controllers with preserved source intent.
5. Stop K3s only in the approved window. **Stopping k3s alone may leave containerd
   shims/containers running.** Inventory and stop the exact node5 runtime tasks
   using a reviewed native method. Do not run k3s-killall blindly: it affects
   mounts/networking. Prove no containerd/shims or snapshot mounts can write to
   source; if not proven, abort the copy and restore service.
6. Cold-copy the runtime tree preserving numeric UID/GID, hardlinks, ACLs,
   xattrs and sparse files (rsync -aHAXS --numeric-ids on verified local paths).
   Use a newly created dedicated destination; no --delete against existing data.
   Check rsync exit status and a cold checksum/dry-run comparison. Do not use a
   live runtime copy as recovery evidence.
7. Preserve original SSD tree as a named rollback preimage on the same filesystem.
   Bind HDD destination at the original runtime path. Persist the bind in fstab,
   require /mnt/files, and add actual `k3s.service` fail-closed dependency checks
   for both HDD and runtime bind identity. Do not modify retired agent-only units.
8. Verify mount source and config, start K3s, verify node Ready, CRI imagefs on
   HDD, containers and PVC identity/readiness, surviving control plane health,
   Grafana/MCP/metrics and application read-only health. No transaction replay,
   publication, login bypass or inference acceptance by proxy.
9. Restore only maintenance-paused controllers, uncordon after acceptance, and
   record errors/restarts/downtime. Inspect workload behavior and actual HDD I/O.
10. **Do not automatically delete the SSD preimage.** Root free space will not
    improve until it is removed. After owner accepts runtime and rollback safety,
    explicitly authorize removal of that exact preimage (not active mount).
    Only then claim SSD capacity reclaimed.

## Rollback boundaries

- Before new runtime writes: stop/prove quiescence, remove only the new bind and
  its owned fstab/drop-in changes, restore original runtime directory, verify
  source identity and restart K3s. Never remove HDD application datasets.
- After runtime has run on HDD: SSD preimage is stale runtime state. Do not
  blindly start it; runtime metadata and pod/task state may have diverged.
  Prefer a cold reverse copy of current authoritative runtime to verified SSD
  capacity, with HDD copy retained. Reconcile task state without running two
  runtimes. Application databases/PVCs must not be rolled back to stale copies.
- Do not prune images, remove leases or manually delete snapshots as a shortcut.

## Acceptance checklist

- Actual backing storage verified, not just VM virtual disk capacity.
- Runtime bind resolves to HDD; K3s server state stays on SSD.
- No original PVC paths/identities or SSO/credential identities changed.
- CRI filesystem accounting reflects HDD; monitor post-change nodefs/imagefs.
- No cold-boot guarantee claimed until separate reboot acceptance.
- Source kept/released decision and actual df before/after documented.
- Dynamic tiers tested and owner-integrated before promising HDD auto-provisioning.
