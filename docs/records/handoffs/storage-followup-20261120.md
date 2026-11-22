# HDD-first closeout —20 November 2026

## Completed and accepted

| Item | Evidence |
|---|---|
| containerd on HDD | Existing original-path bind to /dev/sdb1; kubelet imageFs capacity2TiB |
| SSD runtime preimage removed | Exact retired path checked for wrong device/mounts/open references;58,421,215,232 bytes reclaimed; no PVC deletion |
| Dynamic local-hdd and local-ssd | Existing provisioner; Retain, WaitForFirstConsumer, local PVs, topology only socrat-5 |
| HDD-first ordinary new local data | New legacy local-path claims on5 map to HDD; other nodes/legacy specialized mappings preserved |
| One cluster default | nfs-shared only; local-path and both new tiers explicitly non-default |
| Single source owner | Argo storage-tiers owns the same6 existing provisioner/config/RBAC/class objects; UIDs unchanged; packaged writer skipped, not uninstalled |
| Disk-safe helper | Expected device ID + UUID sentinel checked before setup/teardown; no unsafe helper-template flag, new privileged helper or extra RBAC |
| Monitoring deployed | Grafana dashboard socrat-storage found through MCP;3 rules loaded in Prometheus; stable append-only graph links regenerated |
| SSD vs HDD visible | Traffic Light root safety indicator explicitly named; storage dashboard separates / and /mnt/files and excludes K3s bind aliases |
| Archive data on HDD | Two OpenHands backup/archive claims moved with cold checksum validation and original-path binds; no backup Job run |
| Rancher Healthy | Observer NetworkPolicy now permits advertised API node5 /32 TCP6443; normal CronJob succeeds; no failed resources in MCP tree |
| Persistence | fstab verification0 parse errors; startup guards pass; repeated owner/runtime Ansible plays changed0, no service restart |

Latest guest df after archive handoff: SSD93GiB total, ~11GiB used, ~78GiB available
(~12% occupied); HDD~2TiB total, ~64GiB used, ~1.9TiB available. Values are rounded
and are point-in-time, not continuous capacity guarantees.

## Live storage acceptance (fixtures removed)

- local-hdd: dynamic PV on device2065 at /mnt/files/homelab/volumes; write/fsync,
  read, Pod recreation and reread succeeded; after PVC deletion PV Released
  proved Retain behavior.
- local-ssd: same sequence on device2049 at /var/lib/rancher/k3s/fast-storage;
  Retain behavior confirmed.
- legacy local-path on node5: write/read/recreation on HDD succeeded; original
  Delete lifecycle still cleaned the owned test volume.
- Negative test: ordinary nonprivileged Pod used a root-backed emptyDir mounted
  at the HDD parent path and copied the correct HDD UUID marker. The real setup
  script rejected device2049 before mkdir; correct marker alone cannot fool it.
  Production HDD was never unmounted for this test.
- Only test namespace/PVCs/Pods and exact fixture PVs/directories were deleted.
  All21 original application claim UIDs retained, including archive claims.
- Private operator receipts under ~/.config/homelab/storage-followup and node5
  /var/lib/homelab-recovery; no credentials or dataset contents printed.

## Existing-data policy

Archives moved to HDD; active small agent SQLite/work state, browser profile and
node identities remain explicit SSD exceptions. Critical database placement is
owned by its database policy. This is not a wholesale migration or a claim that
all applications benefit from SSD. New ordinary node5 local-path data is HDD-first;
new explicit fast claims use local-ssd. Cluster-wide no-class claims still use
NFS deliberately, not a single-node disk. Directory PVC sizes are **not quotas**.

## Rancher diagnosis (not alert suppression)

The actual degraded resources were observer-membership CronJobs, not the Rancher
backend. Native Kubernetes API service can choose node5; its /32 was absent from
the observer's TCP6443 egress allowlist. Added only the exact advertised address.
No membership grants, accounts, token secrets, IdP auth or alert silence changed.
Existing scheduled Jobs succeeded after the fix; old failure records expired by
their existing TTL, not a bulk deletion to hide errors. MCP tree then had no
unhealthy resources and Application became Synced/Healthy.

## Remaining external limitation: DeepSeek

DeeperSeeker's native readiness remains false; earlier failures were external401/
invalid session. Read-only local SQLite inspection found one ACTIVE token: local
ACTIVE status does not prove upstream validity, and it is not claimed currently
QUARANTINED. No new upstream calls were made by this followup to rediscover an
already known failure.
Current authoritative docs/applications/ai/deeperseeker.md records a historically revoked/
quarantined main token and a no-login/no-restart window for two banned accounts until
**21 November2026 23:48 MSK**. Whether main is the banned account is not proven.
Do not try to close this by reauthentication now, repeated Restore, browser
automation, token purge, inference tests, credential reset or readiness suppression.
This followup did NONE of those operations. After the documented window, native
owner recovery follows that runbook and requires account/session prerequisites.
Storage is accepted; the external session is **not claimed fixed**.

## Limits and rollback

Physical Proxmox backing capacity was not checked and cannot be inferred from VM
free space; owner authorized SSH-only guest work. Independent backups/DR and a
second cold-boot test after the final archive-bind update are not claimed.
Runtime has been tested through the migration reboot; final fstab and guard
checks passed without imposing another outage.

The old SSD runtime copy is gone; rollback now requires a cold reverse handoff of
current authoritative HDD state, not restoring stale metadata. Application data
was not rolled back. Git-owner rollback must first quiesce reconciliation and
coordinate packaged .skip ownership; do not delete Argo Application/resources
with prune or disable/uninstall local-storage.
