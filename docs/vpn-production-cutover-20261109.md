# Production VPN cutover — 2026-11-09

## Accepted production boundary

`vpn.alchemmist.xyz` and native 3x-ui Hosts now advertise **Moscow91.189.82.238**;
VPN termination/accounting remain on **Netherlands109.120.141.60**. Existing
subscription URLs, identities, keys, SNI, transport settings and disabled bindings
are preserved. Owner explicitly authorized production cutover; no new approval or
console fingerprint confirmation is required.

Native Hosts API changed **7 groups/7 rows**, with preimage/CAS/readback for each:
**17 identities/91 bindings preserved**. Temporary machine API tokens removed.
No production SQL writes, panel/core restart, credential rotation or second panel.
Current native online SQLite backup:409600B,
SHA256`4097da8dbb100f50b9cb30d220aee13a59cdf3e4cf74726747cdddea69ba1ec7`;
quick_check=ok,17/91, legacy32063 still disabled. Original16/85 plus the legitimate
external addition are retained, not attributed to this operation or deleted.

All three authoritative writers (HOME0/HOME1/NL2) now have **only**
`vpn IN A 91.189.82.238`, independent of their old ingress-health failover list.
Native four-health-state renderer comparison accepted **no other record changes**.
NS1 HOME109.173.40.247 and NS2 NL109.120.141.60/glue untouched, TTL60; no registrar
resubmission/cache flushing/Mac DNS override.

All17 enabled subscriptions checked: **84 URI/77 JSON entries**. Backend and
strict-TLS public output agree, old NL literal absent/new Moscow present. Repeated
using **normal DNS**, not only pinned connections. No private links/keys emitted.

## Functional acceptance, not just source or readiness

After DNS/Hosts switch and again **after raw-WAN fencing**, an owned expiring
fixture from real HOME WAN109.173.40.247 passed all five transports:

- Yahoo REALITY/XHTTP32053;
- Sony REALITY/XHTTP32083;
- AMD REALITY/gRPC32084;
- Trojan WebSocket/TLS443;
- WireGuard UDP32085.

Each returned HTTP200,65536B,
SHA256`34dd6758c2908cf5be0e411173f61877f8faf2dcdcfed135b5a5fa90577447bc`;
separate HTTPS through each tunnel returned exit **109.120.141.60**. Fixture/client
bindings and native API tokens removed; original configuration/token rows checked.
No human identity, global SOCKS/proxy, Mac routes/DNS or client-key replacement.

Exact live Xray26.10.21 forwarding binary (SHAa27e3f95…14883e), actual encrypted
Moscow↔NL link, private bounded echo and isolated loopback child: exact **UDP32,
1200,1420,1472,8192B round trips** passed with **default** socket settings.
A custom-fragmentation diagnostic also passed but was **not adopted**: no MTU,
PMTU/sysctl or active proxy change needed. Echo/listeners/children cleaned; no new
public test port or production-proxy restart. This is real cross-host UDP/MTU proof,
not the earlier same-host loopback result or an authenticated AmneziaWG session.

## HOME traffic also moved

- HOME0/HOME3 NL management peer:91.189.82.238:51832 → NL51830, existing end-to-end
  WireGuard keys/AllowedIPs retained, no interface restart. NL peer audit sees
  Moscow91.189.82.238, not HOME public IP, for these two peers.
- HOME1 GOST TLS transport:91.189.82.238:51840 → NL51840. Pinned certificate,
  `wg-transport.socrat.internal`, auth secret and local WG endpoint unchanged.
  Only HOME1 leaf GOST service restarted; active old NL TCP session absent.
- HOME0 initially roamed back to a previously learned192.168.0.1:51830 alias.
  Preserved its uncertain receipt, inspected kernel/disk/other peers and NL-side
  endpoint, then added a **narrow HOME0 old-NL/gateway51830 tuple fence**. Only NL
  used that exact old alias. Fresh ping and NL-side source confirmed Moscow.
  No router/Mac/global firewall changes, no speculation about physical cause.
