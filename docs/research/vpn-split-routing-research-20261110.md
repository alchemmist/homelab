# RF/NL split routing — research, 10 November 2026

**Owner decision after research: DEFERRED. Keep the accepted Moscow → NL runtime
and existing Happ bypass unchanged. This document is reference only, not pending
work, approval to move termination, or authorization to resume implementation.**

**Research only. No production routing, credentials, subscriptions, DNS, ports,
Pod or native services changed. This is not a deployment recipe or acceptance.**

## Verified current state (native read-only, sanitized)

NL panel settings: `subEnableRouting=true`, `subRoutingRules` decodes as
`happ://routing/onadd`, profile `Alchemmist VPN`, GlobalProxy=true,
DomainStrategy=AsIs, FakeDNS=false.49 DirectSites rules: broad ru/xn--p1ai/su plus
explicit VK, Yandex, Wildberries/wbstatic, Ozon/ozonusercontent, banks, government,
transport, retail domains. DirectIp/ProxySites/ProxyIp/BlockSites/BlockIp empty.
No Geoipurl/Geositeurl override in that profile. Thus existing bypass is a manual
domain list, not proof of a maintained server-side GeoIP classifier. Happ itself
ships geo files according to vendor documentation. Panel intent verified, not
current profile activation/delivery on every user's phone.

NL actual Xray routing matches stored template: api inbound→api, geoip:private→
blocked, otherwise first outbound `direct` (Freedom from NL). No RU/Moscow egress.
VLESS32053/32083/32084 and WG32085 sniffing disabled; Trojan32087 has HTTP/TLS/QUIC
routeOnly sniffing. Actual runtime also has a local SOCKS inbound tagged
amneziawg-51821 with sniffing; this suggests AWG may share the classifier through
its integration, but authenticated end-to-end AWG has NOT been accepted.

Moscow is an opaque fixed-destination relay, not a VLESS/Trojan/WG terminator.
The outer REALITY/TLS SNI is camouflage/VPN hostname, not the visited website.
Adding geosite rules to this relay cannot discover the inner destination.

Happ direct means bypass Happ, not bypass other OS/corporate VPNs. Abroad, bypass
may use a foreign ISP address; the Moscow server cannot fix traffic it never sees.
Keep requested existing client bypass, but flag broad .ru conflicts with blocked
Russian domains and the abroad/corporate-underlay limitation before any future
client change. Do not silently alter Mac Tunnelblick/routes or human app profiles.

## Desired policy: Russia-default, explicit foreign exception

A proposal suited to avoiding accidental NL exposure to unclassified Russian
services is **default Moscow egress**, not default NL plus a finite RU list.
This changes generic VPN semantics: unknown foreign services will use a Russian
address, may fail due to geoblocking/censorship, and expose destination metadata
to the Russian hosting network. This is availability/privacy tradeoff, not extra
anonymity or a guarantee against IP blocking.

Logical priority (not copy/paste Xray JSON):

1. Preserve API/management isolation and block client access to private/link-local/
   reserved destinations, metadata endpoints, loops and unauthorized local proxies.
2. Explicit `must-ru` critical domains / inside-Russia-only list → Moscow or error.
3. Reviewed `must-foreign` service families and compact domain block/geo-block list
   → NL or error. Known policy intersections must be reviewed, not accidental.
4. Other RU service/category domains and GeoIP-RU hint → Moscow. Broad `.ru` is not
   an exception above explicit foreign rules: blocked .ru domains exist.
5. Everything else, including unclassified IP-only flows → Moscow.

