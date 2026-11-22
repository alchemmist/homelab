# 3x-ui: an Authentik MFA gateway, not native SSO

## Boundary

The `vpn.alchemmist.xyz` panel (3x-ui 3.11.0) did not provide native OIDC/SAML in the tested version. Therefore the browser passes **Authentik MFA → the 3x-ui's own login**. The passwords, native MFA, users, API tokens, clients and the panel database are not replaced; there is no automatic account creation/merging. The gateway itself does not turn Authentik groups into 3x-ui roles.

- The application `xui-panel`, provider `homelab-xui-panel`, `forward_single`; admission only for `homelab-owner`.
- The existing embedded outpost is used; other providers are kept.
- Nginx without a SA token, non-root/read-only, a pinned image, on `socrat-2`. Browser requests are checked by native forward-auth.
- `offline_access` was added only to this provider, the bearer validity was left at **5 minutes**, the refresh grant validity — 8 hours. **A native outpost limitation:** a real expiry test found a browser roundtrip through the IdP even with offline-access; this is not a seamless server-side refresh like the fixed Argo CD's. An active parent SSO returned the fixture to the native login without re-entering the password/TOTP; an API/XHR with an expired proxy cookie may require reloading the page. Do not increase the bearer TTL to hide this; a separate decision — a reviewed gateway with a full native OIDC refresh.
- The proxy cookies were verified as `Secure`/`HttpOnly`; native cookies over public HTTPS get `Secure`. Callback codes and requests are not written into the gateway's access/error logs (error level `crit`).
- An API without browser MFA is allowed **only** under `/.../panel/api/` with a canonical `Authorization: Bearer …`. The 3x-ui checks the token itself; the gateway removes the incoming Cookie. An incorrect Bearer is not turned into a cookie login and is not sent to the IdP. A browser/cookie-only API stays behind MFA. A login/password entry is not an unattended API exception.
- The text/JSON subscriptions and the existing Trojan WebSocket have separate former backends, priority 200; the panel is a gateway with priority 100. They do not depend on the IdP. The native Bearer branch does not make an auth subrequest; a deferred DNS lookup lets the gateway start without an available DNS/IdP. This is not a claim about a full cold-start/HA of the whole infrastructure.

## Direct port and recovery

Before the change, the public `176.98.185.59:18082` answered HTTP 404 and bypassed the future MFA gateway. Now a separate nftables table `inet homelab_xui_panel_auth` closes TCP 18082 on public addresses, including requests to the public IP via a local/VPN exit. The WireGuard, forwarding/NAT, SSH, subscriptions, VPN ports and transport configuration are not changed.

Only the private destination `10.250.0.2` and loopback are left, through the existing trusted interfaces. This is a **deliberate internal recovery/workload trust boundary**, not a universal enforcement of Authentik over all possible local requests. Access to the private backend still requires native credentials. Do not publish it as a public alternative URL; owner recovery goes through a trusted SSH/WireGuard path. Someone already having root/control over the node or a privileged workload is able to bypass this boundary.

`homelab-xui-panel-auth.service` is a persistent oneshot, before the k3s/VPN services, `CAP_NET_ADMIN`, only its own table. Stopping the service **does not open the port**. The installation was done by an explicit one-time cluster-owner Job: host PID/ROOT read-only, `SYS_CHROOT`, two writable managed directories, without a SA token. This is an administrative host operation, not a new right for ordinary workloads/SSH users; the sudo/SSH policy was not changed. The Job is removed by a TTL controller.

## Sources and repetition

- Gateway: `deploy/xui-auth-gateway/`, renderer `scripts/build-xui-auth-gateway.py`.
- The official unmodified upstream favicon: `icon-source.json`, a pinned revision/SHA256; a separate public immutable image endpoint, not an auth bypass for other resources.
- Argo Application: `deploy/argocd/apps/xui-auth-gateway.yaml`, `Synced/Healthy` is verified **before** switching the ingress.
- Public routes: `charts/traefik-edge/{values.yaml,templates/ingress.yaml}`. Activation does not change the Traefik Deployment/listeners.
- Host firewall: `deploy/xui-auth-gateway-host/`. `python3 scripts/xui-panel-firewall-job.py` only prints the reviewed Job. The owner applies it explicitly, waits for Complete, verifies the persistent service and the unavailability of public 18082. Do not leave this step "for later": otherwise the raw backend bypasses the gateway.
- A narrow IdP reconciler: `ansible/roles/identity_integrations/files/xui_gateway.py`, config `deploy/identity/xui-panel.json`. This is a separate forward-auth integration, not a replay of the whole foundation/controller.

On the owner node, the protected root `~/.cache/homelab-authentik/` contains the existing `credentials.json`, `xui-panel-journal.json` with the exact PK/UUID and `xui-panel-launch.json` with the full HTTPS URL of the native panel (`{"url": "…"}`). The files are 0600, the directory 0700; do not print/publish them. A provider/app with a matching name but without a protected journal is **not adopted**. The initial creation requires the launch file; a repeat `--action check` is read-only, `--action apply` reconciles only these managed objects/owner binding/outpost provider addition. An example after a protected delivery of files:

