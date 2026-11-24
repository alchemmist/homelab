# Thanos local-disk store contracts

The thanos tier (`charts/thanos`, release `thanos-0`, namespace
cattle-monitoring-system) stores metric blocks on node-local disks and scans
host /var/lib for allocation metrics. These are the genuine host-path / root
contracts, documented per object.

## thanos-disk (DaemonSet)

Runs `python3 /scripts/disk.py` on each node (socrat-0/1/3). It:
- reads the host `/var/lib` tree (read-only) to stat per-Thanos-block-dir
  allocation (`/var/lib/socrat-thanos{,-work,-5m,-1h}` and the prometheus DB),
- writes a node-exporter textfile gauge to the host
  `/var/lib/node_exporter/textfile_collector` (writable hostPath),
- loops every 30s and never exits.

Reading `/var/lib` (root-owned) requires uid 0; the container runs
`runAsUser: 0` with all capabilities dropped except none (the drop ALL
overrides) plus seccomp RuntimeDefault and a read-only root filesystem. The
DaemonSet is a node-exporter sidecar-style publisher with no HTTP endpoint, so
it has no liveness/readiness probe (there is nothing to probe; a placeholder
HTTP probe to a non-listening port would be a false positive). The host
`/var/lib` and textfile mounts are the node data channel, not a general host
override.

## Local store hostPath volumes (writable)

The self-hosted thanos object store keeps block data on node-local disks via
hostPath `type: Directory` mounts. The applied `type: Directory` (not wrote
`DirectoryOrCreate`) means each path already exists; the components write real
metric blocks there. Writable hostPath is required for a local-disk store:
- `thanos-compactor` / `thanos-compactor-1h`: hostPath `/var/thanos/work`
  (compaction workspace; -1h additionally on node socrat-3).
- `thanos-store-1h`: hostPath `/var/lib/socrat-thanos-1h` (shelf directory,
  node socrat-3).
- `thanos-shelf-1h`: hostPath `/var/lib/socrat-thanos-1h` (shelf directory,
  node socrat-3).
- `thanos-cascade` (CronJob): hostPath `/var/lib/socrat-thanos-1h` (rawdata
  directory, node socrat-3) and the machine-thanos binary hostPath.

The 5m tier in shared mode uses PVC (thanos-5m-s1-candidate) instead, so the
5m store/compactor/shelf do NOT carry writable host mounts. Only workloads
that must persist block data on a specific node carry the hostPath.

## Isolation

All workloads now run under NetworkPolicies (charts/thanos/templates/
networkpolicy.yaml): store/compactor/query/shelf reach each other over
grpc/http and the scraper over the monitoring namespace; disk/cascade/warm
volume-check are isolated to their peers and DNS only.
