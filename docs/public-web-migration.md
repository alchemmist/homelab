# Public HTTPS application entry migration

Goal: ordinary public DNS and browser Authentik/MFA, without client resolver files
or VPN for web applications. Node SSH, databases, Kubernetes internals and telemetry
receivers remain private. DNS publication is not an authorization boundary.

## Current reviewed entries

| Host | Public admission | Backend authorization retained |
|---|---|---|
| grafana.socrat.alchemmist.xyz | Native Grafana OIDC auto-login, personal Authentik MFA | Anonymous disabled; owner → GrafanaAdmin, app-grafana-editor → Editor, other admitted groups → Viewer; public password/Basic fallback denied |
| search.socrat.alchemmist.xyz | Authentik owner / netbird-internal-admins, mandatory MFA | Search UI, no grant to other admin apps |
| llm.socrat.alchemmist.xyz | Authentik gate with existing Open WebUI admission | Native WebUI identity, roles, chats unchanged |
| litellm.socrat.alchemmist.xyz | Authentik gate with existing LiteLLM admission | Native reviewed-subject OIDC and API keys unchanged |
| rancher.socrat.alchemmist.xyz | Native Rancher OIDC and existing restricted principals, public local-password actions denied | Small policy proxy preserves Rancher agents, API bearer credentials and websockets; private recovery remains |
| grafana-mcp.socrat.alchemmist.xyz/mcp | Existing native MCP server bearer-token validation | Existing read-only tools and fixed Grafana upstream; no health/admin backend ports exposed |
| 0.socrat.alchemmist.xyz/sync/ | Owner / syncthing-web-admins, personal MFA | Existing BasicAuth and original Syncthing device retained; prefix rewrite preserved |
| 1.socrat.alchemmist.xyz/sync/ | Same scoped MFA gate | Explicit 410 gateway-only response; no substitute/new device |
| kuma.socrat.alchemmist.xyz/dashboard | Owner / uptime-kuma-web-admins, personal MFA | Native Kuma authorization/password retained; MFA admission alone grants no native admin rights |

Public entry is owned by each service's existing Argo Application, **not a separate
public-web-entry Application**. For local charts, routes/proxies are templates in
that chart and settings are under `publicEntry` in its values. For externally
sourced platform charts, a small app-specific chart under
`deploy/platform/<app>/public-entry` is an additional source of the **same**
Application. No extra access Application or aggregate chart remains.

| Owner Application | Public resources |
| --- | --- |
| kube-prometheus-stack | Grafana ingress and policy proxy/config |
| searxng | Search ingress |
| open-webui | LLM alias ingress |
| litellm | LiteLLM alias ingress |
| rancher | Rancher ingress and policy proxy/config |
| grafana-mcp | MCP ingress |
| syncthing | Both GUI ingresses and policy proxy/config |
| uptime-kuma | Kuma admin ingress and policy proxy/config |

Shared Traefik, Authentik and cert-manager remain platform components. Authentik
admission policy stays in `deploy/public-web/services.json` and its audit-first
identity tooling; native authorization is not duplicated into Helm charts.
Resource names, namespaces, TLS Secret references and existing access restrictions
are deliberately preserved. Identity-gated ingress resources may remain in the
`identity` namespace but are tracked by their owning service's Application.

VPS Traefik includes cattle-system and cattle-monitoring-system in its namespace
list. Certificates are independently issued by cert-manager, not copied between owners.

Grafana now uses its own native OAuth identity, not the retired outer proxy gate.
The bounded `grafana-public-sso.py` helper audits the existing OAuth/secret source,
requires a fresh hash for an application-only rollout, and rejects unreviewed
admission/role drift. Authoritative values are in
`deploy/identity/grafana-oidc-values.yaml`. Existing native admin recovery and
bearer APIs are preserved; the public bridge blocks local password/Basic fallback.
No whole monitoring-stack sync or Collector restart is part of this change.

## Identity ownership and operations

`deploy/public-web/services.json` is an exact host/upstream allowlist.
`scripts/public-web-access.py` is create-only/audit-first. It verifies bound
mandatory MFA; preserves the existing app groups; creates separate proxy providers
and applications; adds their group bindings; preserves all existing embedded
outpost provider assignments. No users, native roles, passwords, OAuth secrets or
existing application settings are replaced. Existing gate/provider/binding drift
stops, rather than silently broadening or overwriting it.

