# PR Agent, n8n and Rancher handoff to VM105 —15Nov2026

## CURRENT authority and placement

Owner explicitly requested moving PR Agent/n8n/Rancher to the now NFS-enabled
socrat-5. Actual starting placement was PR Agent+n8n on1, Rancher replicas on0/1.

| Workload | Accepted placement | State |
|---|---|---|
| PR Agent | socrat-5,1replica | Ready1, restart0 |
| n8n | socrat-5,1replica/Recreate, original n8n-socrat5 PVC | Ready1, restart0 |
| Rancher server | socrat-5,1replica (subsequent owner request) | Ready1, restart0; eligible hostname only5; NO HA |

**The VM105 n8n database is NOW authoritative and accepting new writes.** Its
contents came from the final quiesced socrat-1 recovery dataset, NOT the older
CT104 database. Never restart the retained copy on1 without a NEW consistent
handoff from5. No SQLite/history merge, workflow rerun or credential reset.

The Rancher server replica on0 previously used2730MiB RAM. It is removed;
public-web-rancher-proxy (~2MiB) and separately managed rancher-webhook/control
components were not part of the server-replica migration and remain untouched.
No whole-node drain or unrelated services moved. Observed node0 memory after
rollout~20574MiB/64%; remaining monitoring CPU/memory was not migrated.

## Quiesce, backup, transfer, identity

1. Saved private Deployment/CronJob/Application/Node/PV/PVC/Secret preimages.
2. Created existing-CronJob online backup on1; archive delivered to3, SHA256 and
   manifest sourceNode1 independently checked:
   n8n-20261115T145846Z-41911c64917c.tar.gz,46293807bytes,
   92968117882bc3bba1c66154d3d4cbd7be2cea560d27c09cfa02a24ae6c53e97.
3. Initial last-minute natural-drain check found two new executions and refused
   to publish replicas0. Waited for natural completion; no API deactivation,
   graph publication, forced cancellation/retry or SQL updates. Once active0,
   published replicas0 and refreshed only owned applications for reconciliation.
   PR Agent had0established connections at preflight; GitOps moved it to5.
4. Waited until old n8n Pod was entirely absent and replicas0 persisted. Final
   SQLite integrity_check=ok and active executions0;7workflows/10credentials/
   1user,6active workflows. Historical crashed count120 unchanged. Final cold
   DB SHA2565b74fd67f04ad6456dda1cd9877ba6659b316f56cd17a27bee9b9e0cad12a7fb.
5. Cold archive47454631bytes, SHA256
   82fd803b3c344459ae2a1b8e095b0089b61d988c084127156666a3440574a05e.
   Every file hash checked on controller; archive/DB hashes checked on VM,
   restored SQLite integrity checked again. Native config encryption key byte-
   matched unchanged n8n-secrets. No secret/key printed or stored in Git.
6. First in-memory SSH transfer timed out90s before guest extraction began.
   Verified target absent; resumed via rsync to a separate incoming archive,
   checked full hash before extraction. No partial dataset activated. The
   bandwidth cap/image download extended n8n downtime to roughly8minutes.
7. Original n8n-socrat5 PV/PVC identities/paths unchanged; recovery PV/PVC on1
   and older legacy claim preserved. New data lives on native ext4 data disk:
   /mnt/files/homelab/n8n-socrat5/data, bind at
   /var/lib/rancher/k3s/storage/n8n-socrat5. Restored UID/GID1000:1000,
   data0700/files0600; native Kubelet fsGroup policy subsequently yields2770/0660
   for the owner-only1000group, with no world access.
8. fstab persists bind with x-systemd.requires-mounts-for=/mnt/files; K3s drop-in
  50-worker-data-mounts.conf requires both mounts and mountpoint ExecStartPre
   checks. Prevents silently starting an empty root-disk dataset when data disk
   is absent. Owning worker playbook/inventory now preserve this and refuse an
   empty replacement DB. K3s itself was NOT restarted for these changes.
9. Only after all checks published node5/original claim/replicas1. n8n started,
   activated the same6workflows; native authenticated API confirms7/6. Startup
   data authority transferred to5; no writer left on1.

Physical PVE backing checked before and after transfer; guest root/data free
checked before/after too. After: PVE crutial142GiB/files4.8TiB free, VM root74GiB,
data~2TiB free (~519MiB used). Virtual2TiB QCOW2 capacity is not reserved space.

## Rancher placement and access

Initial handoff: GitOps chart version2.15.2,2replicas, required anti-affinity
retained; eligible hosts1/5. Existing healthy1 served during5's~5minute image pull/startup.
No Rancher PVC/local datastore to migrate: server state remains in Kubernetes.
Initial Helm/Ansible alternate placement defaults changed to1/5 too; removed
obsolete unused nodeSelector0 value. Subsequently owner explicitly requested
removing node1 replica: replicas1, eligible hostname ONLY5 in GitOps and Ansible.
Reconciled to rancher-657cc447c5-4tzlj on5, Ready1/restart0, ArgoHealthy/Synced;
old Pods on1/5 removed. NO HA: stopping/failing node5 interrupts Rancher panel,
not Kubernetes control-plane/workloads elsewhere. Source ba0f0011; private
preimage under ~/Library/Application Support/homelab/rancher-single-vm105-69c1veq1.
No auth features, RBAC, TLS, MCM/Fleet, webhook or control-plane/etcd membership
changes. Public entry/observer policy unchanged.

Public TLS probes: n8n /healthz200/root200/unauthenticated API401;
PR Agent root200; Rancher /ping200/unauthenticated /v3/users401.
All3Argo applications Synced/Healthy. No browser/every credential/provider
operation, synthetic PR review or manual business workflow execution performed.

## Backups after activation

CronJob follows current nodeName5/claim n8n-socrat5, readonly PVC and existing
restricted transfer identity to3, unchanged schedule/Forbid/no API token.
Exact-CronJob n8n-post-vm105-20261115 succeeded; received on3:

- n8n-20261115T151330Z-42a8fc15ac16.tar.gz,46288844bytes,mode0600;
- archive SHA25699c4a7fa87ca7d577d9018d00a6828a01cd97150a01e08214f4242c5e20aaf79;
- DB SHA256edaac36e0dfc8ab259f0f46c408b5786dbad20f39ae310061e92d6adee8e778e.

Independently checked archive+sidecar, manifest sourceNode5, unchanged encryption
key, DB hash/integrity_check and7/10/1counts. Verification used persistent backup
disk, not constrained /tmp; temporary extracted DB cleaned. Initial verifier
used nonexistent home subdirectory, then a repeated-seek gzip reader exceeded
60s; no production data touched. Confirmed that reader finished/cleaned its own
temp directory before rerunning single-pass streaming verification successfully.

App-level backup acceptance is NOT full VM backup/restore or power-cycle proof.
Those VM105 gates remain separate and untested; no reboot during this handoff.

## Durable evidence / rollback boundary

Private receipts/preimages/cold source archive:
~/Library/Application Support/homelab/vm105-apps-20261115 (0700/0600).
Guest preimages: /root/homelab-vm105-worker-restore-20261115-v2;
verified source archive also retained under /root/homelab-vm105-stage-20261114.
Old recovery source on1 left intact but stopped; original CT full backup retained.
No production dataset, Secret, PV/PVC or backup archive deleted/pruned.

Migration source commits e8294090 (placement/quiesce) and08764fda (sole writer
activation), followed by durable mount/acceptance closeout.30 selected source
tests passed, both charts Helm lint passed, worker playbook syntax passed.
Preserve all new VM writes if reverting; never just point n8n at the now-stale
node1 recovery claim.
