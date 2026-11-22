# Authentik integrations and adding a new service

> **Live auth audit15Nov:** [actual browser/API boundaries](../../../records/handoffs/browser-auth-audit.md).
> Current public Kuma Admin/Syncthing/Search routes do not have the previously
> described Authentik MFA gate. Native service login is not Authentik SSO. Native
> OIDC apps may serve public HTML but deny private APIs. No auth changes applied.

> **Current B2C contract:** [separate app groups and native roles](../../applications/application-access.md).
> Eight enabled roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS;
> the remaining reserved groups do not imply admission. Internal/External is
> not an app permission. The old owner-only/preparatory snapshots below are
> history; browser E2E and instant revocation of all sessions/keys are not
> claimed.

> Current November 7 snapshot: [logins, first login and native roles](../operations/identity-current-state.md),
> [NetBird/network](../../../network/README.md), [monitoring owners](../../../observability/monitoring/observability-current.md).
> The dated rollout/smoke sections below are history of their stage, not
> general readiness.

Start: [identity.md](../../architecture/identity.md). Do not confuse native SSO, a proxy
gate and an ordinary tile. Network entrances/roles were updated November 6:
[network-access.md](../../../network/README.md). The old session evidence below is dated;
version changes require a new review.

## 1. The registry and the sources

| Layer | Where to change it |
|---|---|
| The catalog of eight foundation services | `deploy/identity/services.json` |
| Reviewed people / old application IDs | `deploy/identity/account-mappings.json` |
| The common role intent | `deploy/identity/access-policy.yaml` |
| Providers, scopes, application bindings, MFA | `ansible/roles/authentik/files/configure.py` |
| Native app controllers | `ansible/roles/identity_integrations/files/integrate.py` |
| LiteLLM dedicated controller | `ansible/roles/identity_integrations/files/litellm_oidc.py` |
| Argo CD, outside the foundation registry | `ansible/roles/argocd_oidc/files/configure.py`, `deploy/argocd/values.yaml` |
| Consolidated live status | `docs/auth/architecture/access-management.md` |
| Sanitized results | `deploy/identity/migration-evidence/` |

The catalog's `migration` strings are historical hints, not an oracle of live
readiness: for example, `candidate` can remain on an already-verified service.
Check the actual provider, runtime settings and evidence. The foundation
catalog contains nine dashboard applications with local icons: the eight
registry apps plus the separately managed Argo CD. Additional public gates are
in the separate `deploy/public-web/services.json`; that is not a full
cluster-wide auth inventory.

## 2. Grafana

URL `https://grafana.socrat.alchemmist.xyz/` is reachable through both public
HTTPS entrances with native SSO and needs no workstation DNS overrides.
Native Generic OAuth/OIDC + PKCE, refresh token. Callback `/login/generic_oauth`.
Settings: `deploy/identity/grafana-oidc-values.yaml`; the Secret
`cattle-monitoring-system/socrat-authentik-grafana` holds the client secret.

`homelab-owner` → `GrafanaAdmin`; `app-grafana-editor` → `Editor`; other
admitted groups → `Viewer`. Admission and the native role are different checks.
`ALLOW_INSECURE_EMAIL_LOOKUP=false`, strict role mapping. Anonymous org access
is **off**, OIDC auto-login is on; the former proxy gate was retired after
verifying native roles. The public policy blocks BasicAuth/POST
login/metrics/debug, keeps bearer API/WebSockets and private recovery. Publicly,
without login, only the explicitly shared `socrat-traffic-light` is available,
not the whole organization.

The first `Login provider denied login request` failure was a protocol issue:
`grant_types: authorization_code, refresh_token` was missing. The fix is to
explicitly allow the needed grants in the provider, not to disable MFA/TLS or
widen admin groups.

A real temporary observer/MFA/code flow and the Grafana API role were
verified, not owner impersonation. The private gateway strips the Authorization
header deliberately; browser cookies work. Cleanup/API automation used the
internal API, not a weakened gateway.

