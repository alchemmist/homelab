# Direct WireGuard1↔5: confirmed underlay loss,16Nov2026

## Result and operational boundary

The immediate cause of slow multi-MB UI assets and renderer deadlines is real
packet loss on the **direct WAN UDP path toward socrat-1**, not merely a failing
application or Kubernetes readiness. Loss reproduces with small ICMP over the
hosts' WireGuard addresses, without VXLAN, Services, HTTP, OIDC or database traffic.
A matched two-endpoint capture locates lost encrypted datagrams between node5's
ens18 transmit capture and node1's wlan0 receive capture, BEFORE node1's WireGuard
decryption. This is underlay/NAT/radio-path localization, NOT proof of a specific
router firmware defect, provider policy, hypervisor queue or Wi-Fi chipset bug.

No repair to that physical/WAN fault was performed. No application was migrated
again: LMS stays5, LiteLLM0, renderer1, Rancher1. No routes, keys, AllowedIPs,
interface MTUs, firewall rules, router mappings, Wi-Fi settings or NetBird policies
changed. The single short-lived diagnostic Pod has been deleted.

## Actual topology: same mesh does not mean same transport

- socrat-0 WG10.250.0.1; LAN192.168.0.23; public home UDP51830.
- socrat-1 WG10.250.0.3, NOT10.250.0.11; Arch7.2.9 laptop, wlan0 LAN192.168.0.24.
  It is not an OpenVZ container. Public home UDP51831 forwards to its UDP51830.
- socrat-5 WG10.250.0.41; native VM105 ens18 LAN172.18.84.112;
  sampled public egress94.29.124.139; WG interface1420/Flannel1370.
-5's peer1 endpoint is109.173.40.247:51831, i.e. DIRECT home WAN UDP, not a
  relay through0/2/3. Home port-forward SNAT is visible as192.168.0.1 on node1's
  wlan0. The dynamic source port is observation-only, not a value to pin.
-5's peer0 uses the same home public IP but UDP51830; this path tested cleanly.
- Each peer has its own authenticated key/AllowedIPs and endpoint. WireGuard does
  not automatically route a bad direct1↔5 link through0 or through another peer's
  working TLS relay. Flannel adds VXLAN on top of the chosen host mesh route.

## Bounded measurements

40packets,0.2second interval,1200byte payload, concurrently sampled:

| Path | Loss |
|---|---:|
|1→5 WireGuard |32.5%|
|1→0 WireGuard |0%|
|1→0 LAN192.168.0.23 |0%|
|1→home router192.168.0.1 |0%|

Other completed samples:5→1 with56byte payload50%, with1200bytes35%; later
56byte30packet samples16.7% and20%.0→5 small40packet control0%. Results vary;
do not turn these short samples into long-term SLO/failure-rate claims.

At a later20% loss sample, node5 guest NIC RX0.131Mbps/TX0.280Mbps, no new guest
RX/TX drops. This is far below its30Mbps cap: cap saturation does not explain that
sample. Guest counters alone do not prove hypervisor/router queues are flawless.

Earlier application bulk control, same229044byte JS object: Pod0→Pod5
0.072/0.150sec vs Pod1→Pod5 5.753/15.345sec. Small API200 and one successful
PNG did not demonstrate bulk-path stability; returning two apps was justified.

Wi-Fi read-only snapshot: signal-39dBm, VHT80MHz780/866.7Mbps RX/TX, power save
OFF, no interface error/drop increments indicated by snapshot. A strong signal
and clean LAN ping do NOT by themselves clear AP forwarding/WAN UDP behavior.

### Matched packet capture, no application payload retained

Short-lived node1 hostNetwork diagnostic Pod, existing LMS image and existing
registry pull credential, no service-account token, no volumes/host filesystem,
read-only container root, drop ALL capabilities except NET_RAW. It only parsed
IPv4/ICMP headers and the PUBLIC encrypted WireGuard transport header's receiver
index/counter, restricted UDP data length136bytes to identify tiny probe traffic.
No private key or credential files were read. No TLS/application/user payload
was decoded, persisted or printed; only the listed header fields were retained.
Node5 used existing root access for the same bounded passive capture and ping.

Successful paired sample:

-5transmitted20echo requests and matching20encrypted UDP datagrams toward1.
-1received17of those exact encrypted receiver-index/counter tuples on wlan0;
  the SAME3missing packets corresponded to missing ICMP sequences1,7,17.
-1decrypted all17received requests and produced17echo replies.
-In the overlapping reverse encrypted-counter window,20node1datagrams were
  captured and all20arrived at5. Not all were echo replies: equal encrypted
  lengths can also contain other traffic. Compare counters, not packet length alone.
-Both packet sockets reported ZERO capture drops. Therefore these missing forward
  datagrams did not disappear inside the application, Flannel, or after WG
  decryption on1. Capture TX is before actual wire transmission; localization still
  includes VM/hypervisor egress, Internet/NAT/router and AP/Wi-Fi reception.

Private0700/0600 evidence and probe manifest/scripts:
~/Library/Application Support/homelab/vm105-network-20261116.
Two preliminary capture attempts were NOT used as the complete paired result:
first lacked a registry pull reference; another remote stdout collection timed
out. Header-only136byte filtering produced the complete bounded result above.

## This fault class was already known, and only one peer pair was covered

[Existing HA runbook](k3s-ha.md#home-laptop-to-vps-transport) already records
40–100% loss on direct1↔VPS WAN UDP, healthy0↔VPS/local LAN, ineffective MTU,
offload/port/2.4GHz experiments, and a successful TCP transfer control. It explicitly
states the underlying router/Wi-Fi fault was NOT repaired.

The existing authenticated, destination-pinned GOST TCP/TLS transport covers
**1↔2 ONLY**: peer2 on1 points to127.0.0.1:51840. It does not transparently protect
peer5. Preserve its guard/health timer/TLS authentication; do not revert it to
faulty direct UDP or repurpose its pinned relay destination for5.

Separate configuration defect: node1 WG MTU65456, Flannel/cni/veth65406 despite
physical wlan0MTU1500. Installed wg-quick auto-selection subtracts80from an endpoint
route interface MTU; loopback65536 and the local TLS relay are a plausible origin
of65456. Startup provenance was not captured; do not assert it proven. Normalize
this deliberately later, accounting for live Pod interfaces, not by silently
restarting WireGuard/K3s or relying on a config sync to resize existing veths.
This cannot alone explain losses of56byte probes. Previous MSS1240 experiment
also did not improve the symptom and was completely removed.

## Next decision, not an unapproved live change

1. Keep the current application recoveries and mesh identities intact.
2. Physical diagnosis: controlled Ethernet-vs-Wi-Fi A/B on1 and/or synchronized
   router WAN/LAN capture to narrow the missing datagrams further. Account for
   physical access, DHCP/MAC reservations, ingress VIP, HA and rollback before any
   interface/router intervention. Do not casually reboot home router or whole node.
3. Reliability workaround if that repair cannot be immediate: a separately scoped,
   authenticated, fixed-destination TCP/TLS transport for1↔5, following existing
  1↔2 design but with explicit reachability/relay/port approval, no arbitrary UDP
   proxy or dependency cycles. TCP-over-TCP HOL and independent boot/DR need review.
4. Review explicit, consistent WG/Flannel MTUs separately. Do not open NetBird ACLs
   or widen mesh AllowedIPs just to route around this fault.
5. Before any renewed moves, repeat raw host and Pod bulk tests in both directions,
   sustained loss/retransmit measurements and actual native UI/renderer checks.