Use `ansible/playbooks/public-web-access.yml` with the existing controller SSH and
become credentials. Default is audit. For creation, explicitly supply
`public_web_apply=true` and `public_web_approve_plan_hash=<fresh audit hash>`.
Private before/after snapshots and receipts are under
`/var/lib/homelab-public-web-access`; partial/uncertain runs block rerun pending
manual reconciliation. Never run the broad Authentik foundation configurator for
this migration. Gate readback must converge BEFORE public ingress activation.

## Remaining scope / acceptance boundaries

- Existing public chat, LiteLLM canonical host, Wiki, n8n, Harbor, Argo and x-ui
  need regression checks, not duplicate competing ingress ownership.
- Syncthing real-owner BasicAuth/browser acceptance can supplement the completed
  scoped-MFA/prefix/backend checks. Never start another writer or impersonate the
  gateway-only node as a real device.
- Existing local resolver overrides must not be called unnecessary/removed until
  the affected hostname has accepted public routing. Do not touch corporate
  resolver files, Tunnelblick settings or flush global DNS during its required
  session. Clean-client verification is distinct from owner-Mac verification.
- RustFS console/S3 routes and SPI switching remain separately gated by their
  rollout authorization and acceptance; do not piggyback them on this chart.
- Test each public address with valid TLS, no cookies, forged identity headers,
  invalid tokens, native role checks and applicable API/websocket behavior.
  Tests from this Mac forced to public destinations are not independent external
  vantage tests. Do not declare all onboarding complete from anonymous redirects.

## Historical first-batch acceptance — 2026-11-06

The following first-batch results are retained as history; the closeout below
supersedes its then-outstanding Grafana/Syncthing/Kuma/Mac items.

First batch is **delivered**, not just rendered: public-web-entry and traefik-edge
were Synced/Healthy at `63650a15edbacfec09ad2cc952332d3fd96b96f8`.
All six hosts have both public A addresses and no AAAA according to Google DoH.
TLS verified at both entrances. `scripts/check-public-web-entry.py` passed
**54/54** anonymous/forged-header/invalid-token checks. It reads the existing
migration-owned address inventory; repeat `--address` twice outside the repo.
Both public destinations from the Mac used the unchanged work VPN interface,
not NetBird private routes. A second LAN host also passed; that second run is
not an independent Internet vantage or proof of access from every provider.

A fresh ordinary observer completed password + personal TOTP enrollment + proxy
OIDC at the public VPS Grafana entrance. Its search API read succeeded and native
Grafana admin settings were denied. The same authenticated observer was denied
at the Search gate because it lacks the required group. Authentik renders that
policy-denial HTML with **HTTP200** at its authorization endpoint; acceptance
checks the denial state and absence of the Searx backend, not a fictitious
transport 403. All temporary test identities were deleted. Initial smoke-driver
failures were protocol mistakes (combined identification/password form and tuple
handling), not justification to weaken MFA or app policies.

MCP read-only acceptance on BOTH public entrances: missing/invalid token401;
existing valid token initialized a session and listed **20 tools**, with no write
tools. No token was printed or rotated. Existing public hostname regression:
**30/30 HTTPS checks passed**. Identity gate audit subsequently returned
**operations=0**. Tunnelblick retained its original process; NetBird4/4 and
standalone recovery WG off.

**Not complete:** owner Mac resolver cleanup; Syncthing public GUI/path migration;
full Uptime Kuma administrative SSO boundary review; exhaustive authenticated
acceptance of every app/role and clean-device browser acceptance. The existing
Syncthing service for node0 answers at its root but not `/sync/`; the node1 GUI
service failed connectivity from the controller. Do not start/reconfigure a
Syncthing writer or expose an unreviewed fallback to make this appear complete.
Local DNS overrides are still retained, especially during the mandatory work-VPN
session. New clients need no resolver files for the six delivered public hosts.

Focused source/ingress/NetBird regression: **175 passed, 4 skipped,
139 subtests passed**; public-web playbook syntax check passed. Native-route
Helm guards reject wrong namespace/service/port/path instead of treating a
`native` label as proof of backend authentication. Portal Grafana/Rancher text
was updated without changing their provider, policy or account fields.


### Rancher local-password boundary

