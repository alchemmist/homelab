# Socrat control plane and home ingress HA

## Current voting and control-plane topology

All four nodes run `v1.36.5+k3s1`. On 2026-10-18, socrat-3 was promoted without deleting its agent runtime, and socrat-1 retained its API/controller/scheduler services while relinquishing its etcd vote.

| Node | Kubernetes services | etcd role |
| --- | --- | --- |
| `socrat-0` | API server, scheduler, controller manager, agent | Voter |
| `socrat-1` | API server, scheduler, controller manager, agent | None; dedicated control plane |
| `socrat-2` | etcd-only server with workload agent | Voter |
| `socrat-3` | API server, scheduler, controller manager, agent | Voter |

Quorum is two of three voters: socrat-0, socrat-2 and socrat-3. The two external nodes can maintain quorum after both home nodes fail, provided their direct WireGuard path and disks are healthy. Socrat-3 supplies an external API at `https://10.250.0.5:6443`. CoreDNS, Rancher webhook and each cert-manager component have one replica on socrat-0 and one on socrat-3. Rancher UI, public ingress and application storage have separate placement and availability constraints; this is not a claim that every application survives loss of the home site.

The migration supports socrat-2 being temporarily unavailable: first add socrat-3 as a learner, wait for its promotion, then remove socrat-1 while its original etcd process still runs. Four voters need three votes, so stopping socrat-1 before removing its membership would lose quorum when socrat-2 is down. The helper verifies known names, peer URLs, member IDs and healthy online endpoints; it transfers leadership to socrat-0 before removing socrat-1 if necessary. Only afterward is socrat-1 restarted with `disable-etcd: true`. The final check is read-only. While socrat-2 is unavailable, both socrat-0 and socrat-3 are required and there is no spare vote.

Before and after snapshots plus the server token are retained privately on socrat-3 under `/var/lib/homelab-k3s-rebalance/`; original configuration/service archives remain on each modified node. Snapshot restoration is disaster recovery, not a routine rollback, because it discards later cluster changes. Once socrat-1 is removed, do not restore its old etcd configuration as an automatic rollback. Preserve the archived database and inspect committed membership first.

WireGuard remains the management and flannel network. Socrat-3 uses a direct peer endpoint `176.98.185.59:51830` for socrat-2 and has public egress distinct from the home connection. Its `/32` routes to the home LAN node addresses remain necessary for socrat-0's etcd peer URL. Administrative SSH to socrat-3 currently uses a jump through socrat-0; that administrative path is not the data path between the external voters. Joined embedded-etcd servers can restart using their existing datastore without the original bootstrap server; fresh joins or restores with an empty datastore still require a reachable join endpoint.

The following transport and home-ingress sections describe the existing home-node HA setup and its earlier tests. A physical whole-home power-off test was not performed during the role rebalance.

### Home laptop to VPS transport

Direct WAN UDP between `socrat-1` and the VPS exhibited severe 40–100% packet loss, including raw UDP probes. The `socrat-0`–VPS path and local LAN UDP were healthy. MTU, offload, port and 2.4 GHz experiments did not resolve this; the original Wi-Fi configuration was restored. A TCP probe completed twenty 16 KiB transfers cleanly. The underlying router/Wi-Fi fault is not repaired.

The `wireguard_tcp_transport` role is deployed as a transport workaround for the independent `socrat-1`–VPS path. It uses GOST 3.3.0 with authenticated TLS and a fixed UDP relay:

- The laptop's WireGuard peer for the VPS uses `127.0.0.1:51840`.
- The client reaches `176.98.185.59:51840` over TCP/TLS.
- The VPS relay forwards only to `127.0.0.1:51830`; it is not a general-purpose UDP proxy.
- The VPS WireGuard peer for the laptop learns the relay's ephemeral loopback endpoint.
- TLS verifies the pinned self-signed CA and server name. Authentication material is stored with mode `0600` and must never enter the repository.
- A 15-second health timer restarts the client after three failures, with a 60-second restart cooldown.

This path has no runtime dependency on `socrat-0`. It is necessary for the intended HA topology while the direct UDP fault persists. Carrying WireGuard inside TCP can introduce head-of-line blocking and reduce throughput under loss; it is a reliability workaround, not a repaired native UDP path. Live transport verification passed: twenty WireGuard pings in each direction had zero loss at approximately 45 ms, all three etcd voters were healthy, and the status page through `socrat-1` returned its full 57,056-byte body in approximately 0.35 seconds instead of the previous eight-second timeouts. Wrong CA, wrong server name, missing authentication and wrong password were rejected. An authenticated request for a different UDP target remained pinned to the configured `127.0.0.1:51830` destination, verified through socket inspection. The controlled `socrat-0` API service-stop test passed as described below.

