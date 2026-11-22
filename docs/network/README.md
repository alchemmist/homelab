# Cluster network

| What are you trying to do? | Start here |
| --- | --- |
| Reach a private cluster address as an administrator | [NetBird clients and routing peers](netbird/README.md) |
| Use the standalone recovery path | [WireGuard administrative access](wireguard/wireguard-admin-access-plan.md) |
| Trace a public request into the cluster | [Authoritative DNS](public-entry/public-dns.md) and [HTTPS ingress](public-entry/public-ingress.md) |
| Route an application's outbound requests through a VPN | [Service VPN egress](vpn-egress/service-vpn-egress.md) |
| Recover the VPN used by clients | [VPN failover](vpn-egress/vpn-failover.md) |
| Look up a router address assignment | [LAN static mappings](lan/router-static-mappings.md) |

The dated checkpoints below describe the network at the time of each change; use the task guides above for operating instructions.

## Application egress: owner clarification 17Nov2026

`wg-socrat` is VPN-as-infrastructure. For an application's foreign access, create
a separate service-client in 3x-ui and use its subscription with a standard VPN-client
in the Pod. Do not do SSH-egress toNL and do not change the node's default route. Implementation and
checks: [VPN-as-service](vpn-egress/service-vpn-egress.md). The network history below is kept;
this clarification does not change the existing Moscow→NL infrastructure transit.

# Network and access: current VPN cut 9 November 2026

## Current transport — 10 November 2026 (supersedes the earlier separate WG)

The user's Moscow relay is now **Pod `vpn-transit` on socrat-4** under Argo;
on a real failure — an independent fenced systemd fallback. Both use the same
Xray and config. The shared `wg-socrat`: Moscow10.250.0.40→NL10.250.0.2; the separate
`wg-vpn-transit` is stopped/disabled on both nodes, keys/configs archived.
Management51832UDP/51840TCP stays a separate systemd-relay, independent of the Pod.
DNS:.40:53→.2:5354, the old dnsmasq.2:53 was untouched. Only machine.40 is excluded from
the old private-web443 DNAT; the human/admin ACL was not widened. Trojan allows
only mesh.40/32 and the exact health-loopback127.0.0.1/32.

The real timer automatically restored the native relay after stopping only
the Moscow worker-agent and its relay-container; then the standard failback returned the Pod.
All five HOME profiles were accepted into Pod/native/fallback and **after the separate WG was
removed**; 17 clients/91 bindings/subscriptions84URI/77JSON/keys preserved, fixture cleanup
confirmed. Cluster:3 healthy voters/hashKV equal revision17514049,5Ready/noMemoryPressure.
134 tests+14 subtests, new private archives2/4 off-host SHA verified.
This is not a zero-downtime rollout: the TIME_WAIT guard, management source IP and
Pod bind-capability were fixed; do not hide errors/short unavailability, do not attribute
the native-fallback probe results to the first failed Pod. [Details and operations](../records/handoffs/vpn-mesh-runtime-20261110.md).
API loss while the relay works does not trigger a switch; native is sticky until an explicit
failback. Mobile/AWG/full DR/reboot/HA are unproven. The subscription/public entry are unchanged,
Mac/Tunnelblick/default routes were not changed. Do not replay the preparatory applies.


## Current: production VPN through Moscow, 9 November 2026

**Clients/HOME → Moscow91.189.82.238 → NL109.120.141.60**. The subscription URL
`vpn.alchemmist.xyz` is unchanged; update the existing subscription, not the account/keys.
All three DNS-writers publish the static Moscow VPN A record without NL fail-open. Native
Hosts7/7 updated:17 identities/91 bindings preserved,32063 disabled. Subscriptions of all
17 clients:84 URI/77 JSON, ordinary DNS/valid TLS, no old NL endpoint.
After recovery, three VLESS/REALITY, Trojan and WG were verified from HOME:200/65536B/
control hash, a separate HTTPS exit-check=NL. UDP32…8192B through the real encrypted
inter-server channel was also verified; this is not authenticated AWG/mobile.

