# Public DNS alchemmist.xyz

Updated **12 November 2026** (ns3 and the parent delegation check; the old acceptances are dated below). The current network summary: [network-access.md](../README.md). This is the scheme and the results of the performed acceptances, not a continuous healthcheck and not an instruction to repeat a migration apply.

## Current state on 12 November

The NS3 NS/A are published on0/1/2/4; the REG.RU and parent .xyz delegation/glue
were verified. All6Ready after a separate fix of the Moscow watchdog.
The HOME/NL web A-selection was not changed: Moscow is not yet a third common web A.
NL→Moscow UDP53 previously timed out while TCP worked; the cause is not established.
[Dependency map and HA boundaries](../../records/handoffs/network-dependency-audit-20261112.md).

## Addresses and delegation

| Purpose | Current address |
|---|---|
| HOME / ns1.alchemmist.xyz | `109.173.40.247` |
| VPS / ns2.alchemmist.xyz | **`109.120.141.60`** |
| Moscow / ns3.alchemmist.xyz | `91.189.82.238` |

`109.120.141.97` is an intermediate old address, the migration to`.60` was completed separately.
`176.98.185.59` is the old VPS address used before 5 November. The old results of 1–2 November refer to it, not to the new IP. The migration updated the source/runtime and the REG.RU glue; the new address was verified at the parent. The provider gateway `176.98.185.1` is kept deliberately, do not replace it together with the old IP.

1. The resolver asks `.xyz` about the NS of `alchemmist.xyz`.
2. The parent returns `ns1`/`ns2`/`ns3` and the registrar glue to HOME/NL/Moscow; in the observed delegation the glue TTL is 3600s.
3. Via the glue, the authoritative Knot is queried. In-zone NS/A use a TTL of 60s. This is not a replacement for the parent glue: the bootstrap must not depend on a query to the very NS not yet found.

## VPN — a separate static Moscow entry

`vpn.alchemmist.xyz IN A 91.189.82.238`, TTL60, on all0/1/2 writers. Removed from
FAILOVER, placed in STATIC_A: on a Moscow failure, do not publish NL/HOME as a
hidden fallback. The other records were verified across all four health-combinations;
NS1 HOME and the accepted NS2/glue NL were not changed, the registrar was not resent.
The NL authoritative Knot additionally listens on private10.250.0.2:5354; the Moscow
private relay10.250.0.40:53 forwards TCP/UDP over the existing wg-socrat (the separate wg-vpn-transit retired). Scoped NL Knot
restarts were required when changing the listener; the old dnsmasq mesh:53 is kept, the public listener is kept; a startup dependency on WG.
No Mac resolver override. This is not an HA/partition-consistency guarantee of three writers.
[Production evidence/incident](../../records/handoffs/vpn-production-cutover-20261109.md).

## What runs on the nodes

Knot runs on the OS of socrat-0/1/2/4, not in a pod. The source for the former nodes: `ansible/playbooks/public-authoritative-dns.yml`; the initial Moscow install: `ansible/playbooks/moscow-authoritative-dns-stage.yml`; the renderer `ansible/scripts/public_dns_zone.py`. An NS3-only refresh: `ansible/playbooks/ns3-public-dns.yml`. Do not replay the initial install on an already-configured server.

- The home DNS listens on the VIP `192.168.0.250:53`; the router forwards TCP/UDP 53 to it. The HOME HTTPS 80/443 is also served through the existing VIP scheme.
- The VPS authoritative DNS listens on the new public address.
- The Moscow Knot listens only on `91.189.82.238:53` TCP/UDP and answers from a local zone, independently of the old private DNS-relay in NL.
- Every 30s TCP 443 is checked; for failover names the entries that answered are published. If none answered, both addresses are kept, so the zone does not empty out.
- The record TTL is 60s; the servers refresh the zone independently, the SOA serial may differ slightly.
- `mail`, `sync`, `rooms`, `devsyringe` stay HOME-only per the renderer, rather than automatically getting two IPs.

The new public human entrances use the ordinary authoritative zone. `kuma.socrat.alchemmist.xyz` was added to the failover names after a detected NXDOMAIN that blocked ACME. It does not denote a native Kuma admin grant: the HTTPS gate and app auth are described separately.

The temporary `tv.alchemmist.xyz` is **fully retired**: it is no longer in the renderer/zone, the owned Ingress/Certificate/TLS Secret were removed. The TV uses `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>` without an internal WG. Do not add a separate TV domain back.

## How to change and verify

Do not blindly edit different authoritative servers independently. First check all four health-combinations of the renderer: all unrelated records must stay byte-equivalent. Then a whole-fleet preflight, a fresh exact hash, a serial owned-zone refresh with private backups/receipts, without a daemon/node restart. On an uncertain marker, stop, do not repeat the write.

- `ansible/scripts/public-web-dns.py` / `public-web-dns.yml` — a narrow initial Kuma addition, not a universal DNS editor.
- `ansible/scripts/grafana-tv-dns.py` / `grafana-tv-dns.yml` — now only the retirement of the temporary TV alias, not its creation.
- `ansible/scripts/vps-ip-migration.py` — a separate completed migration; do not run it just for a current DNS check.
- `ansible/scripts/retire-tv-public-alias.py` — only exact owned Kubernetes alias resources; no blanket Argo prune.

The final DNS retirement audits of three nodes showed operations=0; the alias-resource audit — operations=0. The other records are kept. Do not put NS/SSH keys, credentials and private receipts into the wiki.

