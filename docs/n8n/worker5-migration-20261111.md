# n8n / PR Agent / Rancher: worker5 migration, 2026-11-11

Owner authorized all three moves and daily versioned n8n backups to socrat-3.
No NFS enabled; no taints removed; socrat-4 unchanged.

## Ownership and storage

- PR Agent: `charts/pr-agent`, one Pod with gunicorn master + two workers,
  selector worker5 and exact no-NFS toleration. Existing emptyDir caches recreated.
- Rancher: attempted worker5, then rolled back to nodes0/1. Native jailer
  requires device-node creation (`mknod`), denied by unprivileged LXC. No dev-mode,
  jail disablement, privilege expansion or NFS workaround authorized/applied.
  `extraTolerations` is the upstream field; plain `tolerations` is ignored.
  Required anti-affinity and two replicas preserved. Startup-probe budget increase
  did not fix the underlying jailer failure and was reverted as part of rollback.
- n8n: `charts/n8n`, Recreate/single writer. Legacy PVC `automation/n8n` kept
  unchanged for rollback. New `n8n-socrat5` PV/PVC is static local storage,
  `Retain`, node-affinity worker5, path
  `/var/lib/rancher/k3s/storage/n8n-socrat5`, UID/GID1000, directory0700.
- Admission guard gets only the named `automation/n8n-socrat5` PVC exception,
  matching the existing named local NetBird exception. Remote/unclassified PVCs
  remain denied. Policy updated by ownership-checked resourceVersion CAS;
  preimage retained privately during execution. Source remains in
  `deploy/admission/socrat5-local-storage.yaml`.

## Migration

Git first quiesced n8n to zero replicas. Waited for the old Pod to disappear,
then mounted legacy PVC read-only in a temporary migration reader. Archived all
state, copied to worker5 as UID/GID1000, and stored a separate pre-migration
archive on worker3. Offline `PRAGMA integrity_check`: ok; 7 workflows,
10 credentials, 1 user, 5 active workflows. Existing encryption-key Secret and
native login/SSO/webhook identities unchanged. No workflow manually executed.

Pre-migration archive SHA256:
`35f6b8b93f159c79e724f091e4a7f472b2bc94bf573b6dc4a22ce615e66a4820`.
Archive contains private credentials/state: do not publish or commit it.

## Daily backup contract

`CronJob automation/n8n-backup`: 03:15 Europe/Moscow, daily, Forbid overlap,
30-minute deadline, one retry. Runs on worker5 using the same pinned image as n8n,
nonroot, no API token, read-only data mount, bounded ephemeral scratch.

`charts/n8n/files/backup.cjs` uses SQLite's online backup API and checks the
snapshot's integrity. Copies non-database state (excluding diagnostic event logs
and old database copies), adds the existing encryption key and recovery manifest,
then gzip/tar streams over pinned-host-key SSH. Non-database files are copied
online: not a transactionally atomic snapshot of binary objects/external systems.
Does not stop n8n, execute workflows, or modify its database.

Receiver: `scripts/n8n/backup_receiver.py`, installed as
`/home/alchemmist/bin/n8n-backup-receiver.py` on worker3. Dedicated key is restricted
in authorized_keys with forced command, no PTY/forwarding. Only accepts receive
command; no caller-selected paths. Validates gzip CRC and required archive members,
limits compressed/expanded bytes, atomically publishes versioned archives with
SHA256 sidecars. No extraction on receiver. Private directories0700/files0600.

Destination: `/home/alchemmist/backups/n8n/` on socrat-3. UTC timestamp + random
suffix per archive. All versions retained (no automatic deletion); monitor disk
usage. This is private access-controlled storage, **not at-rest encrypted**.
Encryption key accompanies credential ciphertext, so restrict access to archives.
`n8n-backup-ssh` is a Kubernetes Secret provisioned separately, never in Git.

## Restore (explicit operator authorization required)

1. Select version and verify its `.sha256`; inspect manifest/integrity offline.
2. Keep source archive private; extract only into a new isolated directory.
3. Stop the sole n8n writer through Git before changing production state.
4. Restore `data/` into a new local volume with correct node affinity/UID1000.
5. Restore the archived `encryption-key` to `n8n-secrets` only if the existing
   encryption key has been lost; never rotate it during a routine restore.
6. Keep original volume and Secret for rollback. Point Deployment to restored PVC,
   start one replica, verify health/login/workflow/credential counts and normal
   schedules without manually triggering production workflows.

Rollback is not just reverting nodeName: restore original claimName `n8n`,
nodeName socrat-1, and quiesce worker5 first. Old PVC is a migration-time snapshot;
post-migration writes require a fresh reverse migration, not a blind rollback.

## Limits

Backup versions on worker3 protect against loss of worker5 but not simultaneous
loss of both machines. Backups do not include all cluster Secrets, Rancher state,
etcd, external services or complete host recovery. Static local PV's 5Gi capacity
is a Kubernetes declaration, not an enforced filesystem quota. worker5 root is a
loop-mounted filesystem; physical backing-store capacity is not established here.

## Acceptance and incident record

PR Agent received real GitHub webhooks on worker5; outbound GitHub and existing
LiteLLM liveness both HTTP200. n8n public healthz HTTP200/ok; database identity
counts unchanged. Two manual runs of the exact daily CronJob completed and
published separate ~19MiB archives. On worker3 one archive was independently
SHA256-verified, SQLite extracted into a private temporary directory and checked:
integrity ok, 7 workflows, 10 credentials, 1 user, 5 active workflows. Recovery key
present. This proves archive/database readability, not a full application DR drill.
Negative server-dry-run admission probes rejected foreign PVC and inline NFS.
Migration helper Pod removed; legacy PVC preserved. Four rendering/receiver tests
passed. Initial Git push raced an unrelated bot deploy; fetched/rebased without
overwriting it. Rancher cold image pull and catalogs took minutes; original
startup budget caused restarts. With a bounded 10-minute startup budget, Rancher
reached native jailer and exited status2 (`mknod: Operation not permitted` confirmed
inside pod). The stalled older Argo sync operation was scoped-terminated via its
status phase so newer committed desired state could reconcile; no blanket sync,
prune, image override, healthcheck disabling or privileges added.
