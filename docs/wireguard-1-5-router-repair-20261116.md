# socrat-1 ↔ socrat-5: router investigation and fixed encrypted relay

## Scope and evidence

Router admin inspection was owner-authorized. Rotek RX-23302 Rev1.0sp2,
V1.24.154 (2024-11-27); WAN2 DHCP/NAT. Existing WG forwards are correct and
DoS protection is disabled. The authenticated admin UI does not offer a usable
packet-capture/offload control; diagnostic form returns404, and LAN22/23 do
not respond. Hidden superuser-only Telnet controls were NOT enabled. No
firmware flash, reset, router reboot, ACL widening or tunnel restart was done.

A complete private vendor config backup was saved outside Git,5169 bytes,
SHA256 `77408c7d0c9afe9c6aa114e42f9d8abe934d7bfe39816a1ff78298f75c66c590`.
Credentials/session/downloads live in a0700 controller directory, files0600:
`~/Library/Application Support/homelab/router-network-20261116/`.

Two reversible native-path experiments failed and were fully reverted:

*5GHz aggregation disabled: confirmed readback,50/34 ICMP (32% loss).
  Aggregation restored to `enable`, confirmed fresh readback.
* Source-restricted WAN2 UDP51835→Wi-Fi1 UDP51835, plaintext128-byte checked
  UDP payload from the same5 source51830:100 sent,63 echo replies (37% loss).
  This removes external/internal port translation and the51831 port as necessary
  conditions, but is NOT router WAN/LAN packet capture. Echo is round-trip loss;
  server-side count is retained privately. The firmware rejects a second forward
  to the existing backend51830 as overlapping; the rejected attempt changed no
  rules. The distinct51835 rule was removed afterwards. All10 original rows
  were verified canonically unchanged; temporary echo process and files exited
  and were removed. No real WG endpoint changed during this plaintext test.

Existing direct WG remained32.5% loss after adding the diagnostic rule, so
merely reapplying forwarding did not fix it. See earlier packet-loss/NAT docs
for same-flow plaintext evidence and the lossless wired0→LAN1 controls.
**Exact firmware, hardware-NAT/AP or upstream fault remains unproved.**

## Verified mitigation, not a claim to have repaired router firmware

The fixed relay runs on0 and carries only unchanged end-to-end WG1↔5
ciphertext.5 reaches it through its already-authenticated healthy WG peer0.
No public listener/address is needed on5, and no public router port is added.

```
5 WG peer1 endpoint =10.250.0.1:51835
  encrypted again inside existing5↔0 WireGuard
0 DynamicUser UDP10.250.0.1:51835, accepts ONLY10.250.0.41:51830
  fixed socket192.168.0.23:51836 →192.168.0.24:51830
1 unchanged native WG listener/identity
```

Replies use the same fixed sockets. Relay0 cannot decrypt the inner WG1↔5
traffic and has no keys or auth secrets. No arbitrary destination, public bind,
AllowedIPs expansion, copied operator key, TCP wrapping or new public5 endpoint.
Native1↔2 GOST/TLS and all other endpoints remain unchanged.

**Tradeoffs:** this link now explicitly depends on0; this is not an HA
replacement. Additional WG encapsulation can fragment outer IPv4 datagrams;
large host/Pod tests below demonstrate the tested sizes, not all imaginable
UDP/PMTU cases. Existing jumbo MTU on1 is still a separate defect, not silently
normalized here. There is no TCP head-of-line penalty because relay uses UDP.

## Acceptance before persistent activation

Both bounded canaries automatically restored the direct endpoint afterwards.

*5→1 WG ICMP56-byte payload60/60, DF1172 payload20/20, DF1392 payload20/20.
* Simultaneous1→5 WG small ICMP40/40, no loss.
* Real Pod IP transfers with native Flannel, not host-only shortcuts:
  * client1 downloading8MiB from server5:2.631/2.851/2.748s,
    25.50/23.54/24.42Mbps;
  * client5 downloading8MiB from server1:3.034/2.899/2.895s,
    22.12/23.15/23.18Mbps.
* All six8MiB SHA256 checks matched. VM shaping cap remains30Mbps.
* Four named temporary Pods and their exact isolation NetworkPolicy were
  deleted gracefully. No production Pod was deleted and no app moved.

These results justify transport activation, not renderer/LiteLLM migration
acceptance. Final placement remains renderer1/LiteLLM0/LMS5; other accepted
apps, original data and scoped IdP aliases stay unchanged. DR/cold-boot/full
VM restore acceptance remains separate and outstanding.

## Owning source and narrow activation

* `scripts/wg-peer15-relay.py`: fixed destinations, payload never logged/stored.
* `ansible/files/wg-peer15-relay.service`: DynamicUser, no capabilities,
  no-new-privileges, read-only system/home, source/destination cgroup IP filter,
 32MiB memory bound, supervised restart and stable LAN51836 source socket.
* `ansible/playbooks/wg-peer15-relay.yml`: install only0 relay; never restart WG,
  network/K3s or apps. Stops only owned bounded canary units first.
* `ansible/inventory/group_vars/Socrat.yml`: ONLY5's peer1 endpoint changes to
  `10.250.0.1:51835`; the established0 endpoint is preserved.
* `scripts/wg-peer15-endpoint.py apply|rollback`: root-only narrow update on5,
  preserves every other config byte, verifies node identity/known endpoints,
  backs up private original config0700/0600, fsync+atomic writes, updates only
  the selected runtime peer and warms authenticated path. No full wg-quick
  restart or wholesale template application.
* `tests/test_wg_peer15_relay.py`: endpoint preservation/idempotence/fail-closed
  preimages and sandbox/fixed-destination checks.

Activation order: deploy/check0 relay, install endpoint helper on5 as a
root-owned0755 file at `/usr/local/libexec/homelab-wg-peer15-endpoint.py`, then
run `python3 /usr/local/libexec/homelab-wg-peer15-endpoint.py apply` on5 through
the existing SSH jump0. Do not expose private config or run blanket Ansible.
Controller become credentials remain in their existing private file.

## Health, restart acceptance and rollback

Persistent activation/restart observations are recorded below after deployment.
Check `systemctl is-active homelab-wg-peer15-relay`, journal counter-only logs,
peer1 endpoint on5 and the existing bidirectional loss/bulk canaries. Dynamic
WG endpoint learning means checking config alone is insufficient.

Rollback MUST start on5 while relay0 is still running:

```
python3 /usr/local/libexec/homelab-wg-peer15-endpoint.py rollback
# verify5 peer1 runtime/direct path has rewarmed, then on0:
systemctl disable --now homelab-wg-peer15-relay.service
```

Also revert ONLY the owned5→1 endpoint inventory entry to
`109.173.40.247:51831`. Keep keys, addresses, AllowedIPs and the1↔2 transport.
Do not restore an entire stale WG config over independent changes. Rollback
returns to the documented lossy direct path, not a previously healthy service.
