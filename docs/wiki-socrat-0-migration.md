# Wiki recovery and relocation — 2026-11-01

## Result

Wiki now runs as one writer on socrat-0's SSD, using PVC
`wiki-runtime-data-socrat-0` and retained PV `wiki-runtime-data-socrat-0-20261101`.
The restored directory is
`/var/lib/rancher/k3s/storage/wiki-runtime-data-socrat-0-20261101`.
Image/config/Secrets and public/private routing were retained. Helm revision 26
completed successfully. This is a single-node local-volume deployment, not data
replication or automatic failover to socrat-1.

Both public IPs returned HTTPS 200 for `/` and `/healthz`; `/login` returned the
expected OIDC redirect (303). The pod is Ready, Git sync has no error, SQLite
integrity_check is OK, and zombie count is zero. No user account was created or
modified during verification; a full authenticated browser login was not tested.

## Cause and safety

socrat-3 repeatedly became NotReady under extreme disk pressure (I/O PSI up to
90–95%), causing endpoint withdrawal and pod eviction. Git zombies were absent.
Restarting only K3s on socrat-3 did not restore it promptly: etcd startup timed
out. socrat-0/2 maintained quorum, confirmed via etcd endpoint status. K3s on
socrat-0 independently restarted during the incident; this operation was not
initiated by this session.

Before relocation, a short collector ionice experiment was reverted to its
original `none` class. A temporary publishNotReadyAddresses service override
was also reverted to false. One pending socrat-3 pod was given indefinite
NotReady/Unreachable tolerations to stop eviction churn; that pod was subsequently
removed by scaling the deployment down. The new socrat-0 pod uses the normal
chart tolerations. K3s on socrat-3 was temporarily given elevated best-effort I/O
priority during startup; this is process-local, not a permanent service setting.

## Offline copy

Fleet GitRepo `fleet-local/wiki-runtime` and Bundle
`fleet-local/wiki-runtime-deploy-wiki-runtime` were paused, then the deployment
was scaled to zero. Host-side inspection confirmed no Wiki writer remained in
the old pod cgroups before archiving. The full 251 MiB data directory was copied,
not reconstructed from remote Git.

Protected archives, mode 0600 under root-only directories, remain on socrat-3 and
socrat-0 at `/var/backups/wiki-move-20261101/wiki-data.tar.gz`.
SHA-256 on both hosts:

`7578da6d387170f5d73371dd67abd4d621428feb0bb38a18b54293b20918dcd5`

Transfer passed through controller memory only; no backup was stored on the Mac.
Extraction was verified with tar comparison, SQLite integrity_check, and Git fsck
for both repositories. The original PVC `wiki-runtime-data` on socrat-3 is retained
and was not repointed, deleted, or reused.

The target PV uses Retain. Its declarative specification is in
`ansible/files/wiki-runtime-storage-socrat-0.yaml`; it provisions no data and must
not be used as a substitute for restoring a verified backup. At that time, Fleet values
selected the new claim and node socrat-0. Current selection is `deploy/wiki-runtime/values.yaml`, applied by the Argo CD Application.

## Fleet handoff — required before resuming reconciliation

**Retired. Do not execute this handoff.** GitRepo `fleet-local/wiki-runtime` and Bundle `fleet-local/wiki-runtime-deploy-wiki-runtime` are no longer declared in this repository. Wiki reconciliation is the Argo CD Application `wiki-runtime`. The record below is the 2026-11-01 live pause that stopped old Git values from moving the volume back to socrat-3.

At completion, **both GitRepo and Bundle remain paused live** to prevent the
old remote Git values from moving Wiki back to socrat-3. The source values change
is local and uncommitted. After reviewing, committing and pushing the new values
and storage declaration, the historical steps were:

1. Resume GitRepo `fleet-local/wiki-runtime` and ensure it observes the new Git
   revision (do not resume against the old claim/node configuration).
2. Resume Bundle `fleet-local/wiki-runtime-deploy-wiki-runtime` if still paused.
3. Confirm desired claim `wiki-runtime-data-socrat-0`, nodeSelector socrat-0,
   one replica, readiness and public access after reconciliation.

No automatic rollback to the old PVC is safe after new publications or account
changes. Recovery back to socrat-3 or onward to socrat-1 requires another offline,
single-writer data migration preserving the complete current volume.
