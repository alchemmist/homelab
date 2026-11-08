# Configuration-only VPN hardening — 8 November 2026

Issue: [#83](https://github.com/alchemmist/homelab/issues/83). **In progress: REALITY, subscription withdrawal, public backend guard and home-fixed protocol acceptance accepted. Legacy retirement/mobile gates remain.**
The owner explicitly excluded a new VPS, public IP or provider purchase. Original
P1/P2 independent-ASN and proxy/infrastructure-IP separation are deferred, not
prerequisites to start this configuration-only phase and not completed outcomes.
No configuration on this single address can defeat a filter dropping that address,
its prefix or ASN. We can reduce exposed fingerprints and diagnose failures better.

## Fresh runtime evidence

Internal SSH to socrat-2 succeeded. Agent audit at 11:29:48Z and parent preflight
confirmed the same pinned image, 3x-ui **3.11.0**, Xray **26.10.21**, hostNetwork and
panel-managed SQLite. Argo owns the container and edge resources, **not** inbounds.

- Before correction, TCP32053 had XHTTP/REALITY, Yahoo SNI and Intel target.
  Ordinary fallback failed hostname verification. It now has the matching Yahoo
  target; the failed disguise was not proof of authenticated-client failure.
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

### Target correction applied and synthetically accepted

After explicit owner approval of temporary machine access, the target-only change
was applied through the **native API**. Current TCP32053 target and SNI both use
Yahoo. TLS fallback now verifies the hostname, TLS1.3 and ALPNh2. Sony32083 and
AMD32084 still pass the same fallback checks; Trojan/panel loopback readiness and
the primary pod are healthy, container restarts0. The Xray **child** reload from
native inbound save is distinct from a pod/node/K3s restart.

`deploy/vpn-hardening/policy.json` enables the explicitly gated executor.
`scripts/vpn-reality-plan.py` stays pure/read-only; the post-change plan is a no-op.
`scripts/vpn-reality-apply.py` requires fresh session and target hashes, backup and
version/preimage checks. It posts only the target change and checks the whole
semantic configuration, including all original client/host/binding data. It never
writes SQL or silently replays an ambiguous API mutation.

A newly generated, owned **synthetic VPN identity** was linked only to32053. No
human credentials were used. A separate same-node Xray client bound only loopback
and allowed only `speed.cloudflare.com`; all other destinations were blackholed.
It authenticated with VLESS/XHTTP/REALITY and downloaded **65536 bytes before and
65536 bytes after** the correction. Body files were discarded after hashing.
This proves exact-core compatibility and complete tunnel transfers at this vantage,
**not Russian ISP availability or every distributed client build**.

The first attempt passed the baseline but stopped before a target write because
3x-ui3.11 returns nested JSON objects, not legacy JSON strings. Its own fixture and
credentials were cleaned, and original config preservation was checked. Source and
regression tests now accept both DTO forms. The next fresh, separately named session
completed the correction; neither failed state nor a target write was replayed.

Final semantic comparison proved **only target changed**. A separate readback of
`users` (excluding login epoch), `settings` and complete original `api_tokens` rows
matched the pre-session backup. Thus no password/MFA/settings or existing token
changes were concealed by the four-table proxy projection. Rendered human
subscriptions/device refresh were not exercised or claimed from that comparison.

#### Temporary machine credential lifecycle

`scripts/vpn-panel-session.py` uses collision-checked, separately named credentials.
Native CLI issuance is authorized **only for a new unique bootstrap name**, never
`install`, `cli-fallback`, an empty name or a pre-existing token. Its plaintext goes
directly to an exclusive0600 private file. A TTL-limited cleanup admin token30min
and worker `node-sync` token20min are created; bootstrap is immediately deleted.
Only the worker performs client/inbound operations. Cleanup uses exact name/id/hash
ownership and expected-scope checks, removes own rows and private secret files, and
compares all original token rows byte-for-byte. Both executed sessions cleaned up;
**zero temporary token rows or synthetic client remain**, original two tokens intact.

The native CLI cannot assign bootstrap expiry. A crash between issuance and its
native self-cleanup is an unavoidable **uncertain** window, not an excuse to rotate
old tokens or replay creation. Private stdout/intent is retained on uncertainty.
TTL bounds the subsequent worker/cleanup credentials, not that initial CLI window.
No human login/password/MFA, browser session impersonation or direct SQL mutation
was used to obtain access.

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
Same-node authenticated64KiB tunnel acceptance subsequently passed as described
above. Russian fixed/mobile and external authenticated tunnel acceptance remain open.

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

## Client migration follow-up: publication verified, devices not migrated

The owner subsequently requested completing migration of every client. Read-only
inventory and bounded subscription GETs checked **all16 enabled identities** through
both loopback12096 and public HTTPS. The standard URI subscriptions matched after
excluding only the existing randomized REALITY `sid`: **85 published entries**, of
which79 were interpreted VLESS/Trojan/WireGuard profiles and6 opaque `vpn://` import
entries preserved and compared without rewriting. The latter initially stopped a
strict parser; no configuration mutation was attempted during either failed parse.
All seven affected identities really receive encrypted alternatives in their public
subscriptions. This closes the standard URI **publication** gap, not device refresh,
JSON-subscription validation or Russian fixed/mobile tunnel acceptance.

Before audit GETs, runtime metadata was privately captured. Six affected identities
have10 registered HWID/device rows; the seventh has no registered-device inventory.
These are registrations, not ten proven unique/current/online devices. Stored
traffic rows did not establish per-inbound encrypted use. Every audit GET carried
`homelab-vpn-migration-audit/1`; it may advance native `last_sub_fetch` and MUST NOT
be counted as a human/device refresh. No HWID was submitted, none was provisioned;
the affected registered-row count remained10 after the audit.

Managed-node checks found no conventional Xray/sing-box client service/config on
socrat-0. On socrat-3, Happ is installed: saved selected port32053, TUN preference
false, happd active with NET_ADMIN/NET_RAW excluded and NoNewPrivileges. No Happ
loopback proxy listener was running. Its binary subscription store and GUI settings
were **not edited**, GUI was not launched and routes/proxy state were not changed.
Saved selection is not functional acceptance; the TV WireGuard profile is out of
this migration and remains untouched.

**Actual blocker:** there is no proven control channel to the affected end-device
applications and no user/device acceptance. A server cannot change a cached
`security=none` URI into a REALITY client configuration. Removing publication or
closing32063 before those applications switch could disconnect users. No such
write/retirement was performed. Completion needs managed client access or actual
subscription refresh plus working encrypted connection from the affected devices;
missing/extra devices also need inventory. Do not report this migration complete.

Final semantic configuration still matches the accepted target-only snapshot;
no temporary tokens remain. Private publication bodies, pre-audit runtime metadata,
per-record migration evidence and honest incomplete receipt are under
`/var/lib/homelab-vpn-hardening/migration-client-audit-20261108`,0700/0600. Never
publish URLs, subscription IDs, client credentials, hardware identifiers or bodies.

## Owner-coordinated refresh: subscription migration applied

The owner clarified that they will tell users to refresh their subscriptions; remote
control of every application is **not** a prerequisite for withdrawing plaintext
publication. The following native change is now applied: TCP32063 remains enabled,
but **`excludeFromSub=true`**. Only this field changed. No listener/client/host/binding
was deleted and no key, UUID or subscription URL changed.

`scripts/vpn-subscription-migrate.py` previews by default and requires fresh machine
session and configuration hashes, pinned versions/pod, native backup, full config
preimages and publication proof before the one native inbound API update. Before
and after, **all16** enabled subscriptions were fetched through both loopback and
public HTTPS, in **both URI and JSON formats**. Matching publication checks removed
only randomized REALITY sid/shortId; opaque vpn imports were preserved, not decoded
or rewritten. Exactly **7 plaintext entries disappeared**, leaving **78 URI entries**.
All other URI profiles and all remaining JSON configs are unchanged. Each affected
identity retained a published REALITY alternative. The existing synthetic64KiB
REALITY acceptance from the target phase remains protocol evidence, not a claim
that each end device has refreshed.

The first fresh session stopped **before any publication write** on JSON population
validation: Xray26/3x-ui3.11 uses flat VLESS settings (`address,port,id`) rather than
legacy `vnext`. Every machine credential was cleaned and original config preserved.
A regression now covers both shapes; retained private JSON was validated offline
before creating the next separately named session. That session completed; no
uncertain write or failed state was replayed. New local scoped total: **64 tests
+6 subtests passed**. All temporary tokens removed, original users/settings/token
rows matched native backup; pod Ready/container restarts0, all three REALITY
fallbacks still pass verified TLS1.3/H2. Native Xray child reload is expected.

**User action:** refresh the existing subscription, then select an encrypted profile
if the app does not choose one automatically. No new subscription URL or client key
is needed. The withdrawn32063 profile is no longer available to new imports or
refreshes. Already-cached clients may still use the retained listener while users
update. Only after the owner confirms refresh/working connections should32063 be
disabled; no expiry deadline or device acceptance has been invented. This is completed
**server publication migration**, not completed end-device refresh/legacy retirement.

Private accepted evidence:
`/var/lib/homelab-vpn-hardening/vpn83-20261108-subscription-final/{receipt.json,publication-acceptance.json}`,
full URI/JSON before/after bodies, native backup and credential-cleanup receipt.
Keep it0700/0600. Audit GETs may change last_sub_fetch; they are never device refresh.
Raw backend guards, Russian vantage acceptance and IP-ban resilience are unchanged.

## Public raw-backend guard: applied, persistent and functionally accepted

Fresh source counters before external tests showed12096 only on loopback/wg-socrat,
32087 only on those same interfaces, and zero `other` packets on both. All original
16 standard URI+JSON subscriptions already used working public HTTPS. Workstation
baseline TCP connections confirmed that both literal public raw ports were open.
These bounded test connections are known generated observations, not consumers.

A separate owned table **`inet homelab_xui_backend_guard`** now returns established
connections and resets new incoming TCP12096/32087 **only on eth0**. It is an INPUT
base chain priority-6, default accept. No forward/NAT/SSH/443/UDP/WG/AWG/NetBird,
other firewall table, TV profile or panel guard was changed. The ACCEPT-only audit
table is still present separately; it is not the enforcing mechanism. The public
interface/IPv4 were freshly checked. No guessed overlay source allowlist was used.

`scripts/vpn-backend-enforce.py` requires fresh session/config/guard approvals,
backup, owned native fixture and complete before/after proof. A fresh own Trojan
identity authenticated through public-hostname **TLS443/WebSocket**, certificate
verification enabled, and downloaded65536 bytes before guard installation. After
installation, another explicitly named own fixture downloaded65536 bytes through
the same TLS443 path (twice during existing-rule acceptance). Entire original16
URI+JSON subscriptions still match backend/public and their pre-guard versions;
fixture subscriptions are excluded from that original-population comparison.
No human keys were used. Every fixture and temporary machine token was deleted.
All original16 identities/85 database bindings and proxy config remain unchanged;
publication still contains78 entries because32063 is excluded.

The first preparation stopped before a rule write when the extra synthetic
Trojan-only JSON subscription had no generated config. Comparisons now explicitly
cover original identities and do not mistake the intentionally limited fixture for
an original subscriber. The next attempt installed the guard once; strict readback
then stopped because nft1.0.6 represents `ct state established` with `op: in`, not
`==`. **No rule replay or flush**: full exact AST validation was corrected/tested,
and interrupted state finalized by readback with zero repeated rule writes. A fresh
session accepted the already installed guard and installed persistence; it did not
reinstall/reset the live rules or counters.

External workstation probes now receive **TCP resets on both raw ports**, while
443 presents verified TLS1.3. The owned deny counter increased with those probes.
Local subscribed paths, public subscriptions and authenticated Trojan443 remain
working. `/usr/local/libexec/homelab-vpn-backend-guard/` holds root-owned code and
inventory helper; `homelab-xui-backend-guard.service` is active+enabled and validates
or installs ONLY the exact owned table at startup. It does not flush the firewall,
restart K3s/nodes or remove the guard when stopped. **Reboot was not performed and
boot recovery acceptance is not claimed.** Runtime mode remains Kubernetes, watchdog
healthy/not inhibited, four nodes Ready.

Private proof: `vpn83-20261108-backend-final` (pre-rule tunnel and interrupted
readback), `vpn83-20261108-backend-accept` (post-rule full functional acceptance,
original config, persistence and cleanup receipts), under
`/var/lib/homelab-vpn-hardening`. Workstation negative-control receipt is private
`/tmp/netbird-tunnelblick-safe/vpn83-external-guard-proof.json`.

## Actual home fixed-WAN protocol acceptance

A new ephemeral identity, quota10MiB and expiry20min, was bound only to32053 and
Trojan32087 through the supported native API. Own probe configs and a SHA256-pinned
copy of the running Xray26.10.21 binary were transferred using private no-log Ansible
fetch/copy over approved pinned internal SSH, never embedded secrets in process
arguments/environment or posted plaintext machine credentials. TTL API tokens
stayed on the VPS, were never transferred, and were explicitly removed afterward.
The controller uses unconditional VPS cleanup after a successful prepare, even if
the home test fails. Interrupted two-phase work must use private ownership evidence,
not replay fixture/token creation.

On socrat-0 the route to the public VPS is **eno1 via192.168.0.1, not an overlay**.
The directly observed public source matched the approved expected home public IP.
Separate loopback-only, destination-restricted Xray processes successfully fetched
**HTTP200/65536 bytes through VLESS/XHTTP/REALITY32053 and HTTP200/65536 bytes
through Trojan/TLS/WebSocket443**. This closes the available home fixed-path
large-transfer/authenticated-protocol gate, not all Russian networks or a mobile
ISP. It is stronger than the previous same-VPS-only probe. Main routes and resolver
contents hashed identically before/after; no OS proxy/DNS/routes or production
client application was changed. Child processes stopped, private probe configs and
copied binary removed. Server cleanup proved original proxy config/token rows
unchanged and removed own client/tokens. Zero vpn83 fixture/token rows remain.

Code: `vpn-home-session.py` (bounded VPS prepare/ownership-checked cleanup),
`vpn-home-probe.py` (standalone home test). Local scoped result now **71 tests
+6 subtests passed**. Private home receipt:
`/var/lib/homelab-vpn-hardening/vpn83-home-fixed-20261108/receipt.json` on socrat-0;
VPS session receipt under `vpn83-20261108-home-acceptance`. Controller files0700/0600;
local delivered secret configs/binary were removed after cleanup. Audit subscription
GETs remain distinct from actual user refresh; no user/device acceptance invented.

### What is genuinely still gated

-32063 is still enabled but excluded from every subscription. The owner said they
will coordinate refresh, not that refresh/working client connections already
happened. A live legacy connection was observed during this phase; do not infer
abandonment from subscription database records.
- **Blind disable is unsafe:** the active recovery watchdog still requires32063 in
`tcp_endpoints`, `listen_ports` and native-primary port inventory. Retiring it needs
a coordinated source+live watchdog config change under its existing serialization
lock, and monitoring port-list update, BEFORE disabling the native inbound. Never
trigger an unintended fence/fallback, weaken recovery globally, or just stop the
watchdog to hide a false failure. No such retirement write has yet been performed.
- No actual mobile ISP vantage is available. Do not emulate one by disabling the
mandatory corporate VPN, changing routing, or relabeling the home fixed path.
- Destination-IP/prefix/ASN blocking remains outside camouflage's capabilities on
one IP. Independent-ASN/fallback purchase and proxy/infrastructure IP separation
remain explicitly deferred by budget. No immunity or causal TSPU claim.

## Next gated production steps

1. Confirm owner-coordinated refresh and working encrypted client connections,
   then retire32063 with the watchdog+monitoring dependencies corrected safely.
2. Obtain actual mobile-path acceptance when such a vantage is available. Home
   fixed-path VLESS/REALITY and Trojan64KiB acceptance is already complete.
3. No more plaintext API credentials are needed from the owner. Use a new unique,
   short-lived native session only when the next approved operation is ready.
4. Reboot/fallback DR acceptance remains separate: do not reboot nodes, fence K3s,
   flush firewall rules or claim recovery from enabled unit state alone.

Scoped local checks at this checkpoint: **71 tests +6 subtests passed**, including
panel guard/IP-migration regressions and42 dedicated hardening/session tests. CI
runs only offline safety, with no infrastructure credentials. Not the full repo suite.

Private final evidence: `/var/lib/homelab-vpn-hardening/vpn83-20261108-target-final`,
including `receipt.json`, `target-acceptance.json`, before/after64KiB proofs, proxy
snapshots, native backup and credential-cleanup receipt. Keep all private. The first
aborted session is retained separately under the `target-main` directory.

The issue remains open. Public backend denial and the available home fixed-path
acceptance now passed. Plaintext retirement, mobile acceptance, reboot/DR acceptance
and destination-IP-ban immunity are not completed or implied. No new VPS/IP, image upgrade, TV/WG/AWG peer/config change,
Tunnelblick/global DNS/route change or NetBird change occurred.