Read-only check examples from a suitable external vantage:

```sh
dig @x.nic.xyz alchemmist.xyz NS +norecurse
dig @109.173.40.247 alchemmist.xyz SOA +norecurse
dig @109.120.141.60 alchemmist.xyz SOA +norecurse
curl -sS -H 'accept: application/dns-json' \
  'https://dns.google/resolve?name=grafana.socrat.alchemmist.xyz&type=A'
```

The home UDP `dig @8.8.8.8` was previously intercepted and could show an old TTL/AA. For an independent recursive cache view, use DoH and another provider/device; one local UDP result does not prove a global delegation. A forced-routing `curl --resolve` with the correct Host/SNI/TLS checks a specific entrance, **not** ordinary DNS resolution and not independent external access.

## Mac and fault-tolerance boundaries

The owned Mac `/etc/resolver` overrides and the wiki restorer lifecycle were removed, the global DNS/corporate VPN settings were not changed. An ordinary public HTTPS no longer depends on workstation overrides; NetBird DNS is off. The internal SSH is pinned to private addresses separately from the public DNS. A server-side private DNS for other consumers may remain. See [the Mac cleanup summary](../README.md#7-mac-the-old-owned-dns-lifecycle-fully-removed).

The cache does not learn about a failure before expiry and may keep a record longer than the TTL. Already-open connections do not move, the client is not obliged to repeat DNS after a TCP timeout. A public IP failover does not copy PVC/SQLite/MariaDB/GPU and does not make Authentik/management HA. Traefik Edge can use the last routes without a quorum only while the process, network and backend pods are alive. A lost backend/storage the DNS does not restore.

Sources: [public ingress](public-ingress.md), [VPS migration](../../records/handoffs/vps-ip-migration-20261105.md), [public-web closeout](../../applications/public-web/public-web-migration.md), `docs/network/lan/router-static-mappings.md`.


##2026-11-08: partial-network failure / phase1 observation

Current public renderer remains independently local-probed; it is NOT consensus
failover. With VPSIP inaccessible from HOME/mobile but locally healthy onVPS, the
VPS authority can publishVPS while HOME publishesHOME. Two CoreDNS upstream views
then disagree. Internal Authentik dependency was scoped to privateHA-VIP192.168.0.250
(no public DNS change) to restore observer revocation; this does not repair outside
browser fallback or make Authentik/storage HA. Full chronology in observer acceptance.

New on-demand scripts/public-entry-health.py checks forced-IP correct Host/SNI/
verifiedTLS/OIDC backend (no credentials). Local/hairpin probes are NOT external
reachability. scripts/public-entry-failover-plan.py only prepares deterministic
shared decisions with hysteresis and missing/stale/partition warnings; ALWAYS
ready_to_publish=false. No production DNS publisher/timer/TTL/zone change. Trusted
independent collector identities, distribution/leadership/fencing/stale leases,
partition policy and fleet acceptance required before rollout. See network phase1
runbook. By21:15 internalVPS path also timed out/ReadyUnknown; older healthy-VPS
facts are historical, not present availability proof.

## SPI standalone DNS addition — prepared, not applied (9 November 2026 UTC)

Operator explicitly approved adding only `spi.socrat`, after independent public
DoH confirmed NXDOMAIN for both SPI and the assumed wildcard. Source adds this
name to existing failover records; TTL, addresses, wildcard and all other records
are unchanged across all four health combinations. Narrow tooling:
`ansible/scripts/spi-public-dns.py`, `ansible/playbooks/spi-public-dns.yml`, private state
`/var/lib/homelab-spi-public-dns`. Follow the existing whole-fleet preflight, fresh
exact hash approval and serial zone-refresh procedure; no daemon/node restart.
Never run the Kuma-only helper for SPI. No apply has occurred: SSH to socrat-0/1
stops at missing trusted pinned host keys. Restore verified normal operator
access before Ansible become/preflight; do not bypass trust checks or alter
workstation DNS/VPN/routes. DNS readiness alone does not activate native OIDC.

## SPI DNS applied — 10 November 2026 UTC

The exact `spi.socrat` record was applied with the dedicated standard Ansible
whole-fleet preflight and serial refresh on existing authorities socrat-0/1/2.
All three approved the same SPI-only plan hash; all four health-state deltas
retain every unrelated record. Google and Cloudflare DoH independently return
HOME 109.173.40.247 / VPS 109.120.141.60, TTL 60. No wildcard/registrar delegation,
daemon/node restart, local DNS/VPN/routes change. Inventory contains five cluster
nodes; that does not expand the three-node authoritative DNS deployment.
Use the existing trusted homelab known-hosts file for Ansible IP-based targets,
as configured for the restored normal SSH aliases; never disable host checking.
Earlier missing-trust/prepared receipts above are historical.

## OpenHands exact-name addition —18November2026

`openhands.socrat.alchemmist.xyz` added to FAILOVER via Git and the dedicated
`openhands-public-dns.py`/Ansible guarded helper, following explicit owner sudo
authorization. All four nodes had identical fresh preflight hash; all four health
combinations preserved unrelated records; serial zone refresh/private receipts,
no daemon/node/network restart. REG.RU delegation/glue unchanged. All three current
authoritative NS and Google/Cloudflare answer HOME+VPS; native HTTP-01 Certificate
Ready, trusted TLS and SSO protection checked on both edges. This is an exact-name
addition, not a wildcard or permission to expose other services. [App scope](../../applications/ai/openhands.md).
