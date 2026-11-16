# Backup coverage checkpoint —16 November 2026

Bounded read-only inspection of CronJobs/PVs/PVCs, system timers on socrat-0,
and n8n receiver metadata on socrat-3. Private receipts outside Git:
`~/Library/Application Support/homelab/infra-refactor-20261116/` (0700/0600).
No workflow, publication, bank request, production restore or key rotation.

## Verified n8n recurring path

- `automation/n8n-backup`, daily03:15 Europe/Moscow, unsuspended;
  lastSuccessfulTime2026-11-16T00:15:33Z.
- Actual job template selects **socrat-5**, mounts **n8n-socrat5** read-only.
- Source uses SQLite online-backup API/integrity check and preserves encryption
  key and non-database state; non-database files are not a global atomic snapshot.
- Receiver **socrat-3**, `/home/alchemmist/backups/n8n/`:12archives,11with SHA
  sidecars. Latest paired archive46,526,224bytes; SHA256 recomputed successfully.
- Manifest identifies source **socrat-5**. Latest paired database extracted to a
  private temporary directory on socrat-3, manifest DB hash verified, opened
  immutable/read-only and `PRAGMA integrity_check=ok`. Temporary copy removed.
  No application launched and no workflow executed.
- **One unpaired archive is not accepted as a verified backup.** Not deleted or
  silently counted; provenance/retention cleanup remains separate work.
- This proves an independent SQLite restore check, not complete n8n application,
  credential decryption, external service consistency, VM restore or cold boot.
  Storage is access-controlled, not encrypted at rest; key accompanies ciphertext.

## Remaining coverage must not be inferred from migration archives

| Authoritative dataset | Current source / location | Recurring independent backup / restore status |
|---|---|---|
| Wiki runtime | wiki-runtime-socrat5; /mnt/files/homelab/wiki-runtime/data | Full migration seal exists; no recurring coverage accepted by this inspection. Git alone insufficient. |
| Wishlist | wishlist-socrat5; /mnt/files/homelab/wishlist/data | Migration archive verified previously; recurring job/independent restore not yet accepted. |
| Monori back/sync | monori-back-socrat5 / monori-sync-socrat5 | Credentials key + all SQLite/debug state need coverage; no bank sync as restore test. |
| SPI worker | spi-triage-socrat5 | Job/link/lease history and credentials required; no replay. Recurring coverage not established. |
| format-quorum | Three new local datasets on socrat-5 | History/compiler assets covered by cold migration seals; recurring coverage not established. |
| LiteLLM branding | New local dataset on socrat-5 | Original public assets verified in handoff; recurring backup owner not established. |
| Grafana | grafana-socrat5; /mnt/files/homelab/grafana/data | Cold independent archive + exact restore accepted; keys/identity/ACL preserved. Old socrat-1 claim stale; recurring coverage still not established. |
| VM105 / Kubernetes identity | Existing API/host identity and VM disks | App archives/Healthy do not prove full independent VM restore/cold boot. |

Cluster also contains `lms-database-backup` every6hours with recent success. That
is not evidence it backs up the datasets above. OTEL credential rotation and
Thanos cascade jobs are not general application backups. Only dpkg backup timer
was found in the bounded system timer query on socrat-0; other hosts/user timers
and external jobs have **not** been exhaustively inspected.

Next step: finish scheduler/destination/retention inventory, then implement
consistent per-dataset backup adapters with an independent destination and
isolated restore checks. Do not create a generic tar of live SQLite/WAL or
schedule repeated application shutdowns under the label of refactoring.
Stale retained volumes must not be promoted over newer authoritative data.
