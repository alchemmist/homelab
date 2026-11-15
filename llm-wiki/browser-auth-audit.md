# Browser authentication audit — 15 November 2026

## Scope and evidence

Owner asked which user-facing services actually require Authentik, rather than
which have dashboard cards. This is a **read-only** audit. No provider/policy,
user, Secret, workload replica, middleware, networking or login setting changed.
No account login, password guesses/resets, workflow execution, S3 download or
state-changing application API was used. Existing concurrent monitoring/wishlist
work was left alone.

Evidence: [46 anonymous GET checks](../docs/identity/evidence/browser-auth-anonymous-20261115.json),
live Ingress routing/annotations and selected proxy ConfigMaps, Deployment ready
counts and allowlisted non-secret OIDC/login environment settings. No browser
cookies/tokens or credentials in probes. TLS verification remained on. HTTP
redirect targets in evidence omit query strings (OIDC state/nonce not recorded).
HTML sampling records only title, not page content/data. The response body was
bounded to32KiB. These are point-in-time observations, not exhaustive penetration
or logout/revocation acceptance. A failed GET or404 on an assumed API route is
not proof of authorization; additional valid SSO paths were checked separately.

## Main result

**n8n, Umami, Kuma Admin, Syncthing and VPN panel are not protected by Authentik
in the same way as native OIDC applications or RustFS ForwardAuth.** Missing
Authentik cards do not explain or repair that distinction. Their native login
is a different boundary; frontend200 alone does not imply anonymous private data.
Search is currently accessible without Authentik. Previous claims that current
Kuma/Syncthing/Search aliases necessarily require personal Authentik/MFA are
historical and contradicted by current routes/behavior.

## Native Authentik integrations / dedicated session gates

| Service | Current observation | Limits / remaining work |
|---|---|---|
| Grafana | `/login/generic_oauth`302 to Authentik; `/api/search`401 anonymously | Root302 to native `/login`; not an all-path proxy gate. Does not prove every local recovery path disabled. |
| Argo CD | `/auth/login`303 to Authentik; `/api/v1/applications`401 | Public frontend200 is normal; native bearer/session RBAC remains separate. |
| Harbor | `/c/oidc/login`302 to Authentik; `/api/v2.0/users/current`401 | Native project roles/CLI auth independent; issue134 revocation limits unchanged. |
| LiteLLM | `/sso/key/generate`303 to Authentik; `/user/list` and `/v1/models`401 | API keys/owner recovery are separate. Not blanket OIDC redirects over machine API. |
| LMS | Root303 to `/auth/login`, then303 to Authentik; `/api/me`401 | Native student/teacher and lesson grants remain separate. |
| Wiki | Root200 public reading; actual `/api/auth/oidc/login`302 to Authentik | Public content is not an auth bypass. `/auth/login`404 was an invalid guessed path, not a missing integration; `/api/auth/me`200 was not used as private-data proof. Private write/API authorization not exhaustively tested. |
| SPI Queue | `/queue/` and `/api/queue`302 to `/login`; `/login`302 to Authentik | No task dispatch/write API called. |
| RustFS browser | Root302 to Authentik; `/spi/v1/`401 | Live root Ingress has RustFS ForwardAuth. More-specific `/spi/v1/` uses Reader's own session check, not the same Ingress middleware. Invalid-prefix401 does not substitute for valid-artifact forbidden-user testing. Raw S3 credentials/permissions remain separate. |
| Change password | `/change-password`302 to normal Authentik login | Mini-service auth_request + native authenticated-only flow; earlier External fixture checks documented separately. |
| Rancher | Native integration already configured/documented; root200, `/v3/clusters`401 | No fresh full provider/login/MFA/role acceptance in this audit; do not claim entire domain has an Authentik gate. |
| NetBird | Native integration already configured/documented; dashboard200, `/api/users`401 | Machine enrollment/management/relay must not receive browser redirects. Fresh native login/browser-role proof not repeated here. |
| Open WebUI | **Unavailable503** at root, auth API and OIDC start; live Deployment `replicas=0` | Config still has Authentik discovery, OAuth signup/claims, but availability prevents live login verification. `ENABLE_LOGIN_FORM=True`, `ENABLE_SIGNUP=False`: do not label exclusive-SSO from issuer alone. No attempt to start it or infer why another workflow scaled it down. |