## 3. Harbor

URL `https://harbor.socrat.alchemmist.xyz/`, native OIDC, callback
`/c/oidc/callback`. The controller uses the supported `CONFIG_OVERWRITE_JSON`
from the Secret `harbor/socrat-authentik-harbor`; persistence is also honored
by the Harbor role. The owner group → system admin; project grants remain
separate.

Before the switch the old non-admin local identities were checked: switching
the auth mode must not orphan users. The local `admin` is preserved; the known
stale initial password was not reset for testing. Its real recovery
acceptance/rotation requires the owner. Robot accounts and scoped project
credentials remain the way for CI push / private pull; do not apply the
browser gate to the registry API.

Harbor 2.15.4 / chart 1.19.4 and the HA work are described separately in
[harbor.md](../../../platform/harbor/harbor.md). OIDC does not remove the
single-node storage/PG/Redis risks and does not complete HA.

## 4. Rancher

Native Generic OIDC + PKCE, callback `/verify-auth`; restricted access,
subjects based on Authentik user UUIDs. Old local users were not rewritten into
external principals. Because `principalIds` are immutable, the reviewed external
identities `u-authentik-alchemmist` / **`u-authentik-tim-v2`** were created,
with the specific old global/cluster/project grants mirrored to them. That is
not a reason to give everyone cluster-admin.

Tim now logs in as `antropophag`; the recreated identity's UUID is pinned in
the account mapping. The old `u-authentik-tim` and `u-22wv2` are disabled,
grants/history preserved. Native `principalIds` are immutable: do not bypass
the webhook and do not change the old principal in place.
`rancherOidcUserId`/`rancherBindingPrefix` preserve the reviewed replacement at
the next reconcile. [Current links](../operations/identity-current-state.md).

Source: the Rancher branch `integrate.py`, reviewed old IDs in the account
mapping. Client secret: `cattle-global-data/genericoidcconfig-clientsecret`.
The local emergency identities remain. A group name by itself is not a Rancher
user ID; with new grants check the actual principal and namespace/project scope.

## 5. Open WebUI

`https://chat.alchemmist.xyz/`; the main callback `/oauth/oidc/callback`.
The catalog also has a reviewed legacy callback of another hostname; do not add
arbitrary aliases. Settings: `deploy/identity/open-webui-env.json`, Secret
`llm/socrat-authentik-webui`. Post-Helm: `identity-webui-reconcile.yml`.

Old users/chats are preserved through exact UUID/OAuth-ID links
(`Users.update_user_oauth_by_id`), without email merge. Owner is admin, Tim an
ordinary user. You must not set `Auth.active=False` as a universal way to
remove local login: the installed implementation of `utils/mfa.py:get_auth` also
turns off OAuth that way. Merely hiding the password form does not invalidate
old local sessions.

The existing OTel environment is preserved by the reconciler; do not replace
the whole env with the list from the OIDC example. The WebUI → LiteLLM machine
virtual key is independent of browser SSO.

## 6. Wiki

`https://wiki.socrat.alchemmist.xyz/login` → native OIDC, callback
`/api/auth/oidc/callback`. Not merely a proxy in front of the editor. The
runtime source is the neighboring `hugo-docs/runtime/oidc.py` / `auth.py`, while
the homelab keeps the immutable image, chart/Secret wiring and the reviewed
account mapping.

Authlib authorization code + PKCE, state/nonce, signature/audience/expiry and a
pinned issuer. The Secret `wiki/socrat-authentik-wiki` contains the settings
and the session signing key. During reconcile the signing key is preserved so
as not to accidentally invalidate sessions. Callback access logs are off
(`UVICORN_ACCESS_LOG=false`) for code/state privacy.

