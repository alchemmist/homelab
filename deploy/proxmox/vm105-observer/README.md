# Current deployment: MOS guest-only watchdog

[Operator runbook: deployment map, thresholds, maintenance and recovery](../../../docs/platform/kubernetes/vm105-watchdog.md).

`mos/` contains the deployed user timer and restricted guest command. The MOS admin user manager has lingering enabled. Check `journalctl --user -u mos-vm105-watch.service`. Disable with `systemctl --user disable --now mos-vm105-watch.timer`. To revoke the watchdog, remove only the `mos-vm105-watch` forced-command line from guest root authorized_keys. The watcher fails closed on an unknown host key or changed guest LAN address. It does not use RuDesktop or the Proxmox API. A failed SSH probe never triggers a reboot. The guest checks its own API and Node Ready condition. Three consecutive failing probes trigger up to three k3s restarts spaced at least ten minutes apart if another API is ready. After a final grace interval, a peer-confirmed NotReady node may request one graceful guest reboot. Boot grace is ten minutes; reboots rearm after thirty minutes of observed health. No hypervisor reset. Before planned maintenance disable the MOS timer or touch `/var/lib/mos-vm105-watch/hold` inside the guest; remove that file when finished. The test observed the healthy branch; no production fault was injected.

# VM105 independent incident recorder

Historical only: removed from server1357-11-01. Inspect `journalctl -u vm105-observer --since today`.
Every two minutes it records PVE proxy unit state, loopback HTTPS landing page,
node RRD freshness, guest agent response and guest k3s unit state. This is not
an authenticated API, noVNC, external reachability, etcd or Kubernetes Ready check.
It does not restart anything or deliver alerts. A missing sample is not a pass.
Disable with `systemctl disable --now vm105-observer.timer`.

## Triage before reboot

1. From the authorized management LAN compare the PVE HTTPS landing page with
   the local recorder. Check the authenticated node graphs and console separately.
2. On the hypervisor check `qm status 105 --verbose`, `pvesm status` and
   `qm guest cmd 105 network-get-interfaces` (LAN DHCP address can change).
3. Capture guest and voter journal windows before rebooting. Check API readiness,
   node lease age, elected etcd leader, quorum, disk latency and path loss.
   A TCP connection to port 2379 does not verify a healthy datastore.
4. Preserve both VM disks. Never start the old CT alongside VM105, reset etcd,
   clear WAL or permanently exclude a voter based on one failed bootstrap.
5. Verify VM105 node Ready, Grafana external health and each stateful workload.
