# VPN: актуальный production и исторический hardening

## Актуально: production VPN через Москву, 9 ноября 2026

**Клиенты/HOME → Москва91.189.82.238 → NL109.120.141.60**. URL подписки
`vpn.alchemmist.xyz` неизменен; обновлять существующую подписку, не аккаунт/ключи.
Все три DNS-writer публикуют статический VPN A Москвы без NL fail-open. Нативные
Hosts7/7 обновлены:17 identities/91 bindings сохранены,32063 disabled. Подписки всех
17 клиентов:84 URI/77 JSON, обычный DNS/валидный TLS, старого NL endpoint нет.
После восстановления проверены из HOME три VLESS/REALITY, Trojan и WG:200/65536B/
контрольный hash, отдельный HTTPS exit-check=NL. UDP32…8192B через реальный
зашифрованный межсерверный канал также проверен; это не authenticated AWG/mobile.

HOME0/3 management WG и HOME1 pinned-TLS/GOST идут через Москву; известные NL
DNS/HTTPS/VPN потоки на HOME0/1/3 перенаправляются scoped persistent nft DNAT.
Не глобальный exit node, Mac/default routes/DNS-настройки не менялись. Private
DNS:Москва10.250.0.40:53→NL10.251.4.2:53. NS1 HOME и NS2/glue NL сохранены.
NL WAN raw VPN закрыт; только Trojan HTTP-путь на shared443 допускает московский
private10.251.4.1/32 и точный loopback127.0.0.1/32 для штатной health-проверки.
Public403/private101, spoofedXFF не помогает; портал200/LMS303/Argo200 сохранены.
Такой же gate установлен/проверен в native Caddy fallback.

**Инцидент не скрывать:** первоначальный ACL пропустил local health и вызвал
watchdog fallback/остановку NL K3s. Исправлено loopback-исключением, проверки и
watchdog не отключены. Штатный failback исходного member без reset/replacement;
160MB Raft catch-up занял3m45s, bounded start timeout180→600s. После восстановления:
3 healthy voters/common leader/hashKV equal (revision17449598),5Ready/noMemoryPressure,
все пять транспортов и17 подписок повторно приняты, watchdog healthy/fallback off.
Московский socrat-4 — agent-only10.250.0.40, bootstrap NoSchedule сохранён,
не control-plane/etcd/обычный heavy worker. Четыре human admin routes не расширялись.

Бэкапы пяти нод плюс post-recovery supplement — private/off-host/SHA verified;
история/старые recovery receipts сохранены.126 tests+14 subtests passed — срез приёмки,
не непрерывный healthcheck. Mobile/Happ interactive, authenticated AWG, полный DR/
chaos/reboot и сохранение end-user IP enforcement не доказаны. Не обещать HA/TSPU immunity.
Подробности и custody: [production runbook](../docs/vpn-production-cutover-20261109.md).
Исторический staging: [Moscow bootstrap](../docs/moscow-vpn-transit-20261109.md).
Не переисполнять migration/prepare/apply: fresh preimage/CAS, uncertain→разбор.

## Исторические этапы — не текущие запреты/задания

Запрет новой VPS/IP относился к8ноября;9ноября владелец отдельно разрешил
Москву и production cutover. Старые enabled32063/pending утверждения ниже superseded.

# VPN hardening — configuration-only phase, 8 November 2026

