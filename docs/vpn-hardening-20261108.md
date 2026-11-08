# Configuration-only VPN hardening — 8 November 2026

Issue: [#83](https://github.com/alchemmist/homelab/issues/83). **In progress, not accepted.**
The owner explicitly excluded a new VPS, public IP or provider purchase. Original
P1/P2 independent-ASN and proxy/infrastructure-IP separation are deferred, not
prerequisites to start this configuration-only phase and not completed outcomes.
No configuration on this single address can defeat a filter dropping that address,
its prefix or ASN. We can reduce exposed fingerprints and diagnose failures better.

## Fresh runtime evidence

Internal SSH to socrat-2 succeeded. Agent audit at 11:29:48Z and parent preflight
confirmed the same pinned image, 3x-ui **3.11.0**, Xray **26.10.21**, hostNetwork and
panel-managed SQLite. Argo owns the container and edge resources, **not** inbounds.

- TCP32053 still has XHTTP/REALITY, Yahoo SNI and Intel target. Ordinary fallback
  fails hostname verification; that does not prove authenticated-client failure.
- Sony32083 and AMD32084 fallback verified TLS1.3/H2 in the fresh agent audit.
- TCP32063 still exposes XHTTP/VLESS with no outer TLS/REALITY. It has seven links,
  not seven demonstrated active users. It is not merely a TLS-terminated internal hop.
- There are **16 identities / 85 inbound links**. Traffic rows are per identity,
  not a complete per-inbound usage history; empty rows or one empty `ss` sample
  do not authorize retiring a listener. No device identifiers were read.
- Published Trojan is TLS443 through Traefik, `allow_insecure=0`; raw32087 and
  subscription12096 listen separately. Panel18082 already has a working guard.
- All seven host addresses are literal VPS IPv4. DNS-only switching is ineffective.
- Current and previous addresses were observed in AS216139 in the earlier audit;
  current RIPEstat was rechecked. The old address was not probed.

## Implemented foundation

### Consistent inventory and backup

`scripts/vpn-hardening-inventory.py` opens SQLite in `mode=ro`, uses the backup API
for a consistent snapshot including WAL, and performs integrity checks. It does
**not** use `immutable=1` on the live database, which could miss WAL state.

Only counts, ports, transport/security and configuration digests are printed.
Client material stays in memory/private backup. Volatile traffic counters do not
invalidate the configuration digest. Symlink paths, public state directories and
existing backup contents are rejected. No SQL updates are used.

A real online backup was created and checked at:
`/var/lib/homelab-vpn-hardening/20261108-phase1/backup`, directory0700/files0600.
The configuration digest was still unchanged at the later target-plan read.
Full backup contains credentials: never attach it or its rows to an issue.

### Passive backend counters, not enforcement

`scripts/vpn-backend-audit.py` defaults to preview; `--render` is offline. Explicit
root-on-socrat-2 apply requires the exact fresh plan hash and private state. It
installs only `inet homelab_xui_backend_audit`, input policy **accept**, with twelve
interface counters for TCP12096/32087. No reject/drop/NAT/packet logging, panel
rewrite, forwarding, SSH/WG/443 rule or process restart occurs.

The table is installed. Passive samples show32087 traffic on **lo and wg-socrat**;
12096 had no samples. These are path observations, not identification of every
consumer. Do not turn these counters into an allowlist automatically.

nft1.0.6 accepted the installation but omitted the table comment from JSON. The
initial readback stopped and left an uncertain marker. It was **not replayed**.
Exact validation of the complete chain/rule expressions and a readback-only
finalization resolved the marker with zero repeated remote writes. Regression
coverage includes omitted comments, reordered sets, counters and unexpected rules.

This observation table is intentionally **not boot-persistent**. Preserve its
counters during this investigation; do not reinstall/reset it. Removal, if needed,
is only the exact owned table (`nft delete table inet homelab_xui_backend_audit`),
never a ruleset flush. Existing panel guard and loopback readiness remained valid.
Live panel rules have an `nb-host` allowance absent from older Git rules: do not
reinstall that older panel ruleset as a side effect.

### Declarative target correction, preview only

`deploy/vpn-hardening/policy.json` specifies existing-server scope and a target-only
correction. `scripts/vpn-reality-plan.py` builds a pure, drift-checked plan from the
consistent live configuration. It refuses changed SNI, transport, security, ambiguous
target schemas and unsupported scope. It cannot execute SQL or API mutations.

The real plan contains one change: **32053 `realitySettings.target`, Intel443 →
Yahoo443**. Preserve Yahoo `serverNames`, client IDs, keys, short IDs, path, port,
XHTTP mode and empty flow. Node-side direct Yahoo TLS passed hostname verification,
TLS1.3 and ALPN h2. This makes Yahoo a candidate, not an accepted REALITY migration.
The plan is intent, not a readiness/deployment receipt.

### Bounded path diagnostics

`scripts/vpn-path-check.py` makes one HTTPS attempt with explicit stage reporting:
DNS → TCP → verified TLS → HTTP/complete transfer. It never retries, rotates IPs,
stops workloads or claims it authenticated a VPN tunnel. It preserves corporate
VPN/DNS/routes. Per-connection controls are limited to the two existing approved
public ingress addresses, keeping TLS hostname verification; no OS overrides.

Only approved public HTTPS hosts443, no userinfo/query/fragment, and no private
VPN panel/subscription paths. Do not supply credential-bearing URLs. Bodies are
bounded to2MiB and never printed. A short response or incomplete Content-Length
cannot pass the complete-success-above32KiB check. No threshold alert is inferred.

Example from an already-approved vantage, without installing an agent there:

```sh
python3 scripts/vpn-path-check.py --vantage approved-fixed-ISP-ASN \
  --url https://wiki.socrat.alchemmist.xyz/ --address 109.120.141.97
```

The workstation control reached both normal HOME resolution and the explicit VPS
with verified TLS and complete small responses. Those responses were **below32KiB**,
so they were correctly **not** counted as large-transfer acceptance. The workstation
uses mandatory corporate VPN; it is not a Russian residential/mobile vantage.
Real tunnel, large-transfer and Russian fixed/mobile acceptance remain open.

## Research, re-read by subagents

Five child reports covered Russian field evidence, exact upstream protocol source,
fresh runtime, IaC ownership and an independent safety synthesis. Research is not
causal attribution for these incidents; some sources were only partially accessible.

| Source | Supported conclusion / caveat |
| --- | --- |
| [net4people671](https://github.com/net4people/bbs/issues/671), retrieved via `gh api` | Field reports across REALITY and AWG-only hosts, TCP-only/home-ISP/exit-IP failures, and spontaneous recovery. Attachments not downloaded. Does not establish an AI classifier, universal byte threshold or the cause of our incidents. |
| [net4people662](https://github.com/net4people/bbs/issues/662) | Author withdrew simple prefix attribution after DNS/anycast confounding. One datacenter/hostname is not residential national evidence. |
| [Cloudflare, June2025](https://blog.cloudflare.com/russian-internet-users-are-unable-to-access-the-open-internet/) | Operator observed approximately16KiB truncation across H1/H2/H3. Not a current measurement of this VPS or every Russian ISP. Tiny200/TLS is insufficient. |
| [FOCI2026 abstract](https://www.petsymposium.org/foci/2026/foci-2026-0010.php) | QUIC SNI censorship studied in2022–2023. Abstract read, PDF not read; UDP/QUIC is not a universal escape. |
| [REALITY](https://github.com/XTLS/REALITY) and [XHTTP4113](https://github.com/XTLS/Xray-core/discussions/4113) | Coherent target/SNI, real TLS1.3/H2 and intentional defaults. No magic padding/XMUX values or IP-ban immunity. |
| [Xray26.10.21](https://github.com/XTLS/Xray-core/tree/v26.10.21) | Source accepts REALITY on RAW/XHTTP/gRPC. Vision requires the direct TLS/REALITY connection, not an XHTTP/gRPC stream. Leave existing flow empty. |
| [3x-ui3.11.0](https://github.com/MHSanaei/3x-ui/tree/v3.11.0) | Exact release/source and API auth examined. Tokens are hashed, not recoverable plaintext. Subscription-cache invalidation still needs live acceptance. |
| [Amnezia vendor docs](https://docs.amnezia.org/documentation/amnezia-wg/) | Research fetches had inconsistent extraction depth. Do not claim a verified3.1 migration, parameter compatibility or on-wire behavior. Existing peers stay unchanged. |
| [USENIX2023](https://gfw.report/publications/usenixsecurity23/en/) | Fully encrypted-traffic detection research in China, not a TSPU specification or tuning recipe. |
| [net4people663](https://github.com/net4people/bbs/issues/663), [675](https://github.com/net4people/bbs/issues/675) | Unverified TUN hypothesis with DNS/NAT alternatives; unrelated Iran panel claims with unread images. Neither authorizes corporate VPN changes or proves our panel detectable. |

Server-side freedom/direct still uses the same VPS source IP: it cannot implement
client-side Russia-direct egress. Personal split routing needs actual client/DNS/IP
compatibility and a separate opt-in; `.ru` alone is insufficient. No global route
or TV profile was changed. Optional RAW+Vision would be another transport on the
same IP, not an independent fallback. No image upgrade or AWG retuning was bundled.
The separate November7 watchdog fence is not proof of an IP ban and was not altered.

## Next gated production steps

1. Obtain an existing private machine API credential, or explicitly approve a
   separately named, temporary `node-sync` automation token with cleanup.
   Upstream v3.11.0 explicitly allows inbound list/add/update/delete for `node-sync`;
   it does not need full `admin` scope or panel self-update permission.
   One enabled admin token exists; its database value is a SHA-256 hash. No plaintext
   file was supplied. Do not call `x-ui -getApiToken` as a read: upstream source and
   tests show it **recreates/rotates a named credential**. No token, human password,
   MFA, session or database row was changed to bypass this boundary.
2. With fresh version/config checks, backup and native API preimage, apply only the
   32053 target. API changes can restart the Xray child and interrupt all its
   listeners; do not combine with a firewall or client migration. Verify fallback,
   unchanged rendered links and one authorized authenticated test client.
3. Inventory the seven32063 links and subscription consumers; introduce a compatible
   encrypted replacement before any retirement. Verify subscription cache refresh
   and client import. Credential rotation is a separate evidence-based decision.
4. Observe12096 and distinguish Traefik/cluster probes from direct consumers; only
   then design a narrow backend guard. Preserve readiness, subscription fetches,
   Trojan443 and machines. Do not guess interface/source allowlists.
5. Run actual tunnel/large-transfer tests from available fixed/mobile Russian paths
   and an external control. No trigger traffic, malformed packets, broad scans,
   packet payload captures or automatic IP rotation.

The issue remains open. Tests/healthy counters are not proof of accepted encryption,
closed public backends, Russian reachability or protection from destination-IP bans.
