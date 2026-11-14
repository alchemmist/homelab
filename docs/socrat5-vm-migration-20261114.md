# socrat-5 migration checkpoint — 14 November 2026

## Current operator decision

Migration is paused until access returns. The RuDesktop relay explicitly
reported its free two-hour daily limit; do not bypass it or claim successful
transfer/startup without verification. Owner requested restoring available
services on other nodes until the next evening.

- CT104 stopped cleanly, onboot0; retained with its original disks.
- Node socrat-5 UID bb08e55e-04aa-4049-8348-6572b80b771e retained and cordoned.
- VM105 was running with K3s/WG masked/inactive and no authorization marker.
  A 293314282-byte final payload transfer was started, but completion is unknown.
  No permission marker, identity startup or image import was performed.
- PR Agent restored on socrat-1 (not memory-constrained socrat-3), replicas1;
  Argo Synced/Healthy, Pod Ready, public root GET HTTP200. Commit54b2912e.
- n8n remains replicas0, selector5, original PVC/PV and Secret unchanged.
  Do not start it with empty data or silently roll it back to an old backup.
- Other five nodes Ready; only worker5 NetBird/node-exporter degradation expected.
  Never transplant machine-socrat-5 identity into another existing worker.

## Verified cold backup

Proxmox directory (private, root0700):
`/mnt/pve/files/homelab-ct104-vm105-cutover-20261114`.

Archive `vzdump-lxc-104-2026_11_14-15_30_17.tar.zst`:3917013871bytes,
SHA256 `d53f8db1d6e16ee18a40ec591f7441f1c7638636e8ba9bd41fdc0463f0b3edb5`.
Includes rootfs and mp0. zstd integrity passed; CT stayed stopped. Full restore
is not demonstrated. First two attempts failed before creating an archive due
to mapped-root traversal/umask; logs retained. Dedicated UID100000 private tmpdir
and standard child umask resolved it; backup directory remained root0700.

Filtered final package `final-settings-state.tar.gz`:293314282bytes,1414entries,
SHA256 `d402abdd7e7d7d2b02c58a934852b5ef5852a3209bd13d6a0cff6c0404290bad`.
Includes settings/reference etc, user homes, usr/local, K3s agent identity without
containerd runtime, both local PV datasets and native telemetry state/queue.
Not a license to restore all etc onto the VM. Preserve VM network/fstab/fences.
Cold n8n DB SHA256 `9484ff474761182ba3cdf9fcf76c0cc328102d7852f0c519dbf602d26e3e3e9e`,
UID/GID1000:1000, integrity_check ok,7workflows/10credentials/1user,0active.
Successes9777; historical canceled181/crashed150/error25, not newly induced.

## Temporary service restoration gate

Latest accessible verified n8n backup on socrat-3:
`~/backups/n8n/n8n-20261114T001512Z-3ca3196d25f4.tar.gz`.
It predates shutdown by about12h. Owner must accept missing intervening changes
and history and potential duplicate processing before restoring it elsewhere.
Retain original n8n-socrat5 and NetBird PVCs; create an independently named
recovery dataset if approved. Any later return needs an explicit data-authority
decision and consistent reverse synchronization after writes; never blind rollback.

## Administrative access and Git

Kubernetes API was verified through localhost-only SSH forwarding
127.0.0.1:16443→socrat-0 publicSSH→192.168.0.23:6443. Existing Socrat credentials
and TLS verification with tls-server-name192.168.0.23 retained; kubeconfig,VPN,
DNS,routes and SSH aliases unchanged. Socket `/tmp/homelab-kube-api-0z5f22ys/control`;
check it before use and close the owned tunnel when no longer needed.
Private preimages/Secrets/receipts are outside Git under
`~/Library/Application Support/homelab/socrat5-vm-cutover-1xqpv5ft`.
Local main and remote main diverged with concurrent work. Minimal commit-tree
commits atop the fresh remote head were pushed fast-forward; local branch/files
were not reset/rebased/checked out or pushed wholesale. Preserve both histories.

## Resume gates

Confirm actual CT/VM states and transfer checksums first. CT must remain fenced
before any VM identity activation. Keep no-NFS protections until real NFS Pod and
NetworkPolicy tests. Preserve SSH/user credentials, K3s node/password/token,WG,
NetBird state, encryption keys, native SSO/TLS, queues/fsync and existing PVC IDs.
Verify guest AND physical Proxmox backing capacity before and after copies.
CT deletion remains a separate final approval after backup and VM acceptance.
