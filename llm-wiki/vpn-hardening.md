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