Owner → the existing admin ID. Tim → the existing editor ID, a separate
reviewed subject role override. Other admitted observers → reader. Email is not
used as proof of ownership of an old record. The `oidc_accounts` and
`oidc_sessions` tables live in the accounts SQLite; chats/content are not
replaced by this.

`/login?local=1` works only for the existing local owner ID. Non-owner local
passwords and old local sessions are cut off **on the server**, not only in the
UI. This is the most fully verified owner-only fallback in the current
migration. Public read and machine MCP credentials are preserved;
missing/invalid auth for write/MCP must not turn into a browser redirect.
Verified: MFA, write 403 for reader, invalid callback 401, preservation of the
old owner/Tim IDs. Wiki placement/storage changed in parallel: do not take the
old pod location as current truth.

## 7. LiteLLM

The owner confirmed a working login. Native Generic OIDC + PKCE on **1.105.1**:

- launch: `https://llm.alchemmist.xyz/sso/key/generate`;
- callback: `https://llm.alchemmist.xyz/sso/callback`;
- provider `homelab-litellm`, app `litellm`, production admission `homelab-owner`
  or **`app-litellm-user`**. Members receive `internal_user`, identity remains
  `authentik:<UUID>`. Vladislav migrated to the group without replacing his account;
  former user binding removed, `litellm-users.json` empty. Not every Authentik user
  receives access. See [current systemic app groups](../../applications/app-access-groups.md);
- custom scope mapping `homelab-litellm-reviewed-identity`, scope `litellm_identity`;
- Secret `llm/socrat-authentik-litellm`, Generic SSO env; Helm optional Secret refs.

In this version free SSO allows up to five billable users. The controller
conservatively checks that the total number of DB users is <=5 and the pinned
versions. There were two original user rows. The license was not replaced and
the Enterprise check was not bypassed.

The mapping selects the existing `socrat-admin` / `proxy_admin` **by reviewed
IdP UUID** from the account mapping and the private journal, not by
email/username. The needed existing email is substituted after choosing the
immutable identity. Other UUIDs get a separate `authentik:<uuid>` and a
synthetic address under their own `sso.socrat.alchemmist.xyz`. A member of
`app-litellm-user` receives `internal_user`; without it the safe branch is
`internal_user_viewer`, but application admission is not granted with it. An
observer does not automatically become a LiteLLM user.
Addresses under `.invalid` were rejected by the upstream email-validator — do
not use them where the runtime expects a validatable email-domain model.

The native browser roundtrip was verified on a random read-only fixture:
password → TOTP → consent → PKCE callback 303 → server `/user/info`. The
temporary single admission binding, both identity records and the UI keys were
deleted. No test MFA was issued to the real owner and his password was not
read. The original IDs/roles/emails/password hashes/SSO IDs were compared
unchanged. The old Open WebUI virtual key still reads models; without a key it
is still 401. Master/salt/DB Secret data, config and the explicit OTel env are
preserved; vLLM was not restarted. LiteLLM went through the usual graceful
rollout.

Owner DB password recovery: `/fallback/login`, the route returns HTTP 200. The
password was not reset; its real recovery check does not follow from the SSO
confirmation. `litellm.yml` and `llm-vision.yml` are decommissioned: both only
refuse and do not invoke identity reconciliation. Separate identity maintenance
needs its own activation/ownership verification; metrics and model metadata are
not permission to repeat the bootstrap or change native SSO.
The full runbook/rollback: `docs/applications/ai/litellm.md`.

## 8. Argo CD

Native direct OIDC, Dex off. The live GitOps source is
`deploy/platform/argo-cd/values.yaml`; the bootstrap mirror is
`deploy/argocd/values.yaml`, `ansible/roles/argocd_oidc/files/configure.py`,
playbook `argocd.yml`. Issuer `/application/o/argocd/`, callback
`https://argocd.socrat.alchemmist.xyz/auth/callback`, client `socrat-argocd`.
The secret key `oidc.authentik.clientSecret` is in the Argo CD Secret, with no
value in values.

