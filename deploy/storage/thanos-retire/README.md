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

Final check at 21:28 UTC: `raw-packed-copy-20261121` completed. On socrat-3
`restore-verified.json` confirms the full compressed archive and decompressed
manifest; SHA-256 matches the value above. On socrat-0 `offsite-complete.json`
records the same digest, the transit `raw.tar.zst` is absent, and the pre-cutover
raw directory has zero entries. No compressed transit copy remains to reclaim.

## Recovery limit observed on 2026-11-22: raw block downsampling EOF

The workshop Compactor failed to expand chunk ref `167710384981` in raw block
`01M7RY8BC3H3G4HNS4B7BQB8T2` (Nov 13 00:00 through Nov 19 00:00 UTC,
exclusive). The 54-byte record at offset 206660437 in `chunks/000040` matched
between an authenticated S3 range GET and the Compactor cache. Its CRC32C was
valid, but the Prometheus v0.309.1 XOR iterator read 89 of the 120 advertised
samples before EOF. This does not establish loss of the entire block.

The verified cold manifest on socrat-3 contains this block. Its recorded SHA-256
for the entire 536870100-byte segment is
`2b3b77c4356c533b6a0ed7bd4e59b5f38bf8745361bce54f3791bf92f9a7ee23`,
identical to the freshly hashed cache segment. None of the three immediate
parents or the 206 source IDs appear in the cold manifest. Restoring this
archive or downloading the segment again is therefore not a repair for this
record. Preserve the archive, original block and marks. Before replacing any
block, validate a candidate offline, including strict historical queries and
lineage/coverage; do not infer complete coverage from an overlapping interval.

The v2 index entry for series ref `88792714` (series and symbol table CRC32C
checked) maps the exact failing chunk to `node_systemd_unit_state` for
`dbus.socket`, `state="activating"`, `instance="192.168.0.24:9100"` on socrat-1.
Its indexed span is 2026-11-17 04:20:04.097–04:29:59.097 UTC inclusive.
A strict raw-only 10-minute range vector, matching all stored labels and
restricted to the workshop Store, returned HTTP 422 `EOF` for that window.
The same query moved ten minutes earlier and later returned 120 samples each.
The Prometheus sidecar and the separate 5m/1h Stores advertise time ranges
excluding this date. Do not infer the missing values from adjacent samples.

## Cold audit verdict and surgical repair, 2026-11-23

The full cold audit of raw block `01M7RY8BC3H3G4HNS4B7BQB8T2` finished on
socrat-3 (`thanos-cold-block-audit`, streaming the `retired-thanos-raw-20261121`
archive without unpacking it). All 49 chunk segments passed: every per-file
size and SHA-256 matched the verified manifest, every record CRC32C validated,
and every chunk decoded with the upstream v0.309.1 XOR decoder. Totals matched
the block compaction stats exactly: 209,661,260 records over
25,065,032,497 advertised samples. Exactly one record failed: the already
localized chunk ref `167710384981` in `chunks/000040` (CRC valid, XOR decoder
EOF at 89 of 120 samples). The corruption is confirmed to be limited to the
last 31 samples of that single chunk; nothing else in the block is damaged.

Repair applied (option chosen: keep the 89 decoded samples, drop the corrupt
tail, in place):

- Record layout at offset 206660437 of `chunks/000040`:
  `[uvarint chunkLen=48][version 0x01][48-byte chunk][CRC32C BE]`; the chunk
  starts with a big-endian uint16 sample count.
- The count was patched `120 -> 89` and the record CRC recomputed. Segment
  size stays exactly 536,870,100 bytes; every other byte, all offsets and the
  v2 index are unchanged. New segment SHA-256:
  `8a67942454db0b3da7222c0e12be2adebc708ccce27b2b5cf7e45bc0cf6e11f5`
  (original preserved verbatim in the cold archive:
  `2b3b77c4356c533b6a0ed7bd4e59b5f38bf8745361bce54f3791bf92f9a7ee23`).
- The patched segment re-audited end to end: 5,426,540 records,
  650,737,445 advertised samples, `bad=0`.
- The S3 object `thanos-workshop/01M7RY8BC3H3G4HNS4B7BQB8T2/chunks/000040`
  was replaced via multipart upload with the audited bytes under the
  compactor write credential; a pre-replacement S3 copy matched the archived
  original hash, and a post-replacement ranged GET matched the patched hash.
- Verification in production: the raw Compactor completed a full compaction
  iteration and the downsampling pass with zero EOF errors and no restarts;
  the previously failing strict raw-only query_interval for 2026-11-17
  04:20–04:30 UTC now returns HTTP 200 with samples across the window.
  The permanent data loss is the final 31 samples (about 04:29:50–04:29:59
  UTC) of `node_systemd_unit_state{state="activating", name="dbus.socket",
  instance="192.168.0.24:9100"}`; adjacent values were never substituted.
