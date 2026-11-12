> **Later DNS update:** CoreDNS availability recovery at16:35UTC moved replicas
> from1/3 to0/3 and restored natural Alertmanager delivery. See
> [recovery and acceptance](alertmanager-dns-recovery-20261112.md). The earlier
> connectivity samples below are historical, not sustained health guarantees.

# Six-node network dependency audit — 12 November 2026

## Scope and evidence quality

Read-only collection from all six hosts using privileged, filtered WireGuard
queries (no keys), OS routes, bounded ICMP/TCP probes, selected file digests,
relay destination fields and service state. Raw filtered reports are private on
the controller under `/tmp/socrat-network-audit-20261112/`; this document is the
reviewable summary, not a promise that temporary files are durable artifacts.
No failure injection, routing change, firewall relaxation, service restart or
provider-console operation was performed in this audit.

Live sample at15:05–15:06UTC (health rechecked15:08UTC): all6Ready. All36 source/destination combinations
including self passed ICMP and SSH2222: **30 actual directed inter-node paths**.
Mesh handshakes to other nodes were fresh (seconds to roughly2minutes). These
are sequential bounded samples, not a sustained stability/HA acceptance.
A TCP6443 probe from5 to1 failed while5→0/2 and other sources→1 succeeded.
A listening TCP port is not authenticated API or data-plane health proof.

## 1. Separate the layers

1. **Underlay:** public/LAN/NAT routes carry the encrypted transport.
2. **Node mesh:** wg-socrat10.250.0.0/24 selects a destination peer through
   AllowedIPs. Some peer transports are forwarded through Moscow.
3. **Pod network:** Flannel10.42.0.0/16 depends on usable node paths; Ready alone
   does not prove every pod/service route works.
4. **Public ingress:** HOME, NL and Moscow can be entrypoints but still rely on
   routes to applications and state. DNS availability is a different layer.
5. **Management:** public SSH and NetBird; a secondary channel may depend on the
   same hosts/Kubernetes/provider path and is not automatically independent DR.

## 2. Node identities

| Node | Mesh IP | Site/role relevant to failure domains |
|---|---|---|
|0|10.250.0.1|HOME Ethernet,192.168.0.23; control-plane/etcd; HOME authority/VIP owner at sample|
|1|10.250.0.3|HOME Wi-Fi,192.168.0.24; control-plane/etcd; shared HOME WAN/router|
|2|10.250.0.2|NL109.120.141.60; etcd/server; public authority and application/VPN services|
|3|10.250.0.5|Worker, public-facing NAT endpoint46.8.146.172:46559 observed from peers|
|4|10.250.0.40|Moscow91.189.82.238; transit worker, local Knot and native management relay|
|5|10.250.0.41|NATed restricted LXC worker; learned public NAT endpoint; local n8n storage|

Do not equate identical RFC1918 subnet notation at different sites with one LAN.
Observed WireGuard public NAT endpoints can roam and are not permanent addresses.

## 3. Confirmed transport paths

| Pair | Effective transport/dependency |
|---|---|
|0↔1|Direct HOME LAN WG endpoints192.168.0.23/.24:51830|
|0↔2|Moscow management UDP relay, then inner WG carried inside Moscow↔NL WG|
|1↔2|Local GOST127.0.0.1:51840 → Moscow91.189.82.238:51840 → private NL10.250.0.2:51840 → local WG|
|3↔2|WG peer endpoint91.189.82.238:51832 (Moscow UDP relay) → private NL51830|
|4↔2|Direct WG public endpoint109.120.141.60:51830; live and fresh despite failed public TCP reconnects|
|5↔2|Direct WG public endpoint109.120.141.60:51830 at sample; no Moscow relay in that peer's transport|
|3↔0/1|WG to HOME109.173.40.247:51830/51831 at sample|
|5↔0/1|WG to HOME109.173.40.247:51830/51831 at sample|
|4↔0/1|WG to HOME WAN/learned NAT endpoint; separate from its NL management forwarding|
|3↔4/5,4↔5|Direct WG peers using public/learned NAT endpoints at sample|

NL's live WG endpoints corroborate forwarding: peers0/3 arrive from
10.250.0.40 with distinct source ports; peer1 arrives from loopback GOST.
Its peer5 arrives directly from the worker's learned public NAT endpoint.
On0, some runtime endpoints show its router192.168.0.1 rather than configured
public destinations; NAT/roaming observations must not be mistaken for an
independent route. No alternate routing is inferred just because every peer pings.

### The key common dependency

```text
0 ── UDP forwarding ─┐
1 ── TLS/GOST ───────┼── Moscow4 ── WG ── NL2
3 ── UDP forwarding ┘

5 ─────────────────── direct WG ── NL2
```

If4 or its NL transport fails, the configured0/1/3↔NL peer paths are at risk.
A working0↔5↔2 chain does **not** mean WireGuard automatically reroutes0→2 via5.
AllowedIPs/routing do not currently implement that alternate path.

## 4. Administration and real fallback limits

| Node | Tested management path | Limit |
|---|---|---|
|0|HOME WAN2222; native NetBird100.100.155.241|HOME router/power common domain|
|1|HOME WAN2223; native NetBird100.100.160.32|Same HOME domain|
|2|SSH through4→10.250.0.2:2222|Public22/2222 and native NB from Mac previously failed; provider console unverified now|
|3|Native NetBird100.100.7.160; Moscow→mesh2222|Ordinary mesh alias from Mac previously failed|
|4|Direct public91.189.82.238:2222|Working independent of its worker-agent state|
|5|Moscow→mesh2222|Native NetBird100.100.9.130 worked earlier but timed out during this audit|