A separate persistent `wireguard-tcp-transport-guard.service` on `socrat-1` blocks only inbound UDP on `wlan0` from `176.98.185.59`, source port `51830`, destination port `51830`, with comment `homelab-wg-tcp-direct-guard`. Authenticated packets arriving through the old direct path could otherwise cause WireGuard endpoint roaming away from loopback. The client requires and starts after the guard, which remains active during client restarts. There is no automatic fallback to the faulty direct UDP path.

To deliberately roll back this transport, first disable and stop its health timer, then its client and guard service on `socrat-1`. Use the following order on `socrat-1`; remove the matching rule only if it remains after stopping the guard:

```bash
sudo systemctl disable --now wireguard-tcp-transport-health.timer
sudo systemctl stop wireguard-tcp-transport-health.service
sudo systemctl disable --now wireguard-tcp-transport.service
sudo systemctl disable --now wireguard-tcp-transport-guard.service
sudo iptables -D INPUT -i wlan0 -s 176.98.185.59 -p udp --sport 51830 --dport 51830 -m comment --comment homelab-wg-tcp-direct-guard -j DROP
```

Restore the VPS peer endpoint in the laptop's persistent `/etc/wireguard/wg-socrat.conf` to `176.98.185.59:51830`, and set that same endpoint in the running interface with `wg set wg-socrat peer <VPS_PUBLIC_KEY> endpoint 176.98.185.59:51830`. Use the existing verified public key from configuration; do not regenerate identities. On the VPS, restore the laptop peer's public UDP endpoint or let it learn that endpoint from an authenticated laptop handshake. Confirm traffic uses the intended path before stopping the VPS relay. Reflect the rollback in the managed transport settings before reapplying Ansible, otherwise it will reinstate the transport. This rollback deliberately returns to the diagnosed unreliable link and is not an availability recovery procedure.

`ansible/playbooks/wireguard-tcp-transport.yml` owns this configuration and is imported by the canonical HA, mesh and administrative-access workflows. Preserve it when reapplying WireGuard: reverting only the peer endpoint to direct WAN UDP reintroduces the observed loss.

VPS `traefik-edge` now uses `https://127.0.0.1:6444`, the standard k3s agent API load balancer with both home API servers as backends. Five authenticated requests returned HTTP 200 and the Helm change was deployed. This validates current connectivity, not a node outage.

## Deployed home ingress

`ansible/playbooks/home-ingress-ha.yml` configures home Traefik redundancy and keepalived. Two home Traefik replicas and keepalived are deployed on the home nodes. Router WAN2 TCP 80/443 now target the VIP; the seven other live forwarding rules were preserved. No physical node-loss test has been performed.

- Two home Traefik replicas serve ingress; Rancher has one replica per home node via `rancher-placement.yml`.
- Keepalived owns `192.168.0.250/32` on either `socrat-0` (`eno1`) or `socrat-1` (`wlan0`). This is outside the DHCP pool `192.168.0.10`–`192.168.0.200`.
- Unicast VRRP uses existing LAN addresses, without a virtual MAC on Wi-Fi.
- Both instances start as `BACKUP` with `nopreempt`; a recovered higher-priority node does not take the VIP away from a healthy owner.
- The health script checks authenticated local API readiness and certificate-validated Rancher `/ping` through the node's own ingress address.
- Persistent router WAN2 TCP 80/443 forwards target the VIP. DNS retains the same home public address; this is not DNS failover.

See [router operations](router-static-mappings.md). Verify exactly one VIP owner, both direct ingress endpoints and public Rancher before and after cutover. A keepalived handover checks ingress, not complete node-loss recovery.

### Wi-Fi ARP recovery

The home access point drops wired-to-Wi-Fi broadcast ARP for both `socrat-1`'s physical address and the VIP. Directed unicast ARP succeeded in all three probes. The managed helper therefore announces the node's physical address and, only when locally owned, the VIP directly to the router and peer. Keepalived invokes this repair through its health check every three seconds. Actual local VIP ownership is checked before announcing it, avoiding announcements from the standby node.

The helper depends on the router and peer MAC addresses in inventory. Update these after replacing hardware or changing the relevant network interface. Five deliberate neighbor-cache clears recovered within three seconds. Graceful keepalived handovers in both directions subsequently completed in under one second. These verify neighbor recovery and controlled ingress handover; they are not physical power-off tests. The API service-stop test below also passed.

### Controlled API service-stop verification

With `k3s.service` stopped on `socrat-0` and its containers preserved, all of these checks passed while the service was confirmed inactive:

- The local API on `socrat-1` created and read a test ConfigMap.
- The Rancher pod on `socrat-1` returned `pong` from `/ping`.
- The VPS agent API load balancer at `127.0.0.1:6444` returned authenticated HTTP 200 for `/version`.
- The two surviving etcd voters on `socrat-1` and `socrat-2` were healthy.
- The ingress VIP automatically moved from `socrat-0` to `socrat-1`.
- The public Rancher domain returned `pong` from `/ping` when requested from the VPS.