Readback found only generic OIDC and local Rancher authentication enabled. Since
local recovery must not become a public password-only MFA bypass, the public
Rancher ingress uses a dedicated nonroot policy proxy in cattle-system. It denies
POST/PUT/PATCH/DELETE to the normalized `/v3-public/localProviders` path family,
strips method-override headers, and otherwise preserves native API authorization,
websocket upgrades and OIDC. The existing private gateway still reaches Rancher
directly for owner recovery. No Rancher config, password, principal or role is
changed. Stock nginx stable-alpine is pinned to a TLS-fetched OCI index digest
whose body SHA256 matched Docker-Content-Digest. The proxy has no mounted secrets
or service-account token and bounded CPU/memory/tmp. Logs contain status/method/
duration only, never URI, cookies or token-bearing query strings. Argo sync waves
wait for the proxy before switching the existing public ingress; no second
competing Rancher hostname owner is introduced.


Rancher policy activation completed at `f11a7ce4c6c9091a25cab825eee9201bb71c7c08`,
public-web-entry Synced/Healthy. Proxy1/1; **58/58** negative public checks passed,
including local-password POST403 on both entrances and normalized double-slash
paths. Native `/ping`200 on both entrances; protected APIs remain401. Private
Rancher via `10.250.0.3` still serves the UI and sends an empty local-login POST
to native validation401, not the public403 rule. The private `10.250.0.1` entrance
timed out during this check; no before/after causal claim is made for that legacy
route. Neither private gateway was reconfigured. Public users need neither.

The Search backend also passed a positive public test after the same temporary
ordinary user received the non-superuser internal-admin group; negative admission
was checked first. No NetBird device enrollment, native administrative role or
owner-group membership was used. The fixture identity was deleted afterward.

Final expanded focused run (including identity contracts): **190 passed,
4 skipped, 139 subtests passed**. Final identity audit: operations0/changed0.
No Grafana/Collector restart was performed. The completed temporary canary
executable is removed; private run receipts and diagnostics are retained.


## Four-item closeout — 2026-11-06

- **Grafana:** native personal identity and MFA/auto-login accepted with fresh
  ordinary Viewer and Editor fixtures. Viewer read, Editor temporary-folder
  create/delete, and admin-API denial were checked. Both fixtures were deleted;
  no human received owner membership. Existing owner-admin mapping is preserved,
  not claimed as a new real-owner browser login. The obsolete owned Grafana
  proxy application/provider/outpost assignment was retired only after acceptance.
- **Syncthing:** `/sync/` and prefixed noauth-health work through a loopback-only
  clone with temporary Basic credentials; production BasicAuth bytes were checked
  unchanged. A fresh MFA identity with only `syncthing-web-admins` reached the
  production BasicAuth401 on node0 and explicit gateway-only410 on node1, and
  was denied Kuma admission (Authentik denial HTML is HTTP200, not transport403).
  The clone starts nginx only, never a Syncthing process. No device enrollment,
  identity/key/config rewrite or synchronization restart was performed. A real
  owner's existing Basic password was not replaced or borrowed for the fixture.
- **Kuma:** public status/assets/status-page/heartbeat APIs remain accessible;
  public Socket.IO, metrics and unknown administrative APIs are closed. Old
  admin paths redirect to the MFA-protected admin host. Fresh scoped MFA passed
  native WebSocket upgrade101; native `getSettings` denied the MFA-only identity.
  This check was repeated after recovery. Native passwords/accounts remain a
  separate authorization boundary, not a claim of native OIDC support.
- **Mac:** native macOS administrator consent applied the exact cleanup plan.
  Twelve owned resolver files, the owned wiki restorer/plist/marker were backed
  up and removed; only `system/xyz.alchemmist.wiki-resolver` was unloaded.
  Global DNS hash and original Tunnelblick process40769 were unchanged before/
  after; no cache flush, HUP, VPN command or route change was made. Final cleanup
  audit has operations0, resolver_files0 and owned_daemon_loaded=false. Native
  system resolution for 12 affected/control hostnames returned only the two
  public entrances; ordinary DNS+TLS requests reached their gates. Four fresh
  pinned internal SSH connections passed, NetBird peers4/4. Recovery WG remained
  unused. Legacy Wiki DNS installation is now explicit opt-in and WG client DNS
  defaults to none, preventing normal onboarding from recreating the chain.

