# socrat-5 migration checkpoint — 14 November 2026

## CURRENT: owner-approved n8n recovery on socrat-1

Owner explicitly accepted the ~12-hour rollback from14Nov00:15UTC. The restored
DB has accepted new writes and is NOW AUTHORITATIVE. Tomorrow: quiesce the sole
writer and consistently migrate fresh state from1 before moving n8n again. Do
not blindly revert claim/node, merge SQLite files or start an old writer. Retain
source datasets for potential reviewed recovery of missing history; no automatic
history merge was attempted.

### Recovery evidence

- Source archive n8n-20261114T001512Z-3ca3196d25f4.tar.gz, SHA256
  e81bca4fc10bf0b101ee158b3c77c1a32143228b2dd64949f9121441da200d7b.
  Source DB SHA256 ec104daf309e5b93be3d3c6749ee17f41e87faf77ef5c998a84034ccad1dd12c.
- Archive/manifest/DB hashes and integrity_check verified twice. Recovery key
  bytes matched existing Secret; Secret UID/data unchanged. No SQL writes/reset.
- Separate PV/PVC n8n-recovery-20261114, Retain, fixed node1 affinity.
  PV UID d52afbfa-a6e5-4375-a75b-f28900fb8308;
  PVC UID91965136-60b4-4d9b-945d-9d7625235fe8.
- Path /home/alchemmist/.local/share/homelab/n8n-recovery-20261114/data,
  owner1000:1000, directory0700, config/DB0600. Source archive and receipt retained
  privately in parent. Node1 persistent root had~198GiB free after restore.
- Original n8n-socrat5 PV/PVC UIDs unchanged; legacy and NetBird datasets retained.
- Deployment: replicas1/Recreate, selector1, recovery claim.7workflows,
  10credentials,1user,6active workflows activated. Ready1/restarts0,
  Argo Synced/Healthy; public healthzHTTP200/ok, rootHTTP200, unauthenticated
  APIHTTP401. No manual production workflow or credential operation invoked;
  browser login/every credential remain untested.
- PR Agent Ready1 on1 too. Node1 memory~69% at latest sample; no added workload
  on memory-constrained3. No peak-load/long-duration claim. googleDnsEnabled:false
  retained; no unrelated DNS, admission, mesh or global firewall changes.

### Backup acceptance after restore

CronJob now follows current nodeName/claimName; sourceNode is Pod downward API,
not hardcoded5. Schedule03:15Europe/Moscow, Forbid, pinned image, bounded-memory
SQLite online snapshot/hash, readonly data, same restricted SSH receiver/pin/key,
all versions retained. No backup permission expansion or pruning.

Exact-CronJob job n8n-recovery-check-20261114-130649 succeeded exit0. New archive
on3 n8n-20261114T130653Z-038e6a7661ec.tar.gz,45985435bytes, SHA256
568b57170a11c00e9bc90d5cd5aa2c3ca4d82170250c2d672b1a8b46b6c4d6c2.
Independently checked sidecar/archive SHA, manifest sourceNode1, DB hash and
integrity_check=ok,7workflows/10credentials/1user, key present, mode0600. Temporary
verification DB removed; used3's persistent disk, not its small RAM-backed /tmp.

GitOps:6a9835e5(storage/backup/tests),4ab3ecf3(single writer start). Six rendering,
retention, receiver and admission contract tests plus Helm lint passed. This is
a demonstrated application restore, not full host/VM DR acceptance. CT/VM
migration remains paused; deletion still needs separate acceptance/approval.
Private controller evidence: ~/Library/Application Support/homelab/
n8n-recovery-20261114-4mycqjs2. Concurrent working-tree IAM changes were not touched.

## Historical paused checkpoint — superseded by recovery above

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