Never auto-fallback must-RU traffic to NL or must-foreign traffic to RF. Native
recovery and list-update failures must preserve policy, not revert to NL catch-all.
Do not combine domain and IP conditions expecting OR: Xray applies fields in one
rule as AND; ordered separate rules required. Use explicit catch-all and audited
outbound order (Xray's unmatched default is its first outbound).

## Sources assessed

| Source | Useful purpose | Caveats |
| --- | --- | --- |
| [runetfreedom/russia-v2ray-rules-dat](https://github.com/runetfreedom/russia-v2ray-rules-dat) | Unified Xray geo files; ru-blocked, ru-available-only-inside and upstream service categories | Maintainer says updates every6h. Avoid ru-blocked-all (~700k+ domains); do not auto-ingest broad IP/ASN categories. |
| [itdoginfo/allow-domains](https://github.com/itdoginfo/allow-domains) | Russia/inside covers censorship AND foreign geoblocks; outside covers services requiring RU address | Names are easy to invert: inside is the foreign-exit candidate, outside is the RU-exit candidate. Raw lists inspected. Outside is not a complete inventory of Russian sites. |
| [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) | Service families youtube, openai, xai, instagram, reddit, notion; dependency domains | The project explicitly does not prescribe proxy/direct decisions. Categories are not company-ownership/security guarantees. Review shared telemetry/ads/CDN and regex/keyword entries. |

Initial foreign candidates: curated `ru-blocked`/itdog inside plus explicit
YouTube, OpenAI/ChatGPT, xAI/Grok, Instagram, Reddit, Notion categories and reviewed
auth/media/API dependencies. A blocklist alone misses desired services that are
not consistently blocked. OpenAI list includes oaistatic/oaiusercontent and voice
endpoints; YouTube includes googlevideo/ytimg; Notion has notionusercontent.

Do not send all Cloudflare/Amazon/Google IP space abroad: shared CDN IPs host
Russian sites too, defeating the purpose. Domain policy first; service-specific
IP exceptions only when justified. category-ru includes ALL .ru through tld-ru,
not just confirmed Russian companies. GeoIP is location data, not ownership.

Choose one reviewed data family + explicit project overrides; don't stack every
large upstream artifact. Pin source commit/artifact SHA, check license and diff,
counts/intersections and syntax against installed Xray26.10.21, memory budget,
canary acceptance. Atomic last-known-good update; no executing downloaded scripts,
no runtime dependency on GitHub for boot/native fallback. Hashes from the same
publisher verify transfer integrity, not independent trust/authenticity.

## Architecture alternatives (decision still required)

### A. Preserve NL termination; add private Moscow egress (recommended first)

```text
Client → Moscow opaque relay → NL authenticates/classifies
                              ├─ explicit foreign → NL internet
                              └─ RU/default → existing mesh → Moscow egress → internet
```

The Russian service sees Moscow public IP, not NL. Only encrypted/proxied transit
passes through NL; this does NOT eliminate that transit or make the classification
happen on Moscow. There is an extra cross-border round trip for traffic already
missed by Happ bypass. Existing client identities, REALITY keys, panel ownership,
quota/traffic accounting and public entry can stay in NL.

Moscow private egress could be SOCKS5 over the existing WG (SOCKS itself is not
encrypted) or a private authenticated proxy transport. Bind private only, admit
only NL peer, never public open proxy, guard original destination/private ranges,
force actual internet egress source to Moscow public address. Ensure no relay
loop back to NL. UDP support must be tested, not inferred from TCP SOCKS success.
Both Moscow Pod/native modes must include same egress function and port fencing;
NL Kubernetes/native modes must share routing/geodata. No extra WireGuard needed.

This is a small extension relative to moving all termination, not a promise of
zero-risk/no-restart deployment. Acceptance needed for all protocol paths and modes.

### B. True destination selection on Moscow

```text
Client → Moscow VPN terminator/classifier
         ├─ RU/default → Moscow internet
         └─ explicit foreign → private proxy tunnel → NL internet
```

Cleaner/shorter RU path, but current transparent relay cannot do this. Requires
client authentication and REALITY/Trojan/WG termination on Moscow, appropriate
server keys/TLS custody, one-way synchronization from authoritative NL panel,
consistent revoke/expiry/quotas and per-user traffic aggregation. No second
independent panel or two writable identity stores. Server compromise/custody
scope changes. Retaining client keys/subscription URLs does not by itself prove
consistent accounting. Must not implement by secretly copying clients into an
unmanaged config or declaring existing NL-only counters authoritative.

If literal Moscow classification/no RU detour through NL is a hard requirement,
choose B as a separately scoped migration; A is not represented as B.

## DNS, encryption, IPv6, UDP

Proxy-provided destination names are preferable to guessed geolocation. For
IP-only requests assess per-inbound routeOnly sniffing of HTTP/TLS/QUIC. It does
not decrypt HTTPS and is not a TLS MITM; ECH can hide real SNI, QUIC sniffing can
fail. Unknown must remain RF under chosen privacy-oriented default, so access
false negatives are expected until metadata rules are improved. WG/IP flows
cannot be assumed equivalent to domain-aware VLESS requests.

Resolve target names through the selected egress where possible; separately
route DNS, bootstrap DoH safely and disallow inappropriate resolver fallback.
Current Moscow53→NL5354 is **authoritative** alchemmist DNS, NOT a recursive
resolver to reuse for arbitrary client internet names. Test A/AAAA, raw-IP,
DNS-over-UDP/TCP/DoH, HTTP3/QUIC and fallback. No IPv6 or UDP escape to an implicit
NL default; no global Mac DNS/route change and no broad UDP443 block as a shortcut.

## Acceptance before any cutover

- Build/diff policy offline; test known RU, critical inside-only, named foreign,
  blocked .ru, unknown, IP-only, CDN/shared-IP and intersection cases.
- Observe ONLY aggregate route tags/counters or owned synthetic requests, not
  users' browsing histories, URLs, cookies, SNI dumps or packet payloads.
- Canary one owned authenticated fixture; preserve17 identities/91 links and
  subscription URI84/JSON77. Native API/preimage/CAS and private backup, no SQL edits.
- Prove egress IP with controlled test endpoints, not merely page200 or Pod Ready.
  Test intended real services without human-account impersonation.
- Repeat REALITY/Trojan/other VLESS/WG; AWG separate authenticated proof required.
- Failure matrix: NL down, Moscow egress down, list update failure, DNS failure,
  Moscow Pod/native and NL Kube/native. Classified traffic blocks rather than
  silently changing country. Retest independent management/cluster health.
- Do not promise perfect classification or IP-ban immunity. A website sees its
  connection's source IP; automatic marketplace→RKN→our IP blocking is a user
  threat hypothesis, not established evidence for the prior incidents. DNS/CDN,
  cookies, cross-site identifiers, fingerprinting and other metadata remain.

## Primary technical references (retrieved for this research)

- [Xray routing](https://xtls.github.io/en/config/routing.html)
- [Xray sniffing/ECH/routeOnly](https://xtls.github.io/en/config/inbound.html)
- [Xray DNS and local-mode bypass](https://xtls.github.io/en/config/dns.html)
- [Xray SOCKS outbound / no built-in encryption](https://xtls.github.io/en/config/outbounds/socks.html)
- [Happ routing / per-subscription profile and reconnect](https://www.happ.su/main/dev-docs/routing)

These are current upstream docs, not validation of every feature/schema on our
pinned core or each installed Happ version. No implementation accepted here.
