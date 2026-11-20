# socrat-5: containerd moved to HDD — 20 November 2026

## Current followup status

The retained SSD preimage has since been removed after acceptance; dynamic tiers,
monitoring and archive handoff are complete. The following original snapshot is
historical. Current state: [followup closeout](storage-followup-20261120.md).

## Accepted scope

**Runtime relocation completed.** This receipt does not claim all application
PVCs were moved, dynamic storage tiers deployed, or every external integration
healthy. Owner authorized brief downtime and SSH-only work without requiring
Proxmox access; physical backing capacity remains unverified.

- Runtime source coordinates preserved: `/var/lib/rancher/k3s/agent/containerd`.
- Authoritative runtime now on `/mnt/files/homelab/runtime/containerd` via bind
  mount, source `/dev/sdb1[/homelab/runtime/containerd]`, ext4.
- OS and `/var/lib/rancher/k3s/server` remain on `/dev/sda1` SSD.
- Existing application PV/PVC paths/data were not relocated or restored.
- Node UID/SSH/WireGuard identities retained; node Ready and schedulable.

## Procedure and verification

1. Live rsync pre-copy to a fresh dedicated HDD directory, while K3s ran. This
   was only a downtime optimization, not a consistent backup.
2. Owner-authorized reboot of node5; SSH and WireGuard services verified enabled.
3. Boot-time one-shot required a changed boot ID, no K3s/containerd/shims and no
   source subtree mounts before operating. Original SSD runtime stayed intact.
4. Cold full-checksum rsync with numeric IDs, hardlinks, ACLs, xattrs, sparse files
   and stale-file removal confined to the new staging destination completed
   successfully. Rsync verifies transferred files; unchanged files were compared
   by full checksums. A subsequent metadata/size tree dry-run was empty.
5. Avoided a redundant second full content read after the checksum-sync success
   checkpoint. The initial read-only redundant verification was stopped; resumed
   from `cold-verify` with metadata-tree verification only. No copy step skipped.
6. Original SSD directory renamed to the exact retained preimage below; new HDD
   bind installed and persisted in fstab, with mount-identity startup guard.
7. K3s started on HDD; node returned Ready and was uncordoned. CRI imagefsinfo
   reports the runtime snapshot filesystem; findmnt and device/inode guard prove
   the runtime directory is on HDD. No live image override or blanket Argo prune.

Private root receipt: `/var/lib/homelab-recovery/runtime-hdd-boot-20261120`.
The initial runtime switch was around 18:49 MSK; the cold checksum pass took
about 11 minutes, plus boot, final tree traversal and application cold starts.
Downtime was longer than originally hoped; do not describe it as instantaneous.

## Persistent configuration / day-2 owner

- `/etc/fstab`: bind from HDD to original runtime directory.
- `/usr/local/libexec/socrat5-containerd-hdd-check`: checks HDD device, exact
  bind source and matching device/inode of source and target; fails closed.
- `/etc/systemd/system/k3s.service.d/60-containerd-hdd.conf`: requires both HDD
  and runtime mount; guard before start. Actual unit is k3s, not retired agent.
- Day-2 owner: `ansible/playbooks/socrat-5-runtime-storage.yml`; refuses an
  unmigrated node, persists accepted bind/guard only, reloads systemd without
  restarting services. It is NOT a data migration/bootstrap playbook.
- `scripts/socrat5-runtime-boot-migrate.py` is a one-node historical cutover tool,
  with protected state, new-boot and source identity gates. Never replay `prepare`
  against an existing destination or label its live pre-copy a backup.

## Post-reboot transport correction

Node3 retained node5's old NAT endpoint `94.29.124.139:53673`; current authenticated
WireGuard handshake observed at node4 showed `94.29.124.139:56885`. Updated ONLY
existing node3 peer5 runtime endpoint. Handshake age became1s; no keys, AllowedIPs,
routes, VPN subscriptions, persistent network config or service restart changed.

Before correction, direct DNS to CoreDNS on node0 worked but CoreDNS on node3
failed, intermittently blackholing service DNS. N8n init failed its subscription
fetch. After correction the still-uninitialized n8n Pod was normally deleted
(no force, no PVC deletion) to clear restart backoff. Replacement reached2/2 Ready,
zero restarts. No workflows were replayed or executed as tests.

## SSD retained preimage / capacity

`/var/lib/rancher/k3s/agent/containerd.ssd-retained-boot-20261120` is about55GiB.
It is a **stale, fixed-size runtime preimage**, not a current application backup.
It remains on SSD and was NOT automatically removed. SSD currently about24GiB
available (74% occupied); HDD about60GiB used /1.9TiB available. Runtime growth now
goes to HDD; retaining the SSD preimage does not mean runtime is still on SSD.
Deleting this exact preimage after acceptance would reclaim about55GiB. Do not
blindly restore it after new writes; prefer a cold reverse handoff if needed.

## Acceptance limits

Grafana/Grafana MCP, n8n, Rancher native Pods and OpenHands recovered. At the last
snapshot39 Pods were Ready. DeeperSeeker retains the previously observed external
401 authorization failure; credentials were not changed or bypassed. SearXNG and
a concurrent Umami rollout were still progressing at that snapshot. Rancher
aggregate Argo health intermittently reports Degraded despite Ready backend and
proxy; do not substitute readiness for full SSO/whole-cluster acceptance.

Dynamic HDD/SSD StorageClasses and application-tier migrations remain separate
work. The earlier static-tier draft is not the final automatic HDD-first policy.


## Final accepted runtime snapshot

- Kubelet summary: nodeFs capacity99,677,949,952 bytes (SSD); imageFs
  capacity2,163,348,520,960 bytes (HDD), available~2.078TB. This independently
  confirms kubelet/runtime capacity accounting follows the new HDD filesystem.
- 40 node5 Pods Ready; only DeeperSeeker remains unready with the already observed
  external401. SearXNG and Umami subsequently reached Synced/Healthy.
- Grafana, Grafana MCP, n8n, OpenHands Synced/Healthy; n8n2/2 with0 restarts.
  Rancher native backend/proxy remain Ready; aggregate Argo Degraded remains open.
- Original21 node5 application PVC identities match the pre-migration inventory.
- Day-2 Ansible applied successfully; repeat run ok5 changed0 failed0, no restart.
- SSD preimage retained, not deleted; runtime growth/updates now occur on HDD.