Dedicated `groups` scope; scopes openid/profile/email/groups/offline_access.
Application admission is currently owner + platform-operator. Argo RBAC
owner/operator → admin; maintainer/observer in the role table → readonly, but
that does **not give them admission** through the IdP. The default readonly also
does not cancel the application gate. The built-in admin break-glass stays
until a separate owner recovery acceptance. The native server is now
`server.insecure=false`: verified HTTPS also goes from both ingress to the
backend, so refresh keeps the Secure cookie. The bootstrap and live values are
checked for semantic equality; ServersTransport is managed via extraObjects.

In this session only the official pinned icon was added to an already existing
app; its provider/policies were not reconfigured by the icon uploader. Do not
add Argo CD to the foundation catalog without an explicit ownership transfer
between controllers.

## 9. n8n and Kuma — exceptions, not ready native SSO

**n8n:** Community does not provide the needed native SSO integration without a
license. The embedded outpost Authentik guards the browser UI/rest owner-only;
after MFA n8n can still ask for its own login. Configuration:
`charts/n8n/templates/access.yaml` and the proxy settings in the catalog.
Webhooks, waiting webhooks, forms, healthz, `/api/v1` and OAuth credential
callbacks bypass the browser gate by the reviewed route boundary. This does
not make the API anonymous: it keeps checking its own keys/signatures.

Checks: UI/rest → 302 to the IdP; health → 200; API without a key → 401; a
missing webhook → 404. The original Fleet ingress/cert were preserved. You
cannot make robots and callbacks receive HTML login instead of a protocol
response with a wildcard guard over `/`.

