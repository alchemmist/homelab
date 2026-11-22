#1↔5 follow-up: NAT-only5, plain UDP controls and LAN relay A/B

## Addressing correction — owner clarification

**socrat-5 has no publicly reachable API/listener/address. It is reached through
WireGuard.** The sampled94.29.124.139 is an Internet NAT EGRESS address, not an IP
assigned to the guest or proof that arbitrary new inbound connections work. Do not
propose a public server on5 or confuse return UDP on an outbound-created NAT flow
with public inbound reachability. Guest ens18 is172.18.84.112; WG10.250.0.41.

All tests below used existing outbound5 flows, existing home WAN ports, existing
host SSH access, existing WireGuard addresses, and fixed local diagnostic forwarding.
No public5port, router rule, production tunnel or mesh identity was changed.

## New controls beyond the earlier encrypted-packet capture

[Earlier localization](../incidents/wireguard-1-5-packet-loss-20261116.md) already found real
loss before node1 WG decryption. Follow-up used existing approved cluster sudo
credentials through Ansible, preserving the existing pinned host keys. No sudo
policy change, permanent NOPASSWD, personal key copy or new privileged workload.
Only named /run diagnostic code/results were written; those files are now removed.

### Plain UDP in exactly the current5→1 tuple

Forty IPv4 UDP test packets had the same guest source172.18.84.112:51830,
destination109.173.40.247:51831 and UDP length136 as the simultaneous tiny WG
probe packets. IPv4 UDP checksum was computed and asserted correct; payload was
our fixed HNETTEST tag/sequence/zero fill, NOT authenticated WireGuard or real
application data. The target WG kernel naturally discards these tagged messages;
passive capture counts their arrival before that discard. No authentication/key
was guessed, no handshake or peer endpoint was changed.

-5TX40 synthetic UDP, node1 wlan RX28: **30% loss**.
-Simultaneous WG echo requests40, replies28: **30% loss**.
-Header-capture socket drops0 on both hosts.

Thus WG cryptography/inner application/TCP/VXLAN cannot be the sole cause. This
also reproduces the older HA runbook's raw UDP failure class. It does not rule out
an upstream device classifying or rate-limiting the whole existing UDP flow.

### Direct home forwarding versus wired0→LAN1: complete100packet A/B

Same5source port, alternating checked128byte diagnostic payloads,10pairs/sec:

A)5→home publicUDP51831→router forwarding→Wi-Fi1UDP51830.
B)5→home publicUDP51830→wired0UDP51830→a fixed LAN relay→Wi-Fi1UDP51830.

The temporary relay was a30second raw UDP receiver on0; it did NOT bind a new
public port, change the real WG socket, or forward arbitrary traffic. It only
accepted the exact128byte HNETVIA0 test tag, bounded sequences1..100, and sent
that same synthetic payload to the ONE fixed192.168.0.24:51830 destination.
No native WG traffic was rerouted, decrypted or proxied. Node1 recorded only
known test tag/header/sequence, not other UDP payloads.

| Stage | Sent | Received |
|---|---:|---:|
| Direct5→WAN51831→1 |100|82|
|5→WAN51830→wired0 |100|100|
| Wired0 fixed LAN relay→Wi-Fi1 |100|100|

Complete coverage was verified. An earlier shorter run clipped the final2–3
sequences at capture end and is NOT reported as a full40packet comparison; its
common covered window was consistent. The second run above is authoritative.

This materially narrows the failure: general5egress and a generally unusable
Wi-Fi radio are not sufficient explanations. The distinguishing path is direct
home WAN UDP51831 forwarding toward the Wi-Fi node, versus WAN51830 to the wired
node followed by normal LAN forwarding. **It still does not logically distinguish
port/flow-specific provider behavior from router NAT/hardware-forwarding/AP bugs.**
A router WAN/LAN capture or controlled wired1A/B is needed for that final step.
Do not label hardware NAT a proven root cause just because it is a plausible fit.

### Additional bounded observations

-Node1/0 keepalived active. Router/peer neighbor entries on1, peer1 on0 reachable
 with expected MACs. Directed ARP announcements present; no wrong192.168.0.24MAC
 observed in the short captures. Not a full exclusion of intermittent ARP faults.
-Three-end native capture repeated40WG probes,31replies. No missing datagram was
 observed as misdelivered to0, BUT node0 AF_PACKET sockets had capture drops; this
 does NOT conclusively exclude misdelivery. Node1/5 captures had no capture drops.
