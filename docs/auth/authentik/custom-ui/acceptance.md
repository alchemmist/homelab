# Historical browser acceptance

## Current boundary — 7 November, removal of external auth gates

11 obsolete Authentik Applications were removed (including the old Kuma bookmark-card)
and 10 Proxy Providers; outpost assignments were removed.10 native OIDC Applications,
their UUID/client credentials/callbacks/policy bindings are kept. n8n,3x-ui, Kuma
and Syncthing use their own login; SearXNG and published SPI artifacts
are public without Authentik and NetBird. Reader allows only GET/HEAD, checks the
manifest/hash and serves safe types inline. [Contract and boundaries](../../applications/native-browser-auth.md).

Re-acceptance after the socrat-2 recovery: **82/82** public checks
on HOME and VPS, an ordinary TLS check without disabling verification. All4 nodes Ready;
socrat-2 Ready from17:55:34UTC7 November. All8 affected Argo apps Synced/Healthy.
The old xui gateway Application/Deployment/Service/ConfigMap and Pod are absent; no
force-delete was needed.10 native OIDC registrations/providers/bindings and
the kept icon fields are unchanged; Proxy Providers0. A published artifact was
verified through both entries: anonymous GET/HEAD/206, manifest/SHA-256, inline,
PUT/POST/PATCH/DELETE405. [Acceptance](../../applications/native-browser-auth.md#recovered-vps-final-acceptance).
This is a protocol acceptance, not a new per-person login check.


> Current cut7 November: [logins, first login and native roles](../operations/identity-current-state.md),
> [NetBird/network](../../../network/README.md), [monitoring owners](../../../observability/monitoring/observability-current.md).
> The dated rollout/smoke below is the history of its own stage, not general readiness.

Start: [identity.md](../../architecture/identity.md). A detailed engineering runbook of the current design.
