# Public HTTPS application entry: current native-auth contract

Updated7 November 2026. The previous universal browser MFA proxy rollout is
superseded by [native browser authentication](identity/native-browser-auth.md).
Public web access requires neither NetBird nor local resolver overrides. Node SSH,
databases, Kubernetes APIs and telemetry receivers retain their private boundaries.

## Current entries

| Service | Public browser route | Authorization |
|---|---|---|
| Grafana | Existing native OIDC route and presentation filter | Native roles, personal Authentik MFA, anonymous off; machine bearer preserved |
| SearXNG | Direct service ingress | Public, no login or NetBird |
| Open WebUI / LiteLLM aliases | Direct native application ingress | Native OIDC, same accounts/roles/chats/API keys |
| Rancher | Existing native OIDC/password-restriction route | Existing restricted principals; agents/API/WebSocket/private recovery preserved |
| Grafana MCP | Existing `/mcp` route | Native bearer, read-only identity; no browser redirect |
| Syncthing node0 `/sync/` | Path adapter, no external auth | Native GUI login enabled before cutover; API key/devices/data retained |
| Syncthing node1 `/sync/` | Explicit410 | Gateway-only, not an enrolled device |
| Kuma admin | Direct `kuma.socrat.alchemmist.xyz` ingress | Native Kuma login |
| Kuma public status | Existing narrow status/push filter | Anonymous approved reads, native-token push, admin/socket paths restricted |
| n8n | Direct existing native ingress; machine endpoints remain separate | Native login; `/rest/workflows` anonymous401; setup closed |
|3x-ui | Direct existing panel backend | Native3x-ui login; backend firewall and VPN/subscription paths retained |
| RustFS console | Routing-only bridge to9001 | Native RustFS OIDC; private S3/root/writer credentials |
| Published SPI evidence | Direct read-only reader | Anonymous stable GET/HEAD, validated paths/manifest/hash, safe inline MIME/ranges |

There is no `public-web-entry` aggregate owner and no `xui-auth-gateway` Argo
Application. Existing application owners own their native routes; aliases do not
need separate Authentik Applications.11 obsolete IdP apps and10 Proxy Providers
were removed, while all10 native OIDC apps/providers/clients/bindings were retained.
The icon manifest targets only those native applications.

## Verification, not a blanket readiness claim

Run `python3 scripts/check-public-web-entry.py` for forced-public TLS/native
negative probes. It must not expect obsolete `/outpost.goauthentik.io/start`
redirects for native-login/public services. Browser files are opened by native
viewers, not a script-heavy wrapper; active/unknown formats remain attachments.

Final recovered-VPS result:82/82 passed across both public entrances. All4 nodes
Ready; socrat-2 recovered at17:55:34UTC7 November. All8 affected applications,
including traefik-edge, are Synced/Healthy. Old xui gateway Application,
Deployment, Service, ConfigMap and Pods are absent; no force-delete was needed.
Anonymous artifact GET/HEAD/206 and SHA-256/manifest/inline were verified through
both entrances; PUT/POST/PATCH/DELETE return405. All10 native OIDC registrations,
providers and policy bindings remain unchanged; Proxy Providers0. Only computed
media URLs differed from the original snapshot; stored meta_icon fields match.
The prior Caddy/TLS and Node Unknown failure is a resolved historical blocker.
This recheck made no infrastructure, VPN or global DNS/route mutations.

Historical5–6 November receipts (including134/134 TLS/public checks and117 focused
checks) remain receipts for their original stage, not substitutes for the recovered-VPS
acceptance above. Native human first-use/independent ISP/physical TV/DR acceptance is
not inferred from API probes or synthetic fixtures.
