# Mac → SSH management

## Current owner policy — 2026-11-10

Public SSH is primary for ordinary aliases when a public entry exists. This
supersedes the internal-only alias policy in the historical sections below.

| Alias | Destination | SSH jump |
|---|---|---|
| socrat-0 / socrat-master | 109.173.40.247:2222 | none |
| socrat-1 | 109.173.40.247:2223 (existing router forwarding) | none |
| socrat-2 | 109.120.141.60:2222 | none |
| socrat-4 | 91.189.82.238:2222 | none |
| socrat-3 | 10.250.0.5:2222 | none (NetBird) |
| socrat-5 | 10.250.0.41:2222 | none (NetBird) |

All six ordinary aliases were authenticated and returned the expected hostname
and alchemmist user. Existing host-key pins and strict checking retained.
No Mac routes, DNS, VPN configuration or server services were changed. Public
entries do not require the inter-node WG/Kubernetes path; private workers still
depend on NetBird and its network path, not an SSH jump host. Port22 on the current NL IP
remains an explicitly named alternative, not the retired .97 address.

## Historical internal-access setup


> **Current primary client: NetBird**, alongside Tunnelblick, verified 2026-11-06.
> See [NetBird/Tunnelblick coexistence](netbird-tunnelblick-coexistence.md).
> The standalone WireGuard configuration below is the preserved recovery path,
> not the currently active Mac transport. Do not turn it on over the same routes
> and mistake its successful SSH for NetBird acceptance.

The ordinary `socrat-0/1/2/3` aliases must use `10.250.0.1/3/2/5:2222`,
respectively, with `ProxyJump none`, retained pinned host keys and strict checking.
Public SSH or a bastion is a recovery path, **not** a substitute for internal access.
Check effective configuration with `ssh -G`, including duplicate later `Host` blocks.

## WireGuard routing

The Mac's `wg-socrat-admin` has address `10.250.0.4/32` and three direct peers:

| Peer | Allowed host routes |
|---|---|
| socrat-0 | `10.250.0.1/32`, **`10.250.0.5/32`** |
| socrat-1 | `10.250.0.3/32` |
| socrat-2 | `10.250.0.2/32` |

The non-public worker is reached by ordinary encrypted IP forwarding inside the
existing WireGuard mesh via socrat-0. There is **no SSH jump/proxy**, public SSH
connection, additional worker port-forward or default-route capture. Public UDP
endpoints of WireGuard peers are transport underlay, not SSH destinations.

- `wireguard_admin_client` owns the generated Mac profile. `peer.allowed_ips`
  permits explicit registered mesh `/32` routes; other peers retain their own `/32`.
- socrat-0's administrative firewall permits only Mac → worker TCP/2222 plus
  established return traffic. The Mac rule sets `snat: false`, retaining source
  `10.250.0.4` for auditing. Existing forwarding rules retain SNAT by default.
- socrat-3 routes `10.250.0.4/32` back through its socrat-0 peer via
  `wg_socrat_extra_allowed_peer_ips`. Do not also assign that address to a direct
  Mac peer: duplicate AllowedIPs steal the return route. Its desired direct admin
  registry remains empty.

## Applied repair, 2026-11-05

The active imported Mac profile still had the VPS's previous endpoint and no
worker route even though the generated file had the new endpoint. The unrelated
full-tunnel VPN therefore captured `10.250.0.5`.

Updated **both** generated and imported profiles, preserving the private key and
all peer identities. Applied the narrow forwarding rule through the existing
firewall role. Corrected persistent and runtime worker peer routes, removing only
its stale direct Mac peer, **without bouncing the node WireGuard interface**.
The existing active peer endpoint was retained. No node, k3s, database or shared
telemetry pod restart was needed.

A one-off helper initially ran under the remote shell instead of Python and
failed before touching worker state; it was rerun with explicit `/usr/bin/python3`.
An initial GUI AX text update did not activate the changed configuration; after
proper text-change notification and Save, actual host routes and tunnel delivery
were verified. Neither the first command nor a file edit alone was acceptance.

Private preimages: controller `/tmp/vps-ip-move-private/` (including original
imported profile), generated profile's adjacent `.before-private-route-fix`,
worker `/root/20261105-private-ssh-repair/`. They contain secrets; never commit or
print their contents. These are recovery preimages, not full server backups.

## Standalone WireGuard recovery acceptance after an edit

1. Inspect only Address/AllowedIPs/Endpoints in the **imported** profile; generated
   files do not update the imported app configuration. Keep keys unchanged.
2. Save/apply that profile; allow the short Mac tunnel reconnect. Do not restart
   node interfaces or unrelated VPNs. Do not copy credentials to the clipboard.
3. `route -n get 10.250.0.5` must select the same WireGuard tunnel as the other
   internal node addresses, not the unrelated full-tunnel VPN or public default.
4. Ordinary `ssh socrat-N` must succeed for all four aliases with no `-F`,
   `ProxyJump`, forced public HostName or alternate configuration.
5. Check server-side `SSH_CONNECTION`: source `10.250.0.4`, exact destination's
   internal address, server port 2222. This distinguishes actual direct internal
   SSH from a working bastion or source-masked workaround.
6. Verify new connections (not just multiplexed existing sessions), route/peer
   persistence, firewall least privilege and no broad CIDR/default/DNS capture.

Do not infer ping/HTTP permission to the worker from SSH acceptance: transit is
intentionally scoped to TCP/2222. NetBird is not used for this Mac path; its
connection state is not evidence of this WireGuard tunnel's health.

Repair verification: 12/12 fresh SSH sessions (three per node) using ordinary
aliases, with multiplexing disabled for the test, all showed source
`10.250.0.4`, the node's internal destination and port 2222. The owner Mac
`wireguard-admin-client.yml --tags prepare` then converged with **changed=0**;
private-key identity was compared with the preimage and remained unchanged.
Offline regression checks passed: 41 unittest cases plus 5 mesh routing/render
contracts. Tests used the preinstalled Ansible Python/Jinja environment after
network-dependent uv dependency resolution timed out. This is a focused check,
not a claim that the unrelated full repository suite passes.
