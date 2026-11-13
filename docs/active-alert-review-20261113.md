# Active alert review — 2026-11-13

## Scope and observations

Read-only review around 15:45 UTC found eight firing warning series, excluding
Watchdog. The earlier Moscow CPU-contention warning is no longer firing in this
snapshot; that does not establish that capacity contention is permanently solved.

| Firing series | Evidence | Disposition |
| --- | --- | --- |
| `KubeJobFailed`, `automation/n8n-backup-29908815` | Both attempts terminated OOMKilled after about four seconds on November 13. Last scheduled success November 12 00:15:14 UTC. | Actual unresolved backup failure. Repair below; production acceptance still required. |
| `KubeJobFailed`, `pr-agent/spi-github-broker-29903600` | Historical failed Job; same CronJob succeeded November 13 15:40:06 UTC. | Service currently refreshing, historical failure retained. |
| `KubeJobFailed`, `pr-agent/spi-github-broker-29906640` | November 11 log reports installation-stage refresh failure, with code redacted by existing application logging. Same fresh success as above. | Original transport/HTTP cause not established. |
| `KubeJobFailed`, `pr-agent/wiki-openapi-broker-29903600` | Historical failed Job; same CronJob succeeded November 13 15:40:05 UTC. | Service currently refreshing, historical failure retained. |
| `KubeJobFailed`, `pr-agent/wiki-openapi-broker-29906640` | November 11 installation-stage `URLError`; same fresh success as above. | Exact transport cause not established. |
| `KubeJobFailed`, `cattle-monitoring-system/thanos-cascade-29903670` | Job exceeded its deadline on November 9 11:30 UTC. Same CronJob succeeded November 13 15:30:07 UTC. | Current scheduled processing succeeds; does not by itself prove all backlog or block integrity. |
| `NodeSystemdServiceFailed`, Moscow `cloud-init-main.service` | Failed since November 9 20:35:42 MSK. | Boot provisioning failure, not a current k3s-agent failure. Requires private privileged inspection. |
| `NodeSystemdServiceFailed`, Moscow `cloud-init-network.service` | Failed since November 9 20:35:39 MSK. `cloud-init status --long` reports bootcmd exit 255. | Exact command and safe correction not yet established. |

No failed Jobs were deleted, alert rules changed or alerts silenced. Fresh
successful scheduled broker runs are not a justification for replaying production
workflows, rotating credentials, or blindly deleting failed evidence. The two
cloud-init units were not reset, restarted, masked or disabled. Replaying provider
boot provisioning may change networking or identity and is not a routine repair.

Noninteractive sudo is unavailable on Moscow. The unprivileged journal has no
entries for these units. A bounded Loki lookup around the recorded November 9
failure also returned no entries. None of these absences proves that the error was
harmless. Preserve the current worker, VPN, SSH and WireGuard configuration.

## n8n bounded-memory correction

The live SQLite file was 526,041,088 bytes (about 501.7 MiB), observed using only
`fs.statSync` in the existing n8n container. The backup container limit is 512 MiB.
The existing script hashes the snapshot using `fs.readFileSync`, allocating the
entire database in addition to Node, SQLite and other process memory. This is a
concrete incompatibility with the limit. The terminated jobs have no stage logs,
so the precise OOM instruction is inferred, not captured in a trace.

`charts/n8n/files/backup.cjs` now computes the same SHA-256 through an awaited
64-KiB read stream. A hash read error aborts the backup before transfer. SQLite's
online backup, read-only source, integrity check, recovery key, manifest, restricted
pinned SSH destination and append-only versioned receiver are unchanged. No
schedule, resource limit, live database, PVC, credential or production workflow is
changed. Only the backup script ConfigMap changes in the rendered Kubernetes
resources; the n8n Deployment has no checksum dependency on this ConfigMap.

The helper is importable without loading the production SQLite module or starting
a backup. Regression tests prohibit synchronous whole-file reads and check empty,
small, binary, missing and synthetic 528-MiB snapshots. The large fixture must
produce the expected digest below 160 MiB process RSS. Synthetic tests are not
production backup or restore acceptance.

Validation: Node syntax check and 37 focused tests passed (streaming, worker5
storage/receiver, failure alerts/policy and activity exporter). Publication and
production acceptance are recorded separately below when actually completed.

## Remaining acceptance and cleanup boundary

1. Verify the committed backup ConfigMap reconciles without restarting n8n.
2. Run or await one exact backup CronJob attempt; require successful completion,
   receiver archive publication/checksum and private offline SQLite integrity and
   manifest hash verification. Do not trigger n8n business workflows.
3. Preserve private Job status/log evidence before any individually approved
   cleanup of historical failed Jobs. Do not weaken history limits or KubeJobFailed
   merely to hide warnings. Even a successful ad-hoc backup does not update the
   original CronJob's last-success timestamp or remove its old failed Job.
4. Inspect cloud-init bootcmd and relevant root-only logs privately with authorized
   privilege. Do not expose cloud user-data, rerun all cloud-init stages, reboot,
   or reset the failed state before understanding the command and next-boot effect.
