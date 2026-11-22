# Login diagnostics: native SSO and MFA gateways

> Current cut7 November: [logins, first login and native roles](../operations/identity-current-state.md),
> [NetBird/network](../../../network/README.md), [monitoring owners](../../../observability/monitoring/observability-current.md).
> The dated rollout/smoke below is the history of its own stage, not general readiness.

> Network summary of 6 November: [network-access.md](../../../network/README.md). The `176.98.185.59` named in the old acceptances is the former VPS; the current one is `109.120.141.97`. Grafana/Rancher now have reviewed public entrances, the Mac resolver overrides were removed, the Kuma status/admin boundary is complete. Do not treat the historical diagnostic symptoms below as the current live cut.

Cut: **2 November 2026**. Index: [identity.md](../../architecture/identity.md).
This document records verified results and open problems; it does not replace a live check.

## 1. Why the application form stays after Authentik

SSO is a single sign-in; OIDC and SAML are the protocols implementing it. A button/tile by itself does not add protocol support to an application.

| Application | What is implemented | What the user will see |
|---|---|---|
| Argo CD | Native OIDC, short bearer + server-side refresh | A login through Authentik; a separate native password is not needed for the SSO path |
| 3x-ui 3.11.0 | An external Authentik forward-auth gateway | Authentik MFA/admission → **the standard 3x-ui login** |
| n8n, the current Community install | An embedded Authentik proxy guards the browser UI/rest | Authentik MFA/admission → **a standard n8n login is possible**; native SSO is not implemented |

If the parent Authentik session is active, the first stage may pass automatically. The absence of an Authentik button in 3x-ui is an expected property of this implementation, not proof of a bypass. The native form uses the existing application password, not the Authentik password. There is no automatic email/name binding or native account creation.

One login instead of two will require a supported integration in the application itself, a reviewed enhancement or a migration. Do not imitate SSO with a saved admin password/autofill through a proxy and do not bypass n8n's licensing restrictions.

## 2. Argo CD: a new offline_access consent

The text `Access to request new tokens without interaction` is a native consent for the scope `offline_access`. Email/profile may be shown as already granted, offline-access — as a new permission. This is needed for refreshing short tokens and **does not grant an admin role, does not disable MFA**.

Confirm only a self-initiated login into the expected application on a trusted Authentik hostname. Do not hide/fake consent for cosmetics. Details and real expiry tests: [Argo refresh](argocd-refresh.md).

## 3. 3x-ui: the fixed Failed to fetch at Login

**A gateway defect was reproduced and fixed**, not a password error:

1. With a fresh gateway session, the native CSRF and a POST with empty fields returned the standard JSON200.
2. After removing only the proxy-cookie from a temporary fixture, the background POST redirected into OAuth/Authentik.
3. The cross-origin redirect of the background fetch led to `TypeError: Failed to fetch`.

The gateway now returns a **same-origin401 without redirect** for native XMLHttpRequest, fetch cors/same-origin, WebSocket and unsafe methods. Only an ordinary safe browser navigation starts OAuth. The standard 3x-ui3.11 already handles401 via a top-level `location.replace`; no new authentication JS was added.

Both public edges were verified: a fresh CSRF/POST JSON, a missing proxy-cookie →401 without Failed to fetch, **clicking the real native Login button →401 → returning via a top-level SSO**. The synthetic form data did not reach the native backend; this is not a check of a real owner password. The temporary observer users/admission bindings were removed. Sources:

- `scripts/build-xui-auth-gateway.py`, `deploy/xui-auth-gateway/{nginx.conf,resources.yaml}`;
- `scripts/identity-xui-gateway-smoke.py --run [--public-edge IP]` — temporary identity/admission writes, not read-only;
- [The full runbook](xui-gateway.md).

A limitation remains: the native outpost does a browser roundtrip when the proxy session expires; a seamless refresh, like Argo CD's, is not proven. After idle, a reload and re-entering the native fields are possible. The bearer TTL was not increased to hide the problem. Do not automatically replay a POST with a password after OAuth.

MFA, owner-only admission, native CSRF and separate machine credentials were not weakened. The bearer API exception still removes the Cookie and is checked by the 3x-ui itself; an invalid Bearer →401. The VPN transport, subscriptions, native x-ui and Traefik were not restarted by this fix — only the new gateway.

## 4. n8n: an open owner report, not a fixed problem

The owner reported an authorization problem, **the specific symptom and stage are not yet clarified**. You must not consider the problem solved or automatically attribute it to the 3x-ui cause.

Recorded primary checks on **both** edges `109.173.40.247` / `176.98.185.59` with a correct HTTPS/SNI:

| Check | Result | What this proves |
|---|---|---|
| `GET /` without a session | 302 | The browser gateway triggers |
| Clean Chromium → n8n | Native Authentik identification/password, without JS errors | The initial transition works, not an end-to-end owner login |
| `GET /healthz` | 200 | The backend is alive and health does not depend on an interactive login |
| `GET /api/v1/workflows` without an API key | 401 | The machine API did not become public and does not get a login redirect |
| The n8n and Authentik pods | Running/Ready, without current restarts | There is no observed crash of these pods at the check moment |

**Not verified:** a personal owner session, a native n8n login, UI/rest work after idle, reconnect/WebSocket and an active owner API key. During this diagnostics the n8n/IdP configuration was not changed, fixture users were not created.

The next step is to get a safe description: on which screen the failure occurs; the exact text; at once or after idle; whether the problem is in the native n8n form, Authentik/MFA, editor/rest or a loop. Then reproduce exactly this scenario. Do not blindly port the 3x-ui XHR401 configuration: n8n uses a **proxy-mode embedded outpost**, while 3x-ui — nginx forward-auth.

n8n sources: `charts/n8n/templates/access.yaml`, `deploy/identity/services.json`, `ansible/roles/authentik/files/configure.py`. UI/rest are owner-only; separate reviewed routes for webhook/forms/health/API/OAuth credential callbacks and the exact MCP HTTP keep their own native authentication. Do not include them in a wildcard browser gate and do not open all of `/rest` to bypass a login error.

## 5. A safe diagnostic order

1. Clarify the stage and whether it is a fresh tab. A private window is a separate check, not removing the owner MFA devices.
2. Check the public HTTPS from both allowed edges without disabling certificate verification; do not change the system DNS/WireGuard for a test.
3. Compare the document navigation with XHR/fetch: a 302 in a cross-origin flow, 401, 403/CSRF and JSON with a password error are different causes.
4. Do not copy passwords, Authorization/Cookie, callback query, OTP/QR, a full HAR or a private DOM into chat/Git. For a screenshot, remove secrets and address-bar parameters.
5. First the read-only checks; real test identities/admission bindings are a separate explicit scope with an exact cleanup. Do not change the owner's factors.
6. Do not extend the bearer TTL, roles, bypass paths, trusted headers or disable CSRF/TLS/MFA to make an error disappear.
7. Fix the authoritative GitOps source, wait for Synced/Healthy; do not fight selfHeal. Fixtures are not a personal owner acceptance.

## 6. The current frontend

Nature: one scene CSS with an inline preview of the same photo, one HQ AVIF/WebP, an immutable image cache; not two full random frames. Plan History takes its natural height **without an internal scroll**; the history/repeats/rights were not changed. Details and tests — [identity-frontend.md](../custom-ui/README.md), §§15–16. These appearance changes are not a fix of n8n sessions.