Issue [#83](https://github.com/alchemmist/homelab/issues/83) remains open.
Current [implementation/evidence/runbook](../docs/vpn-hardening-20261108.md).

## Budget and intent

Owner explicitly ruled out a new VPS, public IP or provider purchase. Work on
existing socrat-2 configuration and diagnostics. Original independent-ASN/P1 and
proxy/infrastructure-IP separation/P2 are deferred, not secretly provisioned or
claimed complete. No protocol settings defeat an actual destination-IP/prefix/ASN
block. Cause of the two reported blocks remains unproven; do not reclassify the
separate November7 watchdog fence as a demonstrated TSPU IP ban.

## Observed and implemented

- Fresh internal audit: 3x-ui3.11.0, Xray26.10.21, same pinned image, hostNetwork.
  Panel SQLite owns profiles; Argo owns workload/edge, not inbounds.
- 16 identities and85 inbound links, **not85 people**. Plaintext32063 has7 links;
  per-identity traffic rows do not prove per-inbound use or non-use.
- **32053 corrected via native API:** Yahoo SNI now matches Yahoo target. Verified
  fallback certificate/TLS1.3/H2 and an owned synthetic VLESS/XHTTP/REALITY client
  downloading65536 bytes before and after. Full semantic proxy comparison proved
  only target changed; SNI, keys, short IDs, flow, port and human records preserved.
  Same-node acceptance is not Russian ISP or every real-device acceptance.
- `scripts/vpn-hardening-inventory.py`: read-only consistent SQLite snapshot,
  WAL-aware backup, config hash, sanitized counts. Private backup checked under
  `/var/lib/homelab-vpn-hardening/20261108-phase1`, mode0700/files0600.
- `scripts/vpn-backend-audit.py`: default preview, explicit hash-gated root apply.
  ACCEPT-only passive table installed for12096/32087, no reject/drop/NAT/logging
  or persistence. Observed32087 on lo and wg-socrat;12096 still lacks samples.
  Exact nft1.0.6 readback validates expressions even when JSON omits table comments.
  Interrupted readback finalized without replay. No Xray/pod/node restart occurred.
- Panel18082 guard stays unchanged; its live nb-host allowance is absent in older
  Git rules. Never reinstall that old ruleset over live state as a side effect.
- `scripts/vpn-path-check.py`: bounded DNS/TCP/verified-TLS/complete-HTTPS stages,
  no credentials/retries/autorecovery/tunnel claim. Small workstation responses
  passed but did not qualify as >32KiB. Russian fixed/mobile and tunnel tests open.
- `deploy/vpn-hardening/policy.json` and `scripts/vpn-reality-plan.py` encode intent
  and strict preview, not runtime readiness or an executable SQL migration.

## Approved native access, clean teardown, remaining gates

Owner explicitly approved temporary machine API access. `vpn-panel-session.py`
checks new-name collisions, source version/image/UID and fresh hashes, uses native
CLI only for a uniquely named bootstrap, then TTL-limited admin-cleanup30min and
node-sync worker20min tokens. Actual data operations use node-sync. No SQL writes,
password/MFA reset or human credential impersonation. Native CLI bootstrap has no
TTL: interrupted creation must stop with private evidence, not blind replay.
`-getApiToken` must still NEVER be used as a credential read or on an existing name.

Two sessions ran: the first passed64KiB baseline then stopped before target save on
the modern nested-JSON DTO (now regression-covered); all its changes were cleaned.
The next fresh session completed. **Zero temporary tokens or synthetic client remain;
original two token rows, users and settings matched the pre-session backup.** Pod
remains Ready/restarts0; native Xray child reload is not a pod/node restart.
The post-change target plan is no-op. Private proof under
`/var/lib/homelab-vpn-hardening/vpn83-20261108-target-final`.

All seven plaintext links already have an enabled encrypted alternative; no new
port/listener is needed just to provide one. Configured subscription bases are HTTPS
on the expected hostname. All16 standard URI subscriptions were checked via public HTTPS and loopback:
85 entries match, ignoring only randomized REALITY sid (79 interpreted profiles
and6 opaque vpn imports preserved unchanged). All7 affected records really publish
encrypted alternatives. JSON-subscription/device compatibility remains unproven.
Six affected identities have10 registered HWID rows; the seventh has no registered
device inventory. These are not ten proven current/unique devices. Audit GETs used
a distinct agent and can update last_sub_fetch: NEVER treat them as device refresh.
Socrat-3 Happ saved port32053, TUNfalse, no active loopback proxy; no app store/GUI/
route change or functional-device claim. No end-device control/acceptance exists
yet; migration is **not complete**,32063 remains. Private follow-up evidence under
`/var/lib/homelab-vpn-hardening/migration-client-audit-20261108`.

Do not close32063 before compatible encrypted replacement/subscription refresh and
client acceptance. Do not enforce raw-backend rejects before consumer/source proof.
Keep WG/AWG peers, inter-node/recovery, NetBird, mandatory Tunnelblick, global routes/
DNS, production Traefik443 and TV profile unchanged. No magic padding/Vision on
XHTTP/gRPC, image bump, broad firewall flush or Argo sync/prune.

Research references/limits are in the linked runbook: net4people671 field anecdotes,
662 attribution withdrawal, Cloudflare2025 byte truncation, FOCI QUIC SNI abstract,
exact upstream Xray/3x-ui source, and incomplete Amnezia/image/PDF extraction.
Do not turn field hypotheses into proven classifiers or ban-prevention guarantees.


## Latest: plaintext publication withdrawn, owner coordinates device refresh

Owner explicitly clarified they will ask clients to refresh subscriptions. Native
`excludeFromSub=true` is now applied only to32063; enabled=true retained for cached
clients during transition. `vpn-subscription-migrate.py` requires fresh dual hashes,
backup and full publication checks. All16 URI AND JSON subscriptions were checked
public-vs-backend before/after: exactly7 plaintext links removed,78 URI entries
remain; other profiles, opaque vpn imports, remaining JSON configs, identities,
keys and URLs unchanged. Each affected identity retains REALITY. Both legacy vnext
and current flat VLESS JSON shapes are regression-covered; the first session stopped
before a write on schema validation, cleaned itself, and was not replayed.

User instruction: update the SAME subscription, then select an encrypted profile if
not automatically selected. No new credentials required. No remote-device access
gate for this publication change. **Server publication migration done; end-device
refresh and old-listener retirement not claimed.** Keep32063 enabled until owner
confirms users refreshed/connected; do not invent acceptance from our audit GETs.
All temporary tokens cleaned, original users/settings/tokens preserved; pod Ready,
restarts0, three verified REALITY fallbacks healthy.64 tests+6 subtests local passed.
Private proof `/var/lib/homelab-vpn-hardening/vpn83-20261108-subscription-final`.


## Latest: backend exposure closed and real home-path tunnels accepted

A separate exact-owned `inet homelab_xui_backend_guard` INPUT priority-6 rule set
now returns established/raw connections and rejects NEW eth0 TCP12096/32087 only.
No NAT/forward/443/SSH/overlay changes; audit counters remain separate. Before tests
other-interface counters were0; baseline raw public ports open, after enforcement
external TCP resets on both and verified TLS443. All original16 URI+JSON subscriptions
preserved, own synthetic TrojanTLS443 downloaded64KiB before and after. No human
credentials. Guard unit enabled+active; no reboot performed/boot acceptance claimed.
Nft1.0.6 ct-state `in` AST mismatch stopped readback AFTER installation; exact
validation fixed and readback finalized with ZERO rule replay. Fresh session tested
existing guard/persistence. Limited fixture JSON excluded from original-population
checks. All fixtures/tokens cleaned; original proxy records unchanged.

Home socrat-0 actual WAN (eno1→192.168.0.1, public source matches approved home IP,
not WG/NetBird) then passed native **REALITY32053 AND TrojanTLS443,65536 bytes each**.
Only own20min/10MiB identity; pinned copied core; no route/DNS/global-proxy change,
no human secret use, protected SSH fetch/copy rather than secrets in argv/env.
Processes/configs/binary removed, native fixture/tokens cleaned, four nodes Ready,
watchdog Kubernetes/healthy/not inhibited. This is home FIXED, **not mobile**.
Private `vpn83-20261108-backend-{final,accept}` and `vpn83-20261108-home-acceptance`
on VPS; home `/var/lib/homelab-vpn-hardening/vpn83-home-fixed-20261108/receipt.json`.
71 local scoped tests+6 subtests passed; not full repo/DR/IP-ban immunity.

Remaining retirement gate: owner said they WILL ask users to refresh, not that
refresh succeeded. Legacy32063 remains enabled/excluded. Live watchdog still
expects32063 in endpoint/listen/native-primary inventory; monitoring lists it too.
A plain API disable would falsely fail recovery and can fence K3s. Retirement must
coordinate exact source/live config+collector updates under the existing watchdog
lock, not stop recovery or ignore alerts. Do not falsely claim device/mobile/reboot
acceptance. Budget still excludes new VPS/IP/ASN fallback.


## Latest authoritative: server move complete,32063 disabled

Owner explicitly approved old-client disconnect to finish. Native32063 now
**enable=0, exclude_from_sub=1**, no TCP listener, external TCP refused. Only native
enable flag changed, original clients/keys/bindings/URLs untouched. All16 URI+JSON
subscriptions preserved (78 published entries). Users update SAME subscription and
select an encrypted REALITY/Trojan profile if needed; no replacement credentials.
Individual-device refresh is NOT claimed; owner cutover approval supersedes waiting
for its confirmation. Do not resurrect the previously retained legacy listener.

Watchdog endpoint/listen/native-primary inventories and collector ports updated
BEFORE disable; corresponding Ansible defaults/template updated. Brief timer-dispatch
pause+existing-job drain+existing serialization lock, no stopping running watchdog/
K3s/native services, no latch/counter manipulation. Timer resumed, watchdog healthy
Kubernetes/not inhibited, collector new ports+exit0, four nodes Ready. One successful
native disable; boolFalse-vs-SQLite0 sort comparison stopped readback afterward.
Per-ID diff proved no extra fields changed; integer-type fix regression covered.
Full readback/subscriptions finalized with ZERO repeated configuration/API writes.
Original users/settings/token rows preserved, zero probe clients/temp tokens.

Repeated actual home-WAN post-retirement REALITY32053 and TrojanTLS443 tests both
HTTP200/65536 bytes, expected source/non-overlay, routes/resolver unchanged; own
fixtures/binary/configs/processes/tokens cleaned. Private legacy-retire and
post-retire-home sessions on VPS; home `vpn83-home-after-retirement/receipt.json`.
133 expanded local tests+8 subtests passed. Mobile and reboot/DR NOT tested; no
future-IP/ASN-ban immunity/new infrastructure purchase. Server cutover complete;
#83 remains for explicitly unverified/deferred broader resilience outcomes.


## New active incident: public access degraded after otherwise accepted cutover

19:07 home→literalVPS secure TCP ports timed out; workstation initially passed then
also timed out by19:20–19:33. Owner reports Main/Happ initially surviving, then ALL
phone VPNs also failing on mobile. Internal VPS health/4 Ready nodes normal, exact
proxy/traffic auth-quota fields unchanged, all16 clients enabled, no observed exact
home ban/conntrack exhaustion. No repair/reset/IP change performed. Independent
single Germany AS24940 check reached literalVPS443 in10ms:
https://check-host.net/check-report/567207ddk3ba. Regional/source filtering/routing
is likely; NOT proven TSPU/block attribution or a globally dead server.

IMPORTANT DNS: vpn.alchemmist.xyz currently resolves HOME public IP from workstation;
that TLS443 works while literalVPS443 times out. Hostname success != direct VPS
success. Earlier Trojan test used that hostname, exact destination not recorded;
only REALITY home config explicitly targeted VPS literal. Do not overstate prior
Trojan path. Header-only VPS observations are NOT matched home-test packet proof;
paired home capture unavailable (no tcpdump, not installed), cannot localize loss.

IP change may temporarily restore regional access, not cure prefix/ASN filtering.
Keep old IP/control path until parallel cutover; no provider purchase/replace without
owner authorization. Do not silently shift VPN users onto HOME IP (risks all home/
infra endpoints). Mobile failure is owner-reported. Root-cause incident still open;
accepted config migration is not evidence of ongoing availability/IP-ban immunity.
