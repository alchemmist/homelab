# Socrat operator documentation

[Current state](context/context.md) · [Change checks](quality/README.md) · [Infrastructure contracts](infrastructure-contracts.md) · [Public wiki](../wiki/README.md)

[Unexpected loss of `socrat-1`, 21 November 2026](context/socrat-1-loss-20261121.md): observed recovery times, recovery limits and outstanding checks. The [second outage that day](context/socrat-1-loss-20261121-run2.md) tested a separate Alertmanager on node `0` without changing the PostgreSQL primary.

For authorization changes, see [B2C application groups](application-access.md). The [placement and ownership map](context/context.md) was updated on 16 November 2026. The network overview describes the 10 November snapshot (Moscow VPN Pod/native operation, shared mesh, fallback acceptance and SPI service extraction); the observer snapshot is from 8 November. Other sections carry their own dates. This is an operator reference, not public wiki content or a script for repeating migrations. Git records intent; check the running system separately.

The owner deferred the RF/NL server split. Moscow still exits through NL, and the existing Happ bypass remains in place. See [VPN transit internals](vpn-mesh-runtime-20261110.md#what-the-pod-actually-does). Research is not a deployment request. Private recovery evidence stays outside Git.

## Start here

- [PostgreSQL: placement, guarantees and what was verified](postgresql.md)
- [pgAdmin: Authentik sign-in, read permissions and writer connectivity](pgadmin.md)
- [Redis Insight: Authentik groups, dashboard access and revocation](redisinsight.md)
- [Shared Redis: writer endpoint, guarantees and LiteLLM integration](redis-common.md)

1. [Current context](context/context.md): topology, constraints and operating procedure.
2. [Network access](network-access.md): NetBird is the primary route for people. Inter-node WireGuard remains in place; standalone WireGuard is for recovery only. Leave corporate Tunnelblick unchanged.
3. [Identity](identity-current-state.md): `antropophag`, passwords and first sign-in, native app links, Umami limitations and the lack of automatic invitations.
4. [Deployment](cluster-deploy.md): Git to Argo CD, per-application ingress and the image release contract.
5. [Observability](observability-current.md): monitoring owners, paused legacy applications, sources, status and verified placement. For gaps in charts, see [diagnosing missing recent metrics in Thanos](observability-current.md#пропуски-свежих-метрик-в-thanos--19-ноября-2026).

## Runbooks by task

| Task | Reference |
| --- | --- |
| Network onboarding, devices, JWT policies and node agents | [NetBird](netbird.md), [DNS](public-dns.md) |
| Foreign egress for applications on Russian nodes | [Service VPN: dedicated 3x-ui client and subscription](service-vpn-egress.md) |
| Moscow VPN frontend, NL backend, retained clients and known limits | [Production setup and history](vpn-hardening.md), [acceptance and incident](vpn-production-cutover-20261109.md) |
| SSH public keys, regular Linux accounts and revocation | [SSH users](ssh-user.md), [host access and RBAC](identity-host-access.md) |
| Observer group onboarding, Danila and revocation | [Native observer](native-observer.md), [acceptance checks](identity/observer-acceptance-20261108.md) |
| Check which services enforce Authentik, native sign-in or public access | [Browser authentication audit](browser-auth-audit.md) |
| Identity reference and routine administration | [Identity](identity.md), [operations](identity-operations.md) |
| B2C app groups, automatic provisioning and native roles | [Access contract](application-access.md), [technical runbook](identity/app-access-groups.md) |
| External users changing passwords without internal dashboard access | [Password self-service](password-self-service.md) |
| OIDC, native app roles and gateway exceptions | [Architecture](identity-architecture.md), [integrations](identity-integrations.md), [troubleshooting](identity-gateway-troubleshooting.md) |
| Optional SSH-key integration (disabled) | [UUID and key assignments](identity-ssh-keys.md) |
| Theme, native UI and recovery | [Frontend](identity-frontend.md), [backup and recovery](identity-recovery.md) |
| Registry, robot accounts and scoped push/pull | [Harbor](harbor.md) |
| Wiki runtime and content | [Lifecycle](wiki-process-lifecycle.md), [upgrade](wiki-upgrade-20261107.md), [public onboarding source](../wiki/README.md) |
| Per-node metric collection and retention | [OTel to Prometheus to Thanos: raw data, five-minute and hourly resolution, and deletion limits](observability-current.md#метрики-сбор-прореживание-и-перенос-между-нодами--21-ноября-2026) |
| Logs, metrics, traces and profiles | [Current observability](observability-current.md), [monitoring](monitoring.md) |
| Incidents, notifications and workflow integration | [Socrat bot](socrat-bot.md), [SPI frontend, backend and operations](spi-incident-triage.md) (see current context for placement), [n8n](n8n-workflows.md) |
| TV dashboard, targeted Argo CSS and dedicated YouTube VPN | [Android TV](android-tv.md), [maintaining the TV stylesheet](android-tv.md#сопровождение-кастомного-tv-css-для-argo) |
| LMS and local generators | [LMS](lms.md), [local generation](lms-generation.md) |
| SWE Mini retirement | [Removal scope and verification](swe-mini.md) |
| OpenHands Canvas (installed; public sign-in and the full PR lifecycle not yet accepted) | [Verified behavior and blockers](openhands.md) |
| Venice browser bridge, Google session and LiteLLM model | [Current state and limitations](venice-api.md) |
| Dedicated DeepSeek web-session bridge, LiteLLM `o-deepseek` and rate limits to avoid a ban | [Status and limitations](deeperseeker.md) |
| Other subsystems | [RustFS](rustfs-foundation.md), [smart home](smart-home-automation.md), [inference reliability](inference-client-reliability.md) |

## Interpreting historical results

- “Synced/Healthy”, test results, screenshots and counters apply only to the resource and time recorded. Do not add counts across suites or generalize an owner or fixture test to a new user, another device or ISP, or full disaster recovery.
- `tim` in old identity-provider logs is a former login. The Linux account `tim`, Rancher resource names and `wg-socrat` are separate identifiers; do not rename them in bulk.
- NetBird access does not grant SSH, sudo or cluster-admin rights. Authentik MFA does not replace application RBAC.
- Pushing an image or commit does not prove rollout. Check auto-sync settings and hooks.
- Historical migration scripts can change production. Before running one, perform a fresh audit, verify scope, UID and hash, make a private backup and check locking or compare-and-swap protection. Investigate uncertain writes before retrying.
- Never publish credentials, QR codes, private keys, subscriptions or share, recovery or activation URLs that contain tokens. A public hostname does not imply anonymous API access.

The 9 November revision incorporated the completed production VPN acceptance and resolved incident. Editing this reference does not perform a rollout, verify runtime state, sign in on a user's behalf or repeat a VPN or DNS migration.

[Official MCP connections for agents](official-mcp.md): project settings, service inventory, read-only scope and known blockers.