**Open, November 2, 2026:** the owner reported an n8n login/session problem.
Both edges passed the anonymous redirect to native Authentik, health200,
keyless API401 and a Running/Ready pods check. This is not an
owner/native-login/editor-after-idle acceptance; the specific symptom is not
yet clarified. The settings were not changed. Do not port the 3x-ui
nginx forward-auth fix to the n8n proxy-mode without a reproduction. See the
[diagnostics journal](identity-gateway-troubleshooting.md#4-n8n-an-open-owner-report-not-a-fixed-problem).

**Uptime Kuma:** native OIDC is not deployed and not claimed. But the
separation of entrances is **complete**: status `/status/socrat`,
status/heartbeat APIs/assets/badges and token push are public; the public
Socket.IO/unknown admin APIs are closed, and the legacy admin paths lead to
`kuma.socrat.alchemmist.xyz`. On the admin host: the personal MFA of
owner/`uptime-kuma-web-admins`, then the original native Kuma auth. MFA does
not make a person a native admin. Verified: scoped MFA, WebSocket
101/namespace and the denial of native `getSettings`; fixtures deleted.

On an application restart a Secret/SQL credential mismatch was found; an
observed ~35min heartbeat gap occurred. Recovery created a separate schema-only
app account without changing the old SQL passwords and without a DB restart;
the Secret data changed, native Kuma account/auth preserved. Do not regenerate
the Secret/do not change the DB username:
[MariaDB runbook](../../../observability/monitoring/uptime-kuma-mariadb.md),
[summary and limits](../../../network/README.md#6-kuma-recovery-after-the-incident-not-zero-downtime).

### Public aliases and Syncthing

`deploy/public-web/services.json` holds the admission allowlist; the public
Ingresses/proxies belong to the corresponding Argo Applications (local charts or
`deploy/platform/<app>/public-entry` within the same Application); the separate
`public-web-entry` was removed — do not mix them with the foundation registry.
Search admission is owner/`netbird-internal-admins`; app authorization behind the
aliases remains native, machine APIs are not moved to browser redirects.
Rancher is public with native OIDC/roles and a policy proxy against
local-password mutations; agents/bearer/WebSockets/private recovery are
preserved. Grafana MCP is public verified TLS + a separate read-only bearer,
not a human MFA gate.

On node0 `/sync/` is personal MFA owner/`syncthing-web-admins`, then the
unchanged original BasicAuth with the prefix stripped. Node1 answers 410
gateway-only: no new device/identity was created for the GUI. The existing
BasicAuth, sync process/config/data were not changed. The real owner Basic
login remains a separate optional acceptance.
[Details of the public closeout](../../../applications/public-web/public-web-migration.md).

## 10. Connecting a new service: a safe order

### Step 1. Inventory before configuration

Record the version/image/chart, all hostnames and auth paths, the current
people/IDs/roles, local login methods, already-issued sessions, machine
consumers and public routes. Check native OIDC/SAML support, the installed
version's actual license, PKCE/claim support. Do not rely only on the newest
release's documentation.

Make an encrypted pre-change backup of DB/config/Secret references. Do not
print secret bodies to a shared terminal/log. Prepare the owner recovery and
rollback criteria.

### Step 2. Choose the mechanism

The preference is native OIDC. An auth proxy is allowed only with the described
browser/machine/public path split. If a safe boundary is unknown, the status is
blocked, not “SSO is ready because a tile appeared”. The OIDC code flow needs
backend/client support; it cannot be replaced with promotional frontend JS or a
client secret stored in the browser.

### Step 3. Design identity/roles

Define the immutable subject mode **before the first login**. Check the old IDs
and make an exact linking map, data preservation and a conflict policy.
Specifically check another user with the same email/display name: he must not
become the owner. Define the minimal app/project roles separately from the IdP
admission groups.

### Step 4. Provider and application

For a foundation-managed service add a reviewed catalog entry: a unique slug,
name, launch URL, exact redirect, approved groups, icon, explicit migration
mode, and if needed `subMode` / custom scopes. Do not put the client secret in
the JSON. The runtime provider is created by the owner automation with
protected credentials.

Provider: a confidential client for server apps; the needed grant types
explicit; the default native authentication/MFA flow; a suitable
authorization/consent flow; a signing key; strict callbacks; minimal
claims/scopes. The foundation validity is currently access 5 minutes / refresh
8 hours; this is not necessarily the local app cookie lifetime.

Check the custom property mappings: that is executable security-sensitive code.
On a missing mapping the controller must stop/postpone the application, not
grant a broad role by a fallback email. Do not regenerate an existing provider
without its private client journal — first restore/verify the credentials.

A minimal example of a **template**, not a ready integration (replace
URL/slug after review):

```json
{
  "example-service": {
    "name": "Example service",
    "url": "https://service.example.org/",
    "description": "Reviewed native OIDC integration",
    "redirect": "https://service.example.org/oauth/callback",
    "groups": ["homelab-owner"],
    "subMode": "user_uuid",
    "migration": "native-oidc-pending-backend-acceptance",
    "icon": "service-icons/example-service-REPLACE_WITH_DIGEST.svg"
  }
}
```

Do not copy this into production without checking the actual callback, allowed
users and the app backend. `REPLACE_WITH_DIGEST` is a placeholder: first add the
reviewed asset and provenance to `assets/service-icons/sources.json`, get the
real digest/name, then check the served icon and update the corresponding
regression tests. The generic controller currently supports `grafana`, `harbor`,
`rancher`, `open-webui`, `wiki`; `litellm` goes through a separate branch of the
role. For a new slug a backend adapter or its declarative equivalent must be
written/reviewed: the catalog entry by itself does not create OIDC support
inside a new application.

### Step 5. Configure the application backend

Pass the client ID/secret via a private runtime Secret; configure
issuer/discovery and scopes per the installed version. Add source-controlled
references and a post-upgrade reconcile; do not leave only a manual Deployment
patch. Preserve the OTel/env/volumes/machine keys and unrelated chart values. Do
not repeat a blind whole-env replacement. Check readiness/graceful rollout; do
not force-delete draining pods.

### Step 6. Verification and publication

- Positive: password + a real temporary MFA + callback + server-verified ID/role.
- Negative: an unadmitted identity is denied, a non-admin is not admin, exact
  callback/state, wrong issuer/audience/expired tokens are not accepted, no
  arbitrary email merge.
- Existing data and IDs are preserved; the owner recovery is separately accepted
  by the owner.
- Public routes and machine key requests keep the semantic HTTP status, without
  HTML redirects.
- Fixture users/keys/devices/temporary policy bindings are deleted even on an
  error.
- A separate check of already-issued local sessions; UI hiding is not
  enforcement.
- Documentation/evidence without cookies/codes/seeds; tests and a narrow
  commit; a push is not a deploy until the running config/images/controllers
  are checked.

Do not declare “all services migrated” after one successful app flow.


## Argo CD background refresh and backend TLS

`offline_access` was deployed (mapping + requested scope), the proactive
refresh `60s`, the Argo session policy `8h`; the access/ID token stays `5min`.
In Argo CD 3.5.6 renew-cookie depends on `!server.insecure`, so the backend is
now HTTPS with verification of the existing certificate and SNI via
`argocd-verified-tls`. The VPS CRD provider is limited to the argocd namespace
and the chosen transport's label; no skip-verify/cross-namespace/ExternalName.
DNS, WireGuard and MFA were not changed.

The ingress is managed by Argo selfHeal: a temporary pause of traefik-edge
only, publication of the sources, a hard refresh to the new revision, then
restoring the original autosync. Otherwise a manual Helm upgrade gets reverted.
Acceptance status/fixture cleanup and the detailed runbook:
[Argo CD refresh](argocd-refresh.md). Old sessions need one new SSO
authorization to get the refresh token. The other applications are not changed
by this; the 8h refresh validity by itself does not prove that a particular
client gets/uses a refresh token.


## 3x-ui: owner MFA gateway (not native SSO)

The public VPN panel is protected by the Authentik forward-auth (`xui-panel`),
`homelab-owner` only; after the IdP the native 3x-ui login remains. There is
no account/email merge, MFA substitution or automatic native-admin login.
Direct public TCP 18082 is closed by a persistent panel-only nft rule;
private/loopback recovery is a separate trusted boundary with native
credentials.

The text/JSON subscriptions and Trojan WebSocket keep their former backends
and bypass only the human gate, not their own machine authorization. The
native API exception requires Bearer and removes the Cookie; a wrong token
gives 401, a cookie-only browser API requires MFA. VPN/ingress were not
restarted; real tunnel/subscription and both public-edge MFA fixture tests
passed.

The Bearer lifetime is 5 minutes; offline-access/8h refresh are configured only
for the new proxy provider. But the expiry test revealed a native browser
roundtrip to the IdP, not a seamless refresh; a panel reload with an expired
proxy cookie is possible. Do not transfer to this gateway the silent-refresh
claim proven for Argo CD. Personal owner recovery/native-login and valid API
token acceptance remain separate.

Sources, the install host rule, reproducible acceptance, limits and rollback:
[docs/auth/authentik/integrations/xui-gateway.md](xui-gateway.md). The narrow
controller `xui_gateway.py` does not replay the foundation and does not change
the panel's users/database.


### 3x-ui: the Login Failed-to-fetch fix

With the gateway cookie missing, a background POST used to go into a
cross-origin OAuth redirect and produce TypeError: Failed to fetch. Now XHR/
fetch and unsafe methods get a same-origin 401; the native 3x-ui3.11 itself
starts the ordinary top-level navigation. CSRF, MFA, the native password and
the machine Bearer policy are not bypassed. Both edges were checked: native
CSRF/empty-login JSON200, missing-cookie 401 without a redirect and a **real
native Login button →401 → return via SSO**. The test credentials never
reached the native backend; fixture users/bindings deleted. The owner's
native-password acceptance remains personal. A seamless refresh is not
promised. Details: [gateway diagnostics](identity-gateway-troubleshooting.md#3-3x-ui-the-fixed-failed-to-fetch-at-login).


## The machine admin API: not Default Admin

For the identity controllers the `homelab-identity-automation` (service
account) is dedicated, and the Outpost keeps its own separate technical
identity. `akadmin` was deleted after moving the token and the recovery drill.
Human IDs/links/roles were not carried over. The legacy credential key
AUTHENTIK_BOOTSTRAP_TOKEN is kept as an alias of the new key, so current
consumers stay compatible; the runtime Secret excludes the admin bootstrap env.
Details and the broad privilege boundaries:
[admin-automation.md](../operations/admin-automation.md).

## SPI queue native OIDC — prepared 9 November, not activated

Standalone `spi.socrat.alchemmist.xyz`; source in the full `spi-triage` repo.
Native confidential Code+PKCE, state/nonce and RSA issuer/audience/expiry checks;
no RustFS forward-auth or client secret in JS. Dedicated SPI identity catalog/
plan controller follows the separately owned native-provider pattern; do not
replay foundation or change existing human memberships. Frontend-only Secret,
canonical callback and app-owned Ingress/TLS/policy are prepared. Built native
image: 341 tests/zero skips; GET-only live Authentik plan succeeded. No live writes
or protected publication approval: operator kubeconfig is unreachable and SSH
lacks its trusted saved host key. See [SPI OIDC runbook](spi-triage-oidc.md)
for activation, bounded five-minute local sessions and explicit acceptance gates.

## SPI queue runtime closeout — 10 November 2026 UTC

Native SPI frontend is now live at `https://spi.socrat.alchemmist.xyz/queue/`.
Exact DNS record, app-owned verified Let's Encrypt TLS and dedicated native OIDC
provider/client are active. Worker/frontend use canonical immutable digest
`sha256:d8a57a175afff1e1596a8e73832b0ea994abb617c56f7945357ab5d6b9002112`;
original workflow resumed, same PVC/history preserved, Argo Synced/Healthy.
Prepared/blocked checkpoints above are historical. Real personal MFA/callback
acceptance remains unobserved (busy shared browser); no bypass or synthetic human
identity was used. Full evidence/limits: [runtime receipt](spi-triage-oidc.md#final-runtime-receipt--10-november-2026-utc).

### SPI canonical root correction — 10 November 2026 08:46 UTC

Use **https://spi.socrat.alchemmist.xyz/** directly, not `/queue/`. Native callback
returns to root; old bookmarks redirect there. Root release passed 347 native
tests, image `sha256:ce569e2483e7e69f0390eb99cb56c290b48a5429fca25243ac44f711a8fd3224`.
Explicit overload responses replace silent connection-close 502 and sanitized
upstream error diagnostics are enabled. Exact historical reported 502 cause not
proven. Original workflow resumed; execution 16303 stopped under prior owner
authorization, kept for review/no automatic replay; paid reservations not cleared.
1037 job identities and 549 prior terminal hashes preserved. Full dated receipt
in [SPI runbook](spi-triage-oidc.md).

## OpenHands Canvas —18November2026, owner-only OIDC gateway

Official Canvas1.41.0 lacks native human OIDC/RBAC. Its dedicated, official
**oauth2-proxy7.15.6** uses native Authentik Code+PKCE, existing MFA/consent flows,
strict callback and the existing `homelab-owner` group only. This is an explicit
single-tenant shell-service exception, NOT restoration of universal proxy gates.
No users, memberships, IdP keys or other applications changed. Proxy credentials
live in identity, outside coding tools; the native direct ingress stays disabled.
GitOps source, dedicated native-API bootstrap, network/TLS details and remaining
public DNS/TLS acceptance and remaining positive-MFA acceptance:
[OpenHands runbook](../../../applications/ai/openhands.md).