-Node5 opened outbound home0 TCP2222 three times; valid SSH banner each time,
0.023/0.031/0.029sec. No credentials/auth attempts were sent. This verifies TCP
 reachability, not authenticated tunnel establishment or sustained throughput.
-Node1 high WG/Flannel MTUs are still a separate configuration problem, not a
 demonstrated explanation for small raw UDP loss. No live MTU/K3s/Wi-Fi changes.
-NetBird1is not a permitted working alternative from5 in the current kernel peer
 map (Required key not available). No policy/AllowedIPs expansion was attempted;
 do not interpret it as permission to turn NetBird into a blanket inter-node route.

## How to fix without any public inbound5 access

### Native path repair — still requires router-side access/physical A/B

Read router firmware/forwarding/fast-path/UDP-protection state and counters first.
Synchronously compare known test sequences on router WAN receive and LAN/WLAN
transmit:

-Already missing at WAN RX: investigate upstream port/flow-specific filtering/NAT.
-WAN RX complete, router LAN/WLAN TX incomplete: router forwarding/acceleration
 is implicated; a guarded software-NAT/offload A/B may establish and remedy it.
-LAN/WLAN TX complete, node1 RX incomplete: AP/radio/driver path needs diagnosis.
-A controlled Ethernet1A/B can bypass WAN→Wi-Fi fast-path behavior, but preserve
 DHCP/MAC reservation, ingress VIP and HA rollback; no casual router/node reboot.

No current router admin credential/session was located in the known private
homelab stores. Do not guess defaults or use an unauthenticated management exploit.
Ask owner for a private credentials-file/session path, not a password in chat.
Without that access, exact router firmware/hardware cause remains unproven.

### Concrete transport workaround candidate — proposal, NOT deployed

The fixed LAN route through0 has passed the UDP control above. A production-grade
way to use it WITHOUT a new public5service, new public port, or mesh key/AllowedIPs
changes:

1.5initiates an outbound authenticated SSH connection to EXISTING home0 TCP2222.
2.Use a dedicated transport credential/user, pinned0host key, no shell/PTY/agent/
  X11/sudo, and permit ONLY a specific0loopback forwarding destination. Never copy
  the operator's personal private SSH key onto5.
3.A localhost-only UDP-over-stream client on5 carries ONLY peer1 WireGuard UDP
  through that SSH local forward. On0, a localhost-only fixed-destination relay
  forwards ciphertext to192.168.0.24:51830 and returns replies through the stream.
4.Only5's peer1 endpoint changes to its local loopback bridge. Original WG keys,
  node addresses, peer AllowedIPs, application TLS/SSO, and other peer paths stay.
  Original5↔1end-to-end WG ciphertext is forwarded unchanged;0does not terminate
  that cryptographic peer relationship. No general-purpose UDP/SOCKS proxy.
5.Health checks, supervised boot ordering, bounded buffers, fixed destinations,
  rollback and authenticated real WG/Pod bulk/render/UI canaries are REQUIRED.

Trade-offs: this introduces an EXPLICIT0dependency for1↔5 and TCP head-of-line
blocking/extra encapsulation. It does not repair the router fault or improve HA
independence. Do not silently retarget the existing general public51831forward to0
because that would change all clients'1reachability and home HA behavior. Preserve
existing authenticated1↔2TLS relay and guard, do not repurpose its pinned target.

These controls demonstrate a candidate data path, NOT an accepted production
WireGuard-over-SSH implementation. Deployment and any router setting change need a
separate explicit operational decision. No application migration was retried here.

## Evidence and cleanup

Mode0700/0600 private results remain under
~/Library/Application Support/homelab/vm105-network-20261116:
 native4-* (same-flow plaintext comparison),path-ab2-* (full100packet A/B),
 native3-* (three-end capture with node0 capture-loss caveat).
Only parsed headers and our test sequences retained; no user payload/keys printed.
All exact owned /run helper/result files on0/1 removed after fetching receipts;
short-lived capture/relay processes exited normally. Ansible's initial cleanup
call exceeded the controller deadline; an idempotent repeat verified all6named
paths absent on both hosts. No public listeners, services, firewall/route changes,
new credentials or policy grants remain. Unrelated concurrent Venice API/monitoring
work was not modified or accepted as part of this network investigation.