The verification sequence took 8.18 seconds; this is not a measurement of the exact outage duration. `socrat-0` was restarted afterward and verified active. This was a controlled service-stop test with containers retained, not physical node power-off or whole-home failure.

### Final recovery and external verification

After restarting `socrat-0`, all three nodes were `Ready` and all three etcd voters healthy. CoreDNS, Traefik, Rancher, webhooks and cert-manager components retained two ready replicas. All 79 baseline pod UIDs were preserved, and an etcd snapshot named `homelab-ha-validated` was saved. With the VIP still on `socrat-1`, fifteen external rounds from the VPS returned all 45 complete HTTP 200 responses over approximately one minute: Rancher `/ping` (4 bytes), Rancher `/` (6,508 bytes), and status `/` (57,056 bytes). An authenticated Trojan TLS/WebSocket VPN probe also returned HTTPS 200. Transport health had zero failures, required units were verified enabled, and `socrat-1` had 48 GiB free. These checks confirm recovery and the tested external paths; they do not extend the physical-failure coverage above.

## Ansible source of truth

Run from `ansible/` with the appropriate reachable inventory overlay:

```bash
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/k3s-role-rebalance.yml --ask-become-pass
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/k3s-ha-dependencies.yml --ask-become-pass
ansible-playbook playbooks/home-ingress-ha.yml --ask-become-pass
ansible-playbook playbooks/rancher-placement.yml --ask-become-pass
```

`k3s-role-rebalance.yml` is the current role-reconciliation playbook. `k3s-ha.yml` is the original bootstrap migration and refuses to run once the external-quorum completion marker exists, preventing an accidental return to home-majority etcd. `k3s.yml` refuses the legacy topology while `k3s_ha_enabled` is true. Do not use a legacy worker installer to repair a promoted server.

All current nodes use `k3s.service`. The VPS watchdog fences both server and legacy agent units during native recovery and starts the configured primary server unit on manual failback. The `socrat-1` disk reserve policy targets the server service. Its MDB backup folder remains paused; over 40 GiB free was verified before migration after removing only seven redundant archives on that node.

## Recovery and backups

The pre-conversion archive on `socrat-0` is under `/var/backups/homelab-k3s/pre-ha-*`. It includes original server state (`server.tar`) and token/configuration material, is root-only, and must stay private. Preserve the server token with etcd snapshots for recovery of encrypted bootstrap data. Never commit these artifacts or print their contents.

SQLite rollback applies only before other etcd members join. Once this is a three-member etcd cluster, removing `cluster-init` or restoring old SQLite files is not a safe rollback. Datastore incidents require coordinated etcd snapshot recovery with the matching token and explicit handling of all members. Do not reset a member into a competing cluster or delete live server data as a repair shortcut. Verify membership, snapshot integrity and surviving quorum before selecting a procedure.

## Availability limits

- One failed voter is tolerated; two are not. Keep two voters healthy during maintenance.
- Native VPN failover stops the VPS etcd voter. Two healthy home voters retain quorum; a simultaneous home-node failure loses quorum. Native VPN can still serve independently. See [VPN failover](vpn-failover.md).
- Router, home WAN and shared power remain common dependencies. The VIP covers a home node failure, not a site failure.
- NFS at `/srv/k8s-nfs` remains on `socrat-0`; dependent applications are not made highly available.
- The public VPS SSH relay still depends on `socrat-0`; retain direct VPS SSH.
- Uptime Kuma remains one active VPS instance with local SQLite. No multi-site status replication or DNS failover is added.
- No whole-home shutdown, WAN isolation or real VPN failover was tested in this migration.

### Essential service configuration persistence

The `k3s_ha_dependencies` role stores cert-manager replica, placement and rolling-update settings in its existing Helm release, using the same chart version and preserving other release values. Rancher webhook settings use the supported `cattle-system/rancher-config` configuration key. Re-run this role after installing or upgrading these charts.

CoreDNS is managed through `homelab-coredns-ha.yaml` on both home servers. Its complete existing Deployment specification is preserved, with two replicas and home-node placement added. `coredns.yaml.skip` prevents K3s from reapplying its packaged singleton manifest on restart. The etcd-only VPS does not write packaged component manifests. Skipping the packaged manifest also means CoreDNS image, RBAC, Service and ConfigMap upgrades require deliberate review and application; upgrading K3s alone no longer upgrades these resources. Do not use `--disable=coredns`, which would uninstall the DNS resources. To return to the packaged configuration, first transfer management deliberately, then remove the custom manifest and skip files; this is not an automatic rollback operation.