These native integrations are not claims that every URL must redirect before
serving HTML. A public login shell, static asset, OIDC callback, health endpoint
or native401 API response is compatible with correct native SSO. A separate
review is needed for strict Authentik-only human login versus retained local
owner recovery, and for sessions/API-key revocation.

## No Authentik gate / native-service authentication

| Service | Verified facts | What is NOT established |
|---|---|---|
| n8n | Direct Ingress to n8n, no Authentik middleware; root200 n8n shell; `/rest/workflows` and `/rest/credentials`401 | No assertion of anonymous workflows/credentials. Own login, webhook/form/OAuth callback and machine API boundaries are separate. Native OIDC/JIT not accepted. |
| Umami | Direct Ingress, no Authentik middleware; root200 Umami shell; `/api/websites`401 | No assertion of anonymous analytics/account data. Historical suspended account/native OIDC blocker remains. Public tracker must not be blanket-gated. |
| Kuma Admin | Direct Ingress to Kuma, no Authentik middleware; root302 `/dashboard`, frontend200; Socket.IO polling handshake200 without Authentik | A successful transport handshake is not an authenticated session or authorization to read settings. Native socket event permission checks were NOT repeated; do not claim anonymous admin or confirmed denial of every event. |
| Syncthing node0 | Public proxy has no auth_request/Authentik middleware; forwards to GUI with fixed Host. HTML contains native login/password markers. `/sync/rest/system/status` and `/rest/system/status`403 | Native denial observed; do not claim all REST/config/file APIs accepted or tested. Old private-gateway BasicAuth is a different route, not proof of MFA on this public proxy. Node1 `/sync/`410: gateway-only, no separate device. |
| VPN panel | Live `vpn` Ingress has no Authentik middleware and forwards root to panel bridge; owner confirmed not Authentik | Root404 is not an auth check; configured private panel path/login/its APIs were not exercised. Subscription and tunnel routes deliberately not probed or printed. Own panel login is not Authentik. |

## Public content and noninteractive endpoints

Search root200 returns `Socrat Search`; its live Ingress forwards directly to
SearXNG without Authentik middleware. Its current behavior is public, not an
Authentik login shell. Whether the owner wants to restrict it is a policy choice,
not something a dashboard-card migration should decide.

Blog, Cats, Format Quorum, Monori, Wishlist and Socrat Home returned public200
pages. They have ordinary direct Ingress routes, not Authentik gates. This audit
does not establish a new requirement that all such public sites become private,
or audit every form, write API, editor/admin endpoint behind those pages.

`status.alchemmist.xyz` intentionally redirects to `/status/socrat`; its active
nginx policy exposes status/assets/selected status APIs, rejects public Socket.IO
(404 observed) and routes admin paths to the separate Kuma admin host. The latter
host currently has native Kuma login, **not** the historical Authentik gate.

Machine endpoints (PR Agent/GitHub webhook, Telegram bot, image proxy, Remark42
comment service, Grafana MCP bearer, NetBird relay/management, n8n webhooks/forms,
VPN subscriptions/tunnels, Harbor/S3 APIs) cannot be safely forced through a
human-login302 indiscriminately. Their signature/token/role controls require
separate endpoint-specific acceptance; no write probes were made here.

## Proposed next decisions — NOT applied

1. Confirm desired human-facing boundary for **Kuma Admin, Syncthing, VPN panel,
   n8n and Umami**, separately. If an outer Authentik gate is requested, define
   allowed app groups and preserve native accounts/roles; gate+local-password
   remains two-stage authentication, not native SSO/JIT.
2. For n8n/Umami/VPN, split human-admin paths from callback/tracker/webhook/
   subscription/machine consumers before any gate. Preserve existing keys,
   sessions, client URLs, data and local owner recovery until explicitly reviewed.
3. Decide whether Search should remain public. Do not restrict public websites or
   global Wiki read access by assumption.
4. Investigate Open WebUI replicas0 with its current owner/task before restoring;
   no restart/scale authorization inferred from an audit request.
5. Add/clean up Dashboard cards only AFTER the actual authentication contract is
   clear. A providerless bookmark never closes a route or creates a native user.
6. Full fresh-human/browser MFA, forbidden-user and private API/read/write/session
   revocation tests remain separate acceptance, not inferred from these GETs.