```sh
python3 xui_gateway.py ~/.cache/homelab-authentik xui-panel.json --action check
```

After a real check, `apply` is allowed, then another `check`; you must not change the real owner factors for tests. The new application root Argo applies from the published `main`, not by fighting selfHeal. The absence of the IdP is fail-closed for the public human panel, not a reason to open the raw port or remove the native MFA.

## Acceptance 2026-11-01/02

- Two independent fresh browser fixture runs: public edges 176.98.185.59 and 109.173.40.247, TLS/SNI is verified, the system DNS is not changed.
- A real native password/TOTP enrollment; an ordinary observer gets a native Permission denied. After a temporary exact user-binding it reaches **only the native 3x-ui password screen**, without a native login/VPN-administration access. Inspector 404, spoofed identity headers do not bypass the gateway, an invalid Bearer 401 even with a gateway cookie. All fixture users/bindings were removed.
- A real authenticated Trojan TLS/WebSocket tunnel before and after: HTTPS 200 to example.com. The test reads the active machine credential only in memory/a protected temporary config, does not print it and does not change the VPN server.
- 15 unique active subscriptions: 30 successful native text/JSON HTTPS responses without IdP HTML/redirect.
- The hashes of native users/settings/API tokens/inbound configuration matched; the original VPN pod UID/restart counts and the ingress pod template did not change. VPN/Traefik were not restarted. Only the **new** gateway was restarted when fixing/deploying its configuration.
- The first browser attempt found a relative nginx redirect to HTTP/backend port; it was fixed to the canonical public HTTPS and re-verified. The first host installer attempts finished before writing files (D-Bus PID visibility / a wrong name of the checked service); the successful install and the subsequent reload affected only the firewall oneshot. The early unsuccessful harness attempts are not counted as acceptance. A separate strict check "no IdP navigation after 5 minutes" did not pass; this is an explicitly kept native-proxy limitation, not a reason to increase the bearer lifetime.

A repeatable live test (explicit temporary identity/admission writes, not owner):

```sh
python3 scripts/identity-xui-gateway-smoke.py --run
python3 scripts/identity-xui-gateway-smoke.py --run --wait-refresh
python3 scripts/identity-xui-gateway-smoke.py --run --public-edge 109.173.40.247
python3 -m unittest discover -s tests -p test_xui_auth_gateway.py
```

A personal owner check of the native login/owner recovery and a valid-token API client remains separate: real passwords/tokens were not extracted for it. `minutes=5` access and `hours=8` refresh for the proxy provider are not a proven absolute eight-hour limit and not an eight-hour test. Logout does not guarantee the immediate closing of already-open WebSockets or the destruction of native 3x-ui sessions/API tokens.

## Rollback

Keep the private native recovery and the current firewall. First agree on an explicit removal of the MFA gate with the human route (returns a native-only public HTTPS login); do not touch the public VPN routes/backends. Only then remove the provider from the **current** embedded outpost list, keeping others' concurrent additions, and delete only the journal-owned application/provider/binding. Do not blindly restore the whole old outpost snapshot. Do not delete the native DB/credentials and do not reset MFA.

Do not delete the firewall as a side effect of rollback. To consciously remove it, the owner separately disables only `homelab-xui-panel-auth.service`, removes only the `inet homelab_xui_panel_auth` table and the managed unit/rules; no `flush ruleset` or restoring all node firewall rules.


## Login Failed to fetch: expired gateway XHR correction

Reproduced the reported error without real panel credentials: a fresh gateway
session accepted native CSRF + empty-login POST (200 JSON), whereas removing only
the fixture proxy cookie caused cross-origin OAuth redirects and browser
TypeError: Failed to fetch. This is the same unauthenticated branch reached after
proxy expiry, not evidence of a wrong native password.

Named auth-login now returns **401 without redirect** for native XMLHttpRequest,
fetch cors/same-origin, websocket, and unsafe methods. Only normal safe browser
navigation starts OAuth. Native 3x-ui3.11 already handles401 by top-level
location.replace; no custom login JS, POST replay, CSRF bypass or auth exemption.
After idle, a page reauthorization/reload can still occur and inputs may need
re-entry. Five-minute token lifetime and owner MFA/admission remain unchanged;
this does not claim silent proxy refresh.

Both public edges passed: fresh native CSRF/empty-login JSON; missing-cookie
fetch401 same-origin without redirect; **actual native login button** triggering
401 then recovering via top-level SSO. Synthetic form credentials never reached
the backend (response401 asserted); no owner password/OTP was read or reset.
Temporary observer/admission fixtures removed. Earlier selector-harness timeouts
were corrected to native autocomplete attributes and are not counted as passes.
Bearer-invalid401 and spoofed-header denial remain; VPN/public subscriptions,
Traefik and native x-ui were not changed/restarted. Only gateway rolled.