**Kuma recovery incident:** the application-only restart exposed a Secret/live
DB credential mismatch and caused application unavailability. The observed
maximum recent heartbeat gap on a checked active HTTP monitor was **2072s
(about 35 minutes)**; this was not zero downtime and missing scheduled checks
were not fabricated/backfilled. No MariaDB restart occurred (original Pod UID,
restart count0). Existing native-user/auth fingerprints matched before/after.
The old DB account/grants/password were not changed. A new service account
`homelab_kuma_app` was created with the original exact schema-only grant; the
existing Secret was reconciled to its validated application credential and the
validated live root credential. No credentials are in Git or public logs. See
[the DB runbook](uptime-kuma-mariadb.md) for private receipts and audit-only tools.

Final live negative matrix: **134/134** against both public entrances, including
forged identity/forwarding headers, invalid tokens, private/native admin paths,
new gate paths, status read endpoints and denied public Socket.IO. Public status
also rendered correctly in an isolated browser context (its existing partially-
degraded application summary is not asserted globally healthy). Gate lifecycle
audit operations0/changed0; service-account privilege/credential audit operations0.
Focused regression: **117 passed, 17 subtests passed**; three relevant Ansible
playbooks passed syntax checks. These are focused tests, not the repository suite.

Still separate: independent external clean-device/browser/provider acceptance,
exhaustive every-app/every-role flows, real new-human NetBird enrollment and
unrelated storage/SPI/CI work. Mac DNS-free acceptance is observed on the unchanged
work VPN, not a promise about every corporate resolver or Internet provider.

### Living-room traffic light (2026-11-06)

Only `socrat-traffic-light` is additionally available through **native public dashboard sharing**, at `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>`. This is not anonymous organization-wide Viewer access and not an Authentik group bypass. Ordinary Grafana UI/APIs keep native SSO/roles and public password/Basic blocks. The temporary TV hostname has been removed: the TV internal WireGuard profile/key is explicitly retired, so the canonical Grafana hostname resolves publicly without that private path. The YouTube global VPN remains on demand. URL-only delivery, server-side presentation, scoped acceptance and rollback/uncertain-write handling are documented in `docs/android-tv.md` and `llm-wiki/android-tv.md`; do not use full TV provisioning for a URL-only update.


## Per-application ownership handoff — 2026-11-07

The former aggregate `public-web-entry` owner was first disarmed in Git: automatic
sync disabled and Application deletion finalizer removed. All **22** resources
were then added to their eight service owners. Offline rendering verifies exact
payload equality against the pre-migration snapshot (including proxy configs,
Pod templates, TLS, auth guards and resources); only Argo tracking ownership
changes live. Before retirement, all 22 resources had the expected new tracking
owner and their original UIDs. All 18 Certificate/Secret UIDs and all 186 sampled
existing Pod UIDs/readiness/restart counts were unchanged.

LiteLLM's full auto-sync attempted its pre-existing DB migration hook. The Job
remained Pending (512Mi request pinned to a memory-constrained socrat-0); it never
started. Automatic sync was temporarily paused in Git, the operation terminated,
and the pending hook removed by Argo. The alias Ingress alone was synced using a
resource-only operation, which skips hooks. Auto-sync was restored after the
application became Synced/Healthy. No DB migration, identity rewrite or workload
restart was required; the migration Job's existing scheduling policy was not
silently changed as part of an ingress ownership refactor.

After ownership verification the aggregate Application manifest and chart were
removed from Git; root prunes only the now-finalizer-free Application, not the
transferred resources. Children retain prune=false/selfHeal=true. Public TLS and
anonymous/forged-header/invalid-token checks passed **134/134** before and after
handoff. This is a configuration/ownership migration, not a fresh browser-MFA or
user enrollment acceptance test. Historical acceptance sections above describe
the former owner at the time; they are not installation instructions.

Test scope: 88 focused public-access, ownership, TV-policy, Syncthing GUI and
WebUI tests pass. An additional older `test_syncthing_scheduling.py` suite has five
pre-existing failures (it expects a DaemonSet, while the current chart defaults
to a Deployment). Running that suite against pre-migration commit `c612d71`
reproduced all five failures; it is not silently counted as passing or changed
as part of this migration.