HOME0/3 management WG and HOME1 pinned-TLS/GOST go through Moscow; the known NL
DNS/HTTPS/VPN flows on HOME0/1/3 are redirected by scoped persistent nft DNAT.
Not a global exit node, Mac/default routes/DNS settings were not changed. Private
DNS:Moscow10.250.0.40:53→NL10.251.4.2:53. NS1 HOME and NS2/glue NL are kept.
The NL WAN raw VPN is closed; only the Trojan HTTP path on shared443 allows the Moscow
private10.251.4.1/32 and the exact loopback127.0.0.1/32 for the standard health-check.
Public403/private101, spoofedXFF does not help; portal200/LMS303/Argo200 are kept.
The same gate was set/verified in the native Caddy fallback.

**Do not hide the incident:** the initial ACL let local health through and caused a
watchdog fallback/NL K3s stop. Fixed with a loopback exception, the checks and
watchdog were not disabled. The standard failback of the original member without reset/replacement;
a 160MB Raft catch-up took3m45s, the bounded start timeout180→600s. After recovery:
3 healthy voters/common leader/hashKV equal (revision17449598),5Ready/noMemoryPressure,
all five transports and 17 subscriptions re-accepted, watchdog healthy/fallback off.
The Moscow socrat-4 is agent-only10.250.0.40, the bootstrap NoSchedule is kept,
not a control-plane/etcd/ordinary heavy worker. The four human admin routes were not widened.

Backups of five nodes plus a post-recovery supplement — private/off-host/SHA verified;
history/old recovery receipts are kept.126 tests+14 subtests passed — an acceptance cut,
not a continuous healthcheck. Mobile/Happ interactive, authenticated AWG, full DR/
chaos/reboot and end-user IP enforcement preservation are unproven. Do not promise HA/TSPU immunity.
Details and custody: [production runbook](../records/handoffs/vpn-production-cutover-20261109.md).
Historical staging: [Moscow bootstrap](../records/handoffs/moscow-vpn-transit-20261109.md).
Do not re-run migration/prepare/apply: fresh preimage/CAS, uncertain→investigate.

## Historical human ingress acceptance, 7 November

# Network and access Socrat: current contract as of 7 November 2026

## Current boundary — 7 November, removal of external auth gates

11 obsolete Authentik Applications were removed (including the old Kuma bookmark-card)
and 10 Proxy Providers; outpost assignments were removed.10 native OIDC Applications,
their UUID/client credentials/callbacks/policy bindings are kept. n8n,3x-ui, Kuma
and Syncthing use their own login; SearXNG and published SPI artifacts
are public without Authentik and NetBird. Reader allows only GET/HEAD, checks the
manifest/hash and serves safe types inline. [Contract and boundaries](../auth/applications/native-browser-auth.md).