- New owned HOME nft table covers host OUTPUT and forwarded PREROUTING for exact
  NL destination109.120.141.60: TCP80/443/32053/32083/32084/51840 and matching
  UDP443/32085/32086, plus WG51830→Moscow51832. DNS TCP/UDP53 goes to **private
  Moscow10.250.0.40:53**, then over separate WG to **NL10.251.4.2:53**.
  DNS-only SNAT handles host/pod sources on the private hop. No default route or
  broad LAN/pod/service CIDR route was changed; existing tables were not flushed.
- On each of HOME0/1/3, requests explicitly addressed to **old NL IP** proved DNS
  UDP+TCP returning Moscow A, strict-TLS HTTPS and positive native DNAT counters.
  Exact persisted counter-independent table validation; startup failure retains a
  destination-only prohibit fence, successful validation removes only that fence.
  Proxy failure does not delete DNAT or switch covered services directly to NL.

Knot had only a public listener, so a private10.251.4.2:53 listener was added with
WG-address startup dependency. Initial reload diagnosed wrong temp-file group;
restored standard root:knot0640. Native conf-check passed. Knot explicitly requires
restart for listener changes: **one NL Knot service restart**, HOME DNS stayed up;
public listener/zone preserved. Do not repeat the original failed attempt. Source
host vars/template/dependency capture the accepted configuration.

## Ingress hardening and current staged last step

New NL owned WAN fence rejects raw TCP32053/32083/32084 and UDP32085/32086 on eth0,
without touching original backend guard, shared443, DNS or management. From Moscow,
direct-public raw TCP plus12096/32087 fail; private32053 and public443 TLS work.
Private/VPN data-path acceptance repeated afterwards. AmneziaWG32086 listener is
bound globally and forwarded privately, but authenticated AWG acceptance remains
explicitly unproven.

**Last shared443 hardening is staged through a canary first.** An HTTP ipAllowList
middleware permits only Moscow private10.251.4.1 for the Trojan path, not the whole
public HTTPS entrypoint. It uses the existing trusted CRD discovery bucket in
argocd (legacy label value `argocd`, explicit VPN ownership label); namespaces,
selector, RBAC and Deployment are unchanged. Canary mode keeps the original Trojan
route intact. Require direct-public403/private-allowed canary proof before setting
`vpnTransit.enforce=true`. Dynamic Ingress/Middleware only: no edge pod restart,
blanket sync/prune or unrelated auth changes. Until that final check is recorded,
old cached Trojan profiles can still use NL443; new subscriptions are Moscow-only.

## Cluster, custody and explicit limits

Native etcd3.6.14 check: **3 healthy voters/common leader/common revision17392485,
hashKV equal**; **5 Ready, no MemoryPressure**. Fresh Grafana/Thanos node_uname_info
covers all five original canonical instances (HOME0/1 LAN instances preserved).
No etcd reset/health-check disabling, WAL/history manipulation, collector queue/
fsync changes, UPower changes, alert masking or historical failed-Job deletion.

Private controller evidence root:
`~/Library/Application Support/homelab/socrat4-transit-20261109/`.
Final native policy/keys/preimages/panel backup/receipts from **all five** nodes were
fetched into `production-evidence/` and independently source-SHA verified; folders
0700/files0600, not Git. `off-host-verified.json` is the manifest. Original recovery
24-file manifest and prior stage backups remain separate and unchanged.

Limits: fixed-HOME proof is **not mobile/Happ interactive acceptance**; no promise
against blocking/TSPU attribution, site HA, full chaos/reboot or isolated DR restore.
This is not a global HOME exit node: only enumerated relevant NL services and mesh
were moved. STUN/TURN/NetBird relay semantics/other unreviewed ports and Mac are not
silently reconfigured or claimed as migrated. HOME3 native conntrack showed no
active direct NL entries; HOME0/1 lacked conntrack CLI, so no full-conntrack claim.
L4 forwarding changes server-observed source IP to the relay; original per-client
keys/quotas/bindings survive, **original end-user IP enforcement is not proved**.
Clients must refresh their existing Happ subscription; no new account/URL needed.
