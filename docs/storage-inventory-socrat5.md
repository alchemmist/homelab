# Storage inventory: socrat-5

Observed: 2026-11-20T14:14:26.819029+00:00. Read-only Kubernetes + SSH inspection.

SSD/HDD media types supplied by owner; guest devices alone do not prove physical media.

| Claim | PV path | Mount source (longest prefix) | Used (GiB, allocated) | Live consumers |
|---|---|---|---|---|
| format-quorum/format-quorum-clang-versions-socrat5 | `/mnt/files/homelab/format-quorum/clang-versions` | `/dev/sdb1` | 0.0429 | 1 |
| format-quorum/format-quorum-config-history-socrat5 | `/mnt/files/homelab/format-quorum/config-history` | `/dev/sdb1` | 0.0004 | 1 |
| format-quorum/format-quorum-tests-socrat5 | `/mnt/files/homelab/format-quorum/tests` | `/dev/sdb1` | 0.0008 | 1 |
| cattle-monitoring-system/grafana-socrat5 | `/mnt/files/homelab/grafana/data` | `/dev/sdb1` | 0.0903 | 1 |
| llm/litellm-branding-socrat5 | `/mnt/files/homelab/litellm-branding/data` | `/dev/sdb1` | 0.0086 | 1 |
| monori/monori-back-socrat5 | `/mnt/files/homelab/monori/data` | `/dev/sdb1` | 0.0104 | 1 |
| monori/monori-sync-socrat5 | `/mnt/files/homelab/monori/sync-debug` | `/dev/sdb1` | 0.0000 | 1 |
| automation/n8n-socrat5 | `/var/lib/rancher/k3s/storage/n8n-socrat5` | `/dev/sdb1[/homelab/n8n-socrat5/data]` | 0.5273 | 4 |
| llm/open-terminal-socrat5 | `/mnt/files/homelab/open-terminal/data` | `/dev/sdb1` | 2.3575 | 1 |
| llm/open-webui-socrat5 | `/mnt/files/homelab/open-webui/data` | `/dev/sdb1` | 0.0625 | 1 |
| deeperseeker/deeperseeker-data | `/var/lib/rancher/k3s/storage/pvc-24d92c54-3198-4b7a-bd08-3ec88cc22706_deeperseeker_deeperseeker-data` | `/dev/sda1` | 0.0001 | 1 |
| openhands/openhands-cold-backups | `/var/lib/rancher/k3s/storage/pvc-27716289-aa8c-4da0-97b1-3239eae625bf_openhands_openhands-cold-backups` | `/dev/sda1` | 0.7441 | 1 |
| openhands/openhands-upgrade-backups | `/var/lib/rancher/k3s/storage/pvc-59ac8c87-58a0-4bf0-a7cb-a487a9e95728_openhands_openhands-upgrade-backups` | `/dev/sda1` | 0.0377 | 0 |
| netbird-host-peers/machine-socrat-5 | `/var/lib/rancher/k3s/storage/pvc-619eb86a-bfbb-4640-9d7a-bf42fc1f5c41_netbird-host-peers_machine-socrat-5` | `/dev/sda1` | 0.0000 | 1 |
| swe-mini/swe-mini-state | `/var/lib/rancher/k3s/storage/pvc-8c19dd26-34f3-4cc0-8594-81ff825bb5ef_swe-mini_swe-mini-state` | `/dev/sda1` | 0.0015 | 1 |
| openhands/mutation-report-intake | `/var/lib/rancher/k3s/storage/pvc-a188f9e9-9471-42d4-9f72-f4cee5e390ca_openhands_mutation-report-intake` | `/dev/sda1` | 0.0001 | 1 |
| openhands/data-openhands-0 | `/var/lib/rancher/k3s/storage/pvc-d209870e-c917-4bd5-ac4b-8f64dd215eea_openhands_data-openhands-0` | `/dev/sda1` | 3.4164 | 2 |
| venice-api/venice-browser-profile | `/var/lib/rancher/k3s/storage/pvc-fb27d320-f1ee-4522-81e9-9475b6783209_venice-api_venice-browser-profile` | `/dev/sda1` | 1.1063 | 1 |
| automation/spi-triage-socrat5 | `/mnt/files/homelab/spi-triage/data` | `/dev/sdb1` | 1.1229 | 1 |
| wiki/wiki-runtime-socrat5 | `/mnt/files/homelab/wiki-runtime/data` | `/dev/sdb1` | 0.3273 | 1 |
| wishlist/wishlist-socrat5 | `/mnt/files/homelab/wishlist/data` | `/dev/sdb1` | 0.0005 | 1 |

## Evidence limits

- Permission-denied canonical lookup or du is **unknown**, not zero. Mount-table resolution does not follow inaccessible symlinks.
- n8n bind mount is positively confirmed from /dev/sdb1; its PV path is not an SSD indication.
- Owner-authorized sudo read-only inspection completed. No privileged diagnostic Pod, sudo-policy change, deletion or restart was introduced. All PV paths above were individually measured and resolved with privileged findmnt.
- Filesystem snapshot: root 93 GiB, 69 GiB used, 20 GiB available; HDD about 2 TiB, 6.5 GiB used. This is not sum of PVC requests.
- Runtime SCs local-path and nfs-shared both carry default=true. Existing NFS playbook intends NFS alone to be default. Do not adopt K3s-managed objects into Argo without an ownership transition.
- Old retained claims with no running consumers are recovery datasets, not safe deletion candidates.

## Privileged disk breakdown — 20 November 2026

| Directory | Allocated size (rounded du) |
|---|---:|
| K3s containerd | 58 GiB |
| ↳ overlayfs snapshots | 41 GiB |
| ↳ content store | 13 GiB |
| ↳ CRI directory | 4.6 GiB |
| K3s local PVC directories (excluding HDD bind mount) | 5.4 GiB |
| K3s agent images directory | 596 MiB |
| /root (retained staging/recovery material included) | 1.2 GiB |
| /usr | 1.5 GiB |
| /var/log (independent traversal) | 283 MiB |
| HDD homelab data, including retained migration directories | 6.5 GiB |

**Primary SSD consumer is the container runtime, not application PVCs.** The
snapshot/content/CRI figures describe directory allocation, not garbage that can
be removed. Active image layers and writable snapshots may be required.

Do not add independently traversed directory totals: /var/lib/kubelet reports
8.6 GiB but includes bind-mounted PVC data and may double-count existing data.
A separate /var traversal reported 74 GiB while df and root traversal remained
69 GiB used; different traversal roots cross same-device bind mounts differently.
Use df for filesystem capacity/usage and these measurements for attribution,
not an invented additive balance. No cleanup was performed.

Next diagnostic decision: inventory containerd images, leases and active/writable
snapshots against live workloads, then review kubelet image-GC/eviction settings.
Do not manually remove containerd directories or assume all 58 GiB are reclaimable.
Moving only the 5.4 GiB of PVC directories cannot solve the runtime growth problem.
