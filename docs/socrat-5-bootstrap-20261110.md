# socrat-5: isolated WireGuard bootstrap, 10 November 2026

Owner provided a NATed Debian13.6/x86_64 **LXC**, currently hostname testing-class,
172.18.85.108/23. Kernel WireGuard interface creation/removal succeeded locally;
SSH22 active, PermitRootLogin without-password, public-key auth enabled.
Owner-selected identity: **socrat-5**, reserved mesh **10.250.0.41/32**.
Not a Kubernetes member; no K3s installed/admitted by this work.

Public intent/key/independently supplied ED25519 fingerprint:
`deploy/network/socrat-5-bootstrap.json`. Private client key stays on the LXC.
Only Moscow91.189.82.238:51830 peer10.250.0.40 is initially allowed client-side.
No DNS override/default route/Mac route/NetBird policy changes.

Server preparation accepted:
- All five existing mesh peer allocations checked,41 unused. A separate inactive
  default-route WG config on node1 is not a41 allocation. No existing peer removed.
- Dedicated source-scoped mangle PREROUTING guard on Moscow **before DNAT** admits
  only ping to/from.40 and established SSH22 responses to gateway-origin connections.
  All other decrypted source.41 traffic drops, including transit/private-web/API/
  relay hairpin. IPv6 is not admitted by peer AllowedIPs. No forwarding grant.
- Guard validated, enabled native systemd service, required before WG on future
  boots. No flushing existing firewall chains/tables, no K3s restart.
- Persistent wg-socrat config appended one peer under SHA CAS, root-private
  preimage/runtime snapshot, then surgical `wg set ... peer ...` only. Original
  four peer AllowedIPs unchanged; WG service start timestamp still9November.
- Source preserved through dedicated `wg_socrat_bootstrap_peers` on socrat-4,
  separate from admin clients/nodes. Role requires matching isolation before
  rendering bootstrap peer. Admission script is **one-time**, not a replay/update.
- Final readback: new peer41, handshake0 (awaiting owner client start), route41 via
  wg-socrat source40; guard active/exact; Moscow production relay Kubernetes/healthy,
  native inactive/marker absent. This is NOT an end-to-end isolation/SSH proof.

First candidate validation failed before live writes because wg-quick requires a
valid <=15-character interface filename. Inspected unchanged persistent SHA and
runtime peers; archived rejected candidate root-private, corrected filename,
separate accepted receipt. No blind rerun of completed admission.
Earlier diagnostic failures: nft absent (used installed iptables), allowed-ip
parser corrected for space-separated entries; wrong playbook path failed before
execution. No production WG/VPN interruption introduced by those failures.

Private gateway receipts:
`/var/lib/homelab-recovery/20261110-socrat5-bootstrap/` (accepted),
`/var/lib/homelab-recovery/20261110-testing-class-bootstrap/` (original preimage /
rejected candidate). These contain secrets: never copy into Git/stdout.
4 source/template/guard tests passed using Ansible's Python (system Python lacks
Jinja2); shell syntax/Python compilation/diff-check passed.

Next: owner writes client config from existing key, adds agreed public SSH key
without replacing other authorized_keys, starts wg-quick. Then verify real
handshake, both ping directions, independently pinned SSH from gateway path and
negative transit/port cases. Do not weaken root SSH policy or copy private keys
onto gateway to obtain access. Hostname may be changed to socrat-5 after SSH.
LXC nested-container/cgroup/mount/CNI suitability for K3s is a separate unproven gate;
no automatic privileged-container expansion, K3s install or cluster membership.
The earlier session's accepted VPN runtime and deferred RF/NL split remain unchanged.