No SSH trust weakening or workstation route/DNS/VPN changes were used. A failed
native NB connection is not evidence that the whole worker is down;5 had fresh
mesh/SSH connectivity from the other hosts. NetBird agents are host-network
Kubernetes pods and management runs on0, with relays on0/2: not an independent
out-of-band control plane. A fresh, verified provider console for NL remains the
highest-priority management gap; operator portal URL/session is required.

## 5. DNS and external entrypoints

Authoritative host Knot:0/1 via HOME VIP192.168.0.250,2 via NL publicIP,4 via
Moscow publicIP. Four writers, **three public addresses/failure domains**, not four
independent public authorities. Parent .xyz NS/glue for ns1/ns2/ns3 verified.
Moscow Knot serves a local disk zone without query-time NL/WG/Kubernetes
requirement. Its old private10.250.0.40:53→NL5354 relay is separate and retained.

All four deployed renderer hashes match source:
`54a37972c25245b0ef15e63ded45a95f2331ae69037c0bf202ac2f082774760b`.
HOME/NL web443 health selection is unchanged; each writer probes independently.
NS3 addition is NOT publication of Moscow as a third general web A address.
Only vpn retains its dedicated static Moscow A. Per-writer split-brain/cache and
single-vantage health limitations remain. NL→Moscow UDP53 timed out while TCP
passed in the prior phase; the cause is still unresolved.

Earlier forced-IP verified-TLS wiki/LMS tests gave HOME200/303, Moscow200/303,
NL timeout from Mac. These are dated samples, not exhaustive independent external
acceptance. Moscow's user relay forwards fixed ports80/443/etc to NL10.250.0.2;
therefore a third public Moscow web entry is not independent of NL by default.

## 6. Failure consequences — design assessment, not chaos-test results

| Failure | Expected consequence / unresolved condition |
|---|---|
|Single0 or1 host|Other2etcd voters can retain quorum if their transport works; shared HOME VIP/ingress behavior and data locality still matter|
|Whole HOME site/router|Loses0and1 together: only1of3etcd voters remains, no quorum; three public IPs do not fix it|
|NL2|Other0/1 can retain etcd quorum while HOME is healthy; NL backends and Moscow's forwarded web/VPN path affected|
|Moscow4|Authoritative DNS still has HOME/NL, but0/1/3↔NL transport is Moscow-dependent; etcd0/1 can still form HOME quorum|
|Worker3|Its workloads and n8n backup destination affected; not an etcd voter|
|Worker5|Its workloads/local n8n data unavailable; replacing a pod elsewhere does not migrate node-local storage|
|Moscow↔NL WG only|Common management/user relay substrate fails even if both machines and public DNS remain alive|
|One publicIP unreachable from some networks|NS retry may preserve name resolution; cached web A and independently disagreeing writers can still direct clients to the bad entry|

The existing system does not satisfy “any two survivors run Kubernetes”: etcd
needs2of3specific voters. “Any two internet-connected survivors retain node
connectivity” is a separate transport requirement and is not yet proven either.

## 7. What is now preserved in Git

- 08c4534: accepted incident WG/GOST bypass. Source management config exactly
matches live hash89d305e82ee44815a0880b06493555afc746805d5fee58fb34444d883a9d090b.
NL GOST listener0.0.0.0:51840 confirmed with TLS/auth/fixed loopback forwarder.
- c60b16d: new Moscow authority plus guarded exact NS3-only publication.
- 40ddc42: late-healthy native watchdog reconciliation, live source hash
3f130631c493cf60feed9cc5dd1ee970b233c278fb9cf685a00f32e915f03d19.

137tests+15subtests passed after correcting one obsolete test expectation of
public NL management destination. Both new Ansible playbooks pass syntax-check.
No push was performed. Native files require reviewed Ansible/update procedures;
committing does not itself reconcile them. Moscow mesh-runtime play is guarded
initial preparation and intentionally refuses existing configs: do not replay it.
Argo vpn-transit tracks charts/vpn-transit on main with auto self-heal/prune=false;
these commits do not edit that chart. Root/apps and CI still watch main, so a
future push must remain scoped/reviewed rather than assumed operationally inert.

## 8. Next gates

1. Confirm independently managed provider console for NL and practical recovery
   paths for workers, including intermittent native NetBird5.
2. Local etcd snapshot metadata was checked on0/1/2: each has a12November
   09:00UTC scheduled archive (~75MB), plus retained earlier archives. ZIP CRC,
   same-revision integrity, off-host custody and restore were NOT verified.
   Verify off-host copies and perform an isolated restore check; successful app backup jobs alone are insufficient. Latest
   observed n8n00:15:14UTC, LMS12:00:06UTC on12November; restore not tested here.
3. Investigate public NL reconnect and intermittent mesh/API failures with paired
   captures. Do not attribute to an ISP/blocker without packet evidence.
4. Agree a target transport with explicit independent paths and a failure matrix;
   reduce/replace single-Moscow dependency, not add an unexplained relay layer.
5. Only then define three-entry web health/publication and run controlled failures
   with independent management, bounded outage budgets and rollback.