Re-acceptance after the socrat-2 recovery: **82/82** public checks
on HOME and VPS, an ordinary TLS check without disabling verification. All4 nodes Ready;
socrat-2 Ready from17:55:34UTC7 November. All8 affected Argo apps Synced/Healthy.
The old xui gateway Application/Deployment/Service/ConfigMap and Pod are absent; no
force-delete was needed.10 native OIDC registrations/providers/bindings and
the kept icon fields are unchanged; Proxy Providers0. A published artifact was
verified through both entries: anonymous GET/HEAD/206, manifest/SHA-256, inline,
PUT/POST/PATCH/DELETE405. [Acceptance](../auth/applications/native-browser-auth.md#recovered-vps-final-acceptance).
This is a protocol acceptance, not a new per-person login check.


This is the current summary of the network changes, not an instruction to repeat the migration. It replaces the old claims "Grafana only through WG", "anonymous Viewer is kept", "the Mac needs resolver overrides", "the TV connects the internal WG" and "Kuma still awaits entry separation". The transport/negative-case acceptance refers to 5–6 November; on 7 November the
documentation and the owner map were updated, the full VPN/external browser test was not repeated.
The old acceptances remain history; a fresh audit is needed before any new application.

**The user's internal network is NetBird**, not a manual socrat-wg profile.
The names `wg-socrat-*` routes and the `wireguard-internal` resource are real remaining
identifiers; do not rename them automatically. The inter-node WG and the independent
emergency WG below are kept deliberately. Current logins/first login:
[identity-current-state.md](../auth/authentik/operations/identity-current-state.md).

## 1. Addresses, transport and inviolable boundaries

| Purpose | Current state |
|---|---|
| Home public entry | `109.173.40.247` |
| VPS socrat-2 / second public entry | **`109.120.141.60`** |
| Old VPS IPv4 | `176.98.185.59` — history only, not a working endpoint |
| Internal addresses of nodes 0 / 1 / 2 / 3 | `10.250.0.1` / `.3` / `.2` / `.5`, ordinary SSH `2222` |
| Primary administrative transport on the Mac | **NetBird**, only the four agreed `/32` |
| Independent Mac recovery | Standalone WireGuard, usually off; owner client `.4` |
| Mandatory working VPN on the Mac | Tunnelblick, do not disable or reconfigure |

The inter-node `wg-socrat` remains a separate Kubernetes/node network: moving human access to NetBird does not replace it. Since 2026-11-10, by the owner's instruction, ordinary SSH aliases 0/1/2/4 use the public SSH endpoints; the non-public 3/5 go directly over internal addresses via NetBird, ProxyJump none. Pinned host keys are preserved. See the current table in docs/auth/host-access/mac-private-ssh.md. Do not fix SSH by deleting known_hosts, weakening TLS/host-key checks or changing corporate routes.

During acceptances Tunnelblick kept the same process (then PID 40769). This is historical proof, not a permanent PID for future commands: reconcile the actual process before new actions. Do not change the Mac's global DNS, corporate resolvers/routes and VPN profiles; do not use cache flush/HUP.

## 2. Migration of socrat-2

The new IPv4 is reflected in source/runtime, the public zone and REG.RU glue, WG recovery/TCP transport, ingress/probes, NetBird relay/STUN and webhook. The provider gateway **`176.98.185.1` is kept deliberately**: this is not the old VPS address, a mass replacement of all `176.98.185.*` is not allowed.

In 3x-ui seven primary and seven legacy `hosts.address` rows were fixed with backups and whole-table invariants. Acceptance: 15 plain subscriptions / 79 links (74 new VPS, 5 others, 0 old VPS), 15 JSON subscriptions and authenticated Trojan TLS/WS. Do not publish subscription contents, SQLite, keys and receipts. The old backups are kept; do not declare an incomplete rootfs archive a full backup.

STUN is set to the new address, open TURN is not enabled. The webhook was verified on the new endpoint with an empty pending queue. The regional unavailability of the old VPS was reproduced separately; the TSPU theory is unproven.

Sources: [VPS migration](../records/handoffs/vps-ip-migration-20261105.md), `ansible/scripts/vps-ip-migration.py`. Reconcile the actual CLI/runbook, do not run from memory. Applying migration actions: audit first, fresh exact hash, lock, private backup/receipts, stop on an uncertain write. Do not reboot nodes/K3s/DB and do not do a blanket firewall flush.

## 3. NetBird: primary access and separate rights

On the Mac NetBird DNS is off: `disableDns=true`, `disableClientRoutes=false`, `disableServerRoutes=true`. Only the four `wg-socrat-*` routes to the node addresses `/32` are selected; no exit route, LAN capture, pod/service CIDR or corporate network. Fresh SSH to all four nodes and the actual transport were checked, not only a green client status.

Builtin All does not hand out DNS, including to future peers. **The automatic user/device approval requirement is off**; personal Authentik/MFA and group-restricted admission are kept. This is not an All-device policy and not an automatic grant of app/Linux/Kubernetes/admin rights. The OIDC/JWT group mapping uses `profile`; the existing pilot is kept.

Lifecycle: `ansible/scripts/netbird-access.py`, `ansible/playbooks/netbird-access.yml`, [onboarding](netbird/clients/netbird-administrator-onboarding.md). There is scoped grant/revoke/offboard, protection of owner/service identities, a fresh hash and private snapshots. Temporary grant/revoke/no-op/deletion were verified; the bootstrap admin is limited, the old PAT does not grant the former admin access. Do not manually create a fake JWT group with the same name.

Admission to an application, a NetBird policy, a Linux SSH key, sudo and a Rancher/Kubernetes/app role are independent decisions. Removing a group does not guarantee instant closing of old sessions/SSH forwards. The first real new person with their own MFA/device enrollment remains a separate acceptance: temporary fixtures do not replace it.

Recovery WG was verified through the new VPS and all four nodes, including worker `.5/32` and the return path owner `.4`. After the test WG was turned off, NetBird restored. The outdated assistant peer `.6` was revoked; a possible cosmetic GUI record is not an active grant. Phone `.7` and the previously disclosed phone key require a separate owner/rotation decision, they are not revoked incidentally.

More: [NetBird](netbird/README.md), [Tunnelblick compatibility](netbird/clients/netbird-tunnelblick-coexistence.md), [fault-tolerance boundaries](netbird/infrastructure/netbird-independent-access.md). A cold start without management failed earlier; management/Authentik HA and full DR are unproven. Do not remove the independent recovery.

## 4. Kubernetes: a transport mark does not give a pod permission

A cross-node NetworkPolicy bypass was found: the NetBird mark `0x1bd22` overlapped with the kube-router/CNI bits `0x10000`/`0x2000` and led to an allow `0x20000`.

On all nodes a strictly owned nft guard `inet homelab_k3s_overlay_marks`, owner `homelab:k3s-overlay-marks:v1`, was installed: prerouting priority `-175` clears a non-zero mark only on flannel/VXLAN ingress, when **both** addresses belong to the pod CIDR `10.42.0.0/16`. NetBird rules and other traffic are not rewritten. The boot oneshot runs before K3s; stopping the oneshot deliberately does not remove the guard.

Source/procedure: `ansible/scripts/k3s-overlay-marks.py`, `ansible/playbooks/k3s-overlay-marks.yml`, [runbook](../platform/kubernetes/k3s-networkpolicy-overlay-marks.md). Whole-fleet preflight → serial atomic apply, private receipts, nft 1.0.6 compatibility. NetBird/workloads were not restarted.

16 ordinary and 16 forged wrong-namespace gateway-label probes were blocked across different nodes, PodIP/ClusterIP and ports 9000/9001; the real gateway read a consistent fixture, the console stayed closed. Fixtures were removed. This is a verified specific boundary, not a promise of universal protection from any root/cluster-admin. Repeat the audit after network/node upgrades.

## 5. Ordinary public HTTPS: access is not equal to a role

Public DNS does not mean public backend ports. Selected human HTTPS entrances are published; DB, storage/telemetry APIs and internal protocol ports are not opened automatically.

| Service | Final contour |
|---|---|
| Grafana | Native OIDC auto-login, anonymous org access **off**; owner → GrafanaAdmin, `app-grafana-editor` → Editor, others admitted → Viewer |
| Traffic light `socrat-traffic-light` | Only this dashboard is available via native public sharing without login at `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>` |
| Search | Public SearXNG, without Authentik/NetBird |
| `llm.socrat` / `litellm.socrat` | Direct aliases to apps with native OIDC; machine entrances/credentials kept |
| Rancher | Native OIDC/roles; public local-password mutations are blocked, bearer/agents/WebSockets/private recovery kept |
| Grafana MCP | Separate bearer, read-only native identity; missing/invalid token 401, not an interactive MFA gate |
| Wiki | Public read, native OIDC/roles for writing; `/mcp` is protected, forged WG/identity headers do not give a bypass |
| Syncthing node0 `/sync/` | Standard GUI login, enabled in advance before removing the empty BasicAuth wrapper; the prefix is removed; API key/devices kept |
| Syncthing node1 `/sync/` | Explicit **410 gateway-only**, not another Syncthing device and not a fake GUI |
| Kuma status | Anonymous `/status/socrat`, status/heartbeat APIs, assets/badges and native-token push kept |
| Kuma admin | `kuma.socrat.alchemmist.xyz`: only native Kuma login; the public status-only filter is kept |

The ordinary app role groups `app-grafana-viewer`, `app-grafana-editor`, `syncthing-web-admins`, `uptime-kuma-web-admins` were created empty; temporary test memberships were removed. Do not assume granting these rights to new people and do not add them to the owner group for a login. Machine consumers must keep their original API entrances/tokens, rather than move onto an MFA alias without separate compatibility.

Grafana Viewer/Editor were verified with personal temporary password+TOTP fixtures: read, Editor folder create/delete, admin API denial for both. Fixtures were removed; the old Grafana proxy gate was removed after native acceptance. The public policy blocks BasicAuth/`POST /login`, metrics/debug, keeping bearer API/WebSockets/private recovery. The Grafana Deployment and the shared Prometheus/Collector were not restarted by this closeout.

The Kuma public Socket.IO and unknown admin APIs are closed; the old admin/login/settings/dashboard/manage-status-page URLs redirect to the admin host. On the admin host, WebSocket 101, the Socket.IO namespace and denial of native `getSettings` without a native login were verified. You cannot simply close the entire shared socket and consider the status/machine paths kept.

The Syncthing BasicAuth bytes, process/device identity, keys, config and synchronization were not changed/restarted. A real owner Basic login is a separate optional acceptance; the password was neither borrowed nor reset.

Main sources: `deploy/public-web/services.json`, `publicEntry` in local charts and `deploy/platform/<app>/public-entry` in the existing Argo Applications, `ansible/scripts/public-web-access.py`, `ansible/playbooks/public-web-access.yml`, [public entries](../applications/public-web/public-web-migration.md). Audit/create-only, drift refusal, outpost preservation, private receipts. An Authentik policy denial may be HTML with HTTP 200: assess the actual denial, do not demand a fake transport 403.

### Ownership of public ingress after the 2026-11-07 migration

The composite Application **`public-web-entry` and its chart were removed**. The public entries,
policy proxies and their ConfigMap now belong to the existing Applications:
Grafana → **`grafana`** (after the monitoring split), Rancher → `rancher`, Search → `searxng`,
LLM alias → `open-webui`, LiteLLM alias → `litellm`, MCP → `grafana-mcp`,
Syncthing → `syncthing`, Kuma admin → `uptime-kuma`.

For local charts change `publicEntry` in values; for third-party ones —
`deploy/platform/<app>/public-entry`, connected by an additional source of the same
Application. The Authentik policies/groups stay centralized, native roles and
machine authentication were not changed. Do not create a general ingress Application again.

All 22 resources were handed over without recreation; TLS/access checks are kept.
After removing the old owner, the public regression — **134/134**. This is not a new
browser-MFA/onboarding test. The detailed map, the safe ownership handover and
the LiteLLM hooks boundary: [cluster-deploy.md](../platform/delivery/cluster-deploy.md#public-entries-belong-to-applications--2026-11-07).
The Ingress handoff was completed in `e7fe891`; then the monitoring split `8862770`
handed Grafana to its own app. Do not return the old owner. The current sources
and the unfinished aggregate cleanup: [observability-current.md](../observability/monitoring/observability-current.md).

## 6. Kuma: recovery after an incident, not zero downtime

An application-only restart to close old sockets revealed a mismatch between the Secret and the active SQL password; the application was unavailable. The maximum observed heartbeat gap of an active HTTP monitor — **2072s, about 35 minutes**. The history was not faked, no backfill was done.

The old app password could not be restored. The existing SQL passwords were not reset: a separate `homelab_kuma_app` was created with an exact schema-only grant `` `uptime\_kuma`.* `` (escaped underscore, not a wildcard schema). The old `uptime_kuma` account/grants are kept. The app Deployment uses the new username; the DB Deployment username stays `uptime_kuma`. The MariaDB Pod UID/restart count and the fingerprint of the native Kuma account/auth are kept.

The Secret UID is kept, **the Secret data changed during recovery**; do not repeat the intermediate claim about unchanged credential bytes. The random bootstrap Secret was disabled, the old Argo tracking ownership was exactly removed/keep is kept, the bootstrap guard does not allow confusing the app/DB username. Do not change the DB deployment username or regenerate a live Secret to bypass the guard.

Audit: the maintenance task `kuma-db-account-recovery` (without apply), `ansible/scripts/kuma-db-account-recovery.py`, [MariaDB runbook](../observability/monitoring/uptime-kuma-mariadb.md). Private candidate/before/grants/uncertain/after receipts are kept. On an uncertain write, stop; do not change defaults and do not repeat the recovery blindly. The separate DB was not restarted.

## 7. Mac: the old owned DNS lifecycle fully removed

12 exactly owned `/etc/resolver` files, the wiki restorer script/plist/marker were removed; only `system/xyz.alchemmist.wiki-resolver` was unloaded. Before removal, content/owner/mode/symlinks were checked, with a private backup and a fresh hash. Final audit: operations=0, resolver_files=0, daemon=false.

The global DNS hash and the previous Tunnelblick process are kept; no cache flush/HUP, no global DNS/route/VPN mutations. Native system DNS for the 12 affected/control hosts returned the public HOME/VPS; ordinary DNS+TLS and a clean browser reached MFA without overrides. Internal pinned SSH to all nodes/NetBird kept working, recovery WG was not used.

Source: `scripts/macos-public-dns-cleanup.py`; backups/receipts in the private `/var/db/homelab-public-dns-cleanup/`. Normal Wiki onboarding no longer installs a resolver: the legacy task requires `wiki_editor_client_private_dns_legacy=true`. The default admin WG DNS mode is `none`. Server-side private DNS may remain for other agreed consumers, this is not a reason to restore Mac overrides.

## 8. Television: only public Grafana, YouTube VPN separately

By the user's final decision `xiaomi-tv` was removed through the WireGuard UI together with the config/key on the TV. Its exact public peer `.8/32` was revoked on the three nodes where it existed; the worker already did not have it. All four final audits — operations=0. The inventory and both helper APK no longer create/connect an internal profile.

Only **`alchemmist-tv` for YouTube remained**, without reading/replacing its key/config. The YouTube helper brings it up on demand and waits for VALIDATED. The Grafana helper turns off this global VPN and opens Fully **without connecting the tunnel**. The always-on VPN was cleared; the helper source and `tv-admin.yml` do not return it. Package/component/signing identity is compatible with the existing remote assignments.

The Fully URL — canonical `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`; the exact address is root-private `/var/lib/homelab-grafana-tv-public/fully-url.json`. The temporary **`tv.alchemmist.xyz` was removed** from authoritative A records and the chart; its exact Ingress/Certificate/Secret were removed by UID, not a blanket prune. The DNS/alias final audits — operations=0; this is a historical result. A separate public-web-entry was then removed; the Grafana public ingress/proxy now belong to **grafana**; the Helm release/service
names with kube-prometheus-stack are kept, this is not the old Argo owner.

The server JS/CSS restores a 5px inset, hides the public header/footer and autofits a compacted layout: the native public scene ignores the old kiosk/autofit flags. It is important to take the compacted geometry, not the intersecting raw gridPos. Fully scale 55%, font 75%, empty injectJsCode (no Plus watermark), remote assignments/HDMI and Android Private DNS are kept. The native share does not change the dashboard JSON, refresh 5s and live range now-12h.

A real TV screenshot with live data, a YouTube foreground with **one real VALIDATED VPN network** and a subsequent Fully without VPN were verified. Do not consider `NOT_VPN` in the Wi-Fi capabilities an active VPN. The physical remote/cold start were not re-verified.

Procedures: [TV](../applications/android-tv/README.md), [operational runbook](../applications/android-tv/README.md), `tv-public-dashboard.yml` (URL only). Do not delete the WireGuard app data entirely: the YouTube profile is stored there. Do not destroy private historical backups.

## 9. What is proven and what is still separate

- Final TV/canonical checks: **24/24** verified-TLS forced-routing checks of two IP; the general public-web regression **134/134**, ingress **30/30**, **66 focused tests**, four Ansible syntax checks. This is not the full repository suite.
- Public-web closeout before the TV: **117 passed / 17 subtests**, real scoped MFA/native role tests; count it as a separate historical sample, do not sum the tests into one invented acceptance.
- Forced public routing, a second LAN device and a clean browser do not replace an independent external Internet/provider/device test. An exhaustive every-app/every-role/machine API/WebSocket acceptance was not done.
- The first real new-human NetBird enrollment, owner Syncthing Basic acceptance, independent DR/HA, the long-term compatibility of corporate VPN and the phone-key decision — separately.
- The CI `HOMELAB_DEPLOY_KEY` publickey failure, the unrelated LMS/RustFS Argo drift and the historical adminclient test expectations — are not a reason for a blanket sync/prune or a relaxation of protection.

The closing network/TV commits: `435c70b`, `448f93f` (with the intermediate TV-alias implementation and its subsequent full retirement). The last live state matters more than an intermediate idea. A Wiki update by itself deploys nothing.


## VPS migration recovery — 2026-11-09, fresh acceptance

This supersedes the prior unreachable/ReadyUnknown observation, not its history.
Owner rebooted socrat-2; persistent NEW=109.120.141.60/24, gateway109.120.141.1.
All four nodes Ready; watchdog Kubernetes healthy=true; native fallback inactive.
Management uses owner-authorized direct NEW:2222 with pinned key and /usr/bin/ssh;
old controller wrapper is not private-only evidence and must not be reused blindly.
Do not further alter Mac WireGuard; corporate Tunnelblick/routes/DNS preserved.

Seven stale panel host addresses migrated via native API only, with uncertain-call
readback/reconciliation and no replay.16 identities/85 bindings, credentials,
quotas and disabled legacy32063 preserved; temporary admin tokens removed.
All16 URI subscriptions(78 entries) and JSON(72) match backend/public TLS pinned
NEW, zero OLD. Own temporary HOME-WAN identity authenticated REALITY and
TrojanTLS to literal NEW with HTTP200/65536 bytes each; no overlay/global proxy,
fixture removed. This is NOT mobile/operator acceptance or filtering attribution.

Source d8a5e54 merged normally with upstream SPI extraction and pushed as0642a36;
bot/netbird/traefik-edge/spi-triage naturally Synced/Healthy at that revision.
No blanket sync/prune. Bot runtime webhook env and Telegram destination NEW;
queue2 ->0, existing machine secret/URL/allowed updates retained, no duplicate
mailing command sent. Recipient-level mailing completion remains unproven.
REG.RU accepted ns2-only glue change; **both x.nic.xyz/y.nic.xyz now publish NEW**,
ns1=109.173.40.247 and both NS names unchanged; cached old glue can outlive this.
Public NEW UDP53 authoritative answer and STUN Binding verified.

Still separate: owner phone refresh/connectivity; mailing recipient confirmation;
RustFS manual-sync auth-egress /32 runtime (source changed, app still old revision);
Collector delivery, off-host DR and workstation NetBird LoginFailed. Public
backend eth0 TCP12096/32087 denials preserved (external refused;443 open), priority-6.
NetBird added one nb-host-only accept to that accept-policy chain: read-only proof
shows no public-rule change/no-op semantics; installed exact-table validator stops
on the extra rule, so do not blindly run ensure/rewrite the table. No firewall edits.
Runbook/evidence index: docs/records/handoffs/vps-ip-migration-20261108.md. Focused166tests+21subtests.
