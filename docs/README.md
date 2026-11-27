# Socrat operator documentation

Choose the narrowest route that answers the question. Nothing below is required reading in sequence.

| Starting point | Open |
| --- | --- |
| Where do I check metrics, logs, traces or alert delivery? | [Observability](observability/README.md) |
| How does the cluster fit together? | [System overview and sources of truth](platform/system-overview.md); [platform guides by task](platform/README.md) |
| I have a service, namespace, group or endpoint | [Entity lookup](entities.md) |
| I have a symptom or alert | [Symptom lookup](symptoms.md) |
| Why was this design chosen? | [Accepted decisions](decisions/) |
| What was actually tested, and when? | [Incidents](records/incidents/) or [handoffs](records/handoffs/); neither is a current operating procedure |
| Is this change allowed or safe? | [Operational boundaries](platform/operational-boundaries.md) and [repository checks](quality/README.md) |
| What is the plan for independent public web entrances? | [HOME, Moscow and NL ingress rollout plan](plans/independent-public-ingress.md) |
| Is this a proposal rather than an accepted change? | [Research and proposals](research/) |

The [public wiki](../wiki/README.md) has a separate audience and publication process.

## Runbooks by task

| Task | Reference |
| --- | --- |
| VM105 / socrat-5: MOS watchdog, K3s restart and guest reboot | [VM105 recovery runbook](platform/kubernetes/vm105-watchdog.md) |
| Authentik login wallpapers, image quality and RustFS media delivery | [Gallery architecture and runbook](applications/authwall/README.md) |
| Network onboarding, devices, JWT policies and node agents | [NetBird](network/netbird/README.md), [DNS](network/public-entry/public-dns.md) |
| Foreign egress for applications on Russian nodes | [Service VPN: dedicated 3x-ui client and subscription](network/vpn-egress/service-vpn-egress.md) |
| Moscow VPN frontend, NL backend, retained clients and known limits | [Production setup and history](network/vpn-egress/vpn-hardening.md), [acceptance and incident](records/handoffs/vpn-production-cutover-20261109.md) |
| SSH public keys, regular Linux accounts and revocation | [SSH users](auth/host-access/ssh-user.md), [host access and RBAC](auth/host-access/identity-host-access.md) |
| Observer group onboarding, Danila and revocation | [Native observer](auth/roles/observer/native-observer.md), [acceptance checks](records/handoffs/observer-acceptance-20261108.md) |
| Check which services enforce Authentik, native sign-in or public access | [Browser authentication audit](records/handoffs/browser-auth-audit.md) |
| Authentication, access and routine administration | [Authentication and access](auth/README.md), [operations](auth/authentik/operations/identity-operations.md) |
| B2C app groups, automatic provisioning and native roles | [Access contract](auth/applications/application-access.md), [technical runbook](auth/applications/app-access-groups.md) |
| External users changing passwords without internal dashboard access | [Password self-service](auth/authentik/operations/password-self-service.md) |
| OIDC, native app roles and gateway exceptions | [Architecture](auth/architecture/identity-architecture.md), [integrations](auth/authentik/integrations/identity-integrations.md), [troubleshooting](auth/authentik/integrations/identity-gateway-troubleshooting.md) |
| Optional SSH-key integration (disabled) | [UUID and key assignments](auth/host-access/identity-ssh-keys.md) |
| Theme, native UI and recovery | [Frontend](auth/authentik/custom-ui/README.md), [backup and recovery](auth/authentik/operations/identity-recovery.md) |
| Registry, robot accounts and scoped push/pull | [Harbor](platform/harbor/harbor.md) |
| Wiki runtime and content | [Lifecycle](applications/wiki/wiki-process-lifecycle.md), [upgrade](records/handoffs/wiki-upgrade-20261107.md), [public onboarding source](../wiki/README.md) |
| Per-node metric collection and retention | [OTel to Prometheus to Thanos: raw data, five-minute and hourly resolution, and deletion limits](observability/monitoring/observability-current.md#metric-collection-downsampling-and-node-migration-21-november-2026) |
| Logs, metrics, traces and profiles | [Current observability](observability/monitoring/observability-current.md), [monitoring](observability/monitoring/monitoring.md) |
| Incidents, notifications and workflow integration | [Socrat Bot](socrat-bot/README.md), [SPI frontend, backend and operations](applications/spi/spi-incident-triage.md) (see current context for placement), [n8n](n8n/n8n-workflows.md) |
| Lenovo USB tablet: ADB, Fully fullscreen, PostgreSQL dashboard and recovery | [Android tablet](applications/android-tablet/README.md) |
| TV dashboard, targeted Argo CSS and dedicated YouTube VPN | [Android TV](applications/android-tv/README.md), [maintaining the TV stylesheet](applications/android-tv/README.md#maintaining-the-argo-tv-stylesheet) |
| LMS and local generators | [LMS](applications/ai/lms.md), [local generation](applications/ai/lms-generation.md) |
| SWE Mini retirement | [Removal scope and verification](applications/ai/swe-mini.md) |
| OpenHands Canvas (installed; public sign-in and the full PR lifecycle not yet accepted) | [Verified behavior and blockers](applications/ai/openhands.md) |
| Venice browser bridge, Google session and LiteLLM model | [Current state and limitations](applications/ai/venice-api.md) |
| Dedicated DeepSeek web-session bridge, LiteLLM `o-deepseek` and rate limits to avoid a ban | [Status and limitations](applications/ai/deeperseeker.md) |
| Other subsystems | [RustFS](data/object-storage/rustfs-foundation.md), [smart home](applications/smart-home/smart-home-automation.md), [inference reliability](applications/ai/inference-client-reliability.md) |

[Official MCP connections for agents](platform/agent-access/official-mcp.md): project settings, service inventory, read-only scope and known blockers.
