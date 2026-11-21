# One-time retirement of the pre-cutover workshop, 2026-11-21

Scope is exactly the **contents** of `/var/lib/socrat-thanos` on `socrat-0`.
Do not generalize these scripts into periodic retention. They deliberately pin
the node, directory device/inode, post-cutover Prometheus UID and original TSDB
PVC. Run Python without optimization. Do not delete the TSDB, WAL, shipper
journal, current S3, 5m NFS, 1h shelf, compactor workspace, or PVCs. Leave an
empty original mountpoint; no recursive wildcard host cleanup.

The first new production upload `01M7ZQNKDF9JW6PX0TH142HGHX` appeared naturally
at 19:00 UTC; `warm-natural-shipper-ngvx2` completed at 19:02:08 UTC. It compared
694,621,248 bytes of live index/chunks from the TSDB with S3; metadata/source,
ULID, interval and stats also matched. Shipper had 1 upload and 0 upload failures.

`pack.sh` creates a private compressed tar **outside** the original directory
on 0 (transit spool), tests it, restores the whole tree, compares every SHA-256
with the independent source read, and removes only the verified scratch restore.
S3 primary storage is physically on 1; the transit archive is on 0. It is not
an offsite backup until `socrat-3` has received and verified it. Do not conflate
an archive-in-progress with a successful restore.

`retire.py --release-verified-files` checks the natural shipper Job, live PVC,
no direct raw hostPath, compactor/Store S3 identities, hourly destination,
and live unmarked S3 block/lineage coverage at the same resolution/labels and
full time interval. It independently hashes the cold archive and the old raw
tree again. It stops on a mismatch and permits unlinking **only** manifest
files; it cannot authorize deleting the 5m shelf or the backup. The per-run
`released.json` records the file count, bytes and hashes. A failed gate is an
investigation, not permission to disable an assertion.

`offload.py`: scoped TLS Service + single-purpose reader mount only the spool,
not live data. Job `raw-packed-copy-20261121` pulls byte ranges to the private
backup directory on 3, fsyncs and checks the full archive SHA-256. The ingress
policy allows only its matching Pod; a short-lived TLS cert and a one-use secret
protect the private endpoint (credentials not in Git). Compressed bytes do not
pass through Grafana, Prometheus, the Kubernetes API or the workstation.

`finish_offload.py --after-release` requires the confirmed source-release receipt.
It transfers the manifest, waits for a successful offload Job, then independently
checks the archive hash **and** every decompressed tar member on 3. Only then may
it remove the now-identical compressed transit file from 0. Network errors or a
failed restore retain the local compressed backup. Temporary Service, policy,
secret, script ConfigMaps and serving Pod are removed after success. Keep the
verified cold copy on 3 in `/home/alchemmist/.local/state/socrat-backups/retired-thanos-raw-20261121/`.
The final receipt is `restore-verified.json` there and `offsite-complete.json` on 0.
Never put a backup directory under an active Thanos reader or writer.

Recovery: verify `raw.tar.zst` against the recorded SHA-256, restore into a new
empty private directory, compare `tree.manifest()` to `manifest.json`, and query
through an isolated read-only Store first. This backup is not a substitute for
newer data written to 1 after cutover. Do not point a live writer back at it.

19:25 UTC: the final release completed. All 19 old blocks had active S3
coverage. Full cold restore matched 148 files / 53,235,947,912 logical bytes;
manifest `bdb264b6d7dd302333cf350f62645d332ec93256c207c5c79052578690e9ca93`.
Raw directory contains zero entries (4 KiB for the directory itself). Available
space increased 53,232,201,728 bytes during unlink (49.58 GiB). Compressed
transit archive 14,422,352,421 bytes / 13.43 GiB, SHA-256
`368b1e8f9b96c9d9f600c62a43c34d165d60a513aece08bcec7c76d760939c8a`.
At this checkpoint the off-host copy was in progress, not yet independently
accepted on 3. The running finish controller keeps the transit copy unless
both the remote archive and its decompressed manifest verify. The net space
reclaimed before transit-spool release is approx. 36.14 GiB.
