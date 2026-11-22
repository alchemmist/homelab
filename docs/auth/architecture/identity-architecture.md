# Socrat authorization: architecture and trust boundaries

> **Current B2C contract:** [separate app groups and native roles](../applications/application-access.md).
> Eight enabled roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS;
> the remaining reserved groups do not imply access. Internal/External is not
> an app permission. The old owner-only/preparation snapshots below are history;
> browser E2E and instant revocation of all sessions/keys are not claimed.

> Current November 7 snapshot: [logins, first login and native roles](../authentik/operations/identity-current-state.md),
> [NetBird/network](../../network/README.md), [monitoring owners](../../observability/monitoring/observability-current.md).
> The dated rollout/smoke sections below are history of their stage, not general readiness.

Implementation snapshot **November 1, 2026**. Start of the reference: [identity.md](identity.md).
This describes the really deployed system and its limits, not a promise of a
completed migration of all endpoints. For changes, first reconcile the current
manifests and live state.

## 1. What exactly is centralized

Authentik is the Identity Provider (IdP): personal users, passwords, mandatory
MFA, groups, permission to enter applications, issuing OIDC tokens. Applications
remain separate systems with their own data, local IDs, rights, sessions and API
keys.

Do not mix four different layers:

1. **Network:** NetBird is the primary human ingress; the inter-node WireGuard
   and the separate recovery WG are preserved. Public ingress/TLS/NetworkPolicy
   are separate boundaries.
2. **Authentication:** who the person is and how they proved identity; here
   Authentik/MFA.
3. **Authorization:** which applications, projects, namespaces and operations
   they are allowed.
4. **Machine credentials:** robots, service accounts, virtual keys, webhooks, MCP.

A successful MFA does not automatically grant cluster-admin. A visible tile does
not prove the backend uses SSO. Access to an IP/port is not access to data. OIDC
does not migrate the user base and does not merge accounts by itself.

## 2. Actual placement

- Public IdP: **https://auth.socrat.alchemmist.xyz/**.
- Namespace `identity`, Authentik chart/app **2026.8.5**.
- One replica each of server and worker on `socrat-0`; PostgreSQL **17.11** there
  too.
- PostgreSQL external to the chart: StatefulSet/Service `authentik-postgres`.
- `authentik-data`: PVC for `/data`; the DB has separate persistent storage.
- PVs are kept with `Retain`; that protects against accidental claim deletion,
  it is not a backup.
- Runtime Secret `authentik-runtime`; ServiceAccount `identity-runtime`, without
  an automatically mounted API token. The server/worker must not manage the
  cluster.
- The embedded outpost serves the n8n proxy integration. No need to place an
  outpost in front of every application: for native OIDC the browser goes
  straight to the application.
- The Quiet Mono static files — a separate sandboxed nginx `socrat-authentik-theme`,
  also on `socrat-0`. Details in [identity-frontend.md](../authentik/custom-ui/README.md).

Sources: `deploy/authentik/values.yaml`, `foundation.yaml`, the
`ansible/roles/authentik/` role, playbook `ansible/playbooks/authentik.yml`.
The chart is pinned by version and SHA-256 in the role defaults; assets and
nginx by hashes too. Do not rewrite the version guard until a new version has
been verified.

**This is not HA.** Two public ingress IPs and several control-plane nodes do
not replicate the IdP PostgreSQL, PVC or `/data`. Losing `socrat-0` can take away
new logins and styling. Already issued sessions of some applications may keep
working, but that is not a guarantee. Distributed HA, independent backups, key
escrow and full DR are separate tasks.

## 3. Server, worker, DB and frontend

The server serves the API, flow executor, OIDC endpoints, UI and the embedded
outpost. The worker runs background tasks. PostgreSQL contains users, groups,
flows/stages, providers/applications, bindings, tokens and service state. The
installation's secret key, signing keys and client secrets are part of the
system's identity: restoring the DB alone without the matching secret material
is insufficient.

The frontend is **Authentik's stock Lit/Web Components**, not our own form with
its own password validation. Pages have nested shadow roots; the flow executor
receives a challenge from the server and loads the needed native stage. Our
production frontend is Brand CSS + local static files + a few explicitly managed
presentation fields. The synthetic offline prototype in `prototypes/authentik/`
does not participate in authentication.

Do not carry over a stale generic Redis recipe from some other version here: our
manifests and the pinned chart define the deployed composition.

## 4. Authentik objects

| Object | Role |
|---|---|
| User | Personal identity, UUID, activity, groups, MFA devices |
| Group | A set of users; a group name can go into signed claims |
| Flow | An authentication / authorization / invalidation / enrollment scenario |
| Stage | One step: identification, password, MFA, consent, login etc. |
| Stage binding | Order/conditions for including a stage in a flow |
| Plan | The computed flow execution with context and current bindings |
| Provider | OIDC/proxy protocol config, callbacks, signing key, scope mappings |
| Application | Tile/launch URL and the link to a provider; admission policies |
| Property/scope binding | Access condition for an application/object: a group or policy |
| Property/scope mapping | Claim-building code; security-sensitive configuration |
| Brand | Domain, logo/favicon/background, CSS, language/theme defaults |
| Outpost | Proxy/forward-auth component for non-native integrations |

The default flow names matter to the reconciler. Do not rename or delete them
blindly: automation looks for specific slug/name and must stop on ambiguity.

## 5. The ordinary login path

```text
browser -> application -> authorize with Authentik
                       -> admission / authentication flow
                       -> password + MFA if no live session yet
                       -> authorization flow / consent
                       -> the application's exact callback with a one-time code
application -> Authentik token endpoint (client credentials + PKCE verifier)
           -> token/identity validation -> the application's own session
```

OIDC uses the authorization code, not the user's password in the application.
`state` ties the callback to the initiated request; `nonce` ties the ID token to
this login; PKCE ties the code to the initiator. The application checks issuer,
signature, audience, expiry and other protocol invariants. Do not disable TLS
verification.

If an Authentik MFA session already exists, repeated password prompts may not
appear. A brief `Redirecting` is a normal transition, not a new login and not an
error. Login via the tile and via the application's SSO button must lead to the
same trusted IdP. An old local application session may not trigger OIDC until
logout/expiry. To verify a new login, use a separate private browser context,
not an owner MFA reset.

## 6. Endpoints and subjects

For foundation-managed OIDC, the standard endpoints on the IdP:

- authorize: `/application/o/authorize/`;
- token: `/application/o/token/`;
- userinfo: `/application/o/userinfo/`;
- issuer/discovery of a specific application: `/application/o/<slug>/` and its
  `.well-known/openid-configuration` (check the installed version's metadata).

The issuer must be copied exactly, including path/trailing slash. Do not pick
the issuer from an untrusted token payload and do not allow an arbitrary
discovery URL. Callbacks are exact HTTPS URLs with `matching_mode: strict`, no `*`.

**The immutable subject is not the email and not the username.** Some of our
providers use `sub_mode: user_uuid`; others keep the previous `hashed_user_id`.
One must not change the subject mode after enablement and expect the application
to recognize old accounts. `request.user.uuid` is the Authentik record's UUID;
the `uid` in Authentik can depend on the installation's secret key and is not a
replacement for this UUID. The LiteLLM mapping explicitly uses the UUID; this
was fixed after checking the upstream source.

Where data already exists, a reviewed map is composed before the first login:
**Authentik subject/UUID -> a specific existing application user ID**. Neither
a matching email nor an identical display name proves ownership of the old
account. Registry: `deploy/identity/account-mappings.json`; the real UUID/IDs
there are metadata, not bearer credentials. Do not add passwords or tokens to
this file.

## 7. Admission, app roles and sessions — different checks

`deploy/identity/services.json` defines the foundation apps, callbacks, admitted
groups, icons and protocol hints. An application's `groups` limit the ability to
pass through the IdP; role mapping inside the application determines the final
rights. The foundation application common policy is `any`: one permitted group
suffices. This does not mean “let everyone in”, but an extra permissive binding
is dangerous.

Observer admission to an application must not automatically give Editor/Admin.
An IdP superuser and an app admin are different roles, connected only by
explicit mappings. Even after revoking the IdP group, an already issued app
cookie may remain valid. Logging out of one application, logging out of Authentik
and revoking all app sessions are not the same. See the full offboarding
procedure in [identity-operations.md](../authentik/operations/identity-operations.md).

## 8. Login to an application grants no SSH / kubectl

Full procedure: [Linux/SSH and RBAC](../host-access/identity-host-access.md).

Linux and Kubernetes are separate perimeters. On the four nodes personal SSH
public keys are configured, password logins of managed restricted users are
closed, and there is no implicit sudo/docker/root-equivalent membership. Keys
are assigned per host.

`/etc/rancher/k3s/k3s.yaml` on `socrat-0`: **0640 root:alchemmist**, owner-only
group. The file used to be world-readable; the chmod stops new reads but does
not revoke the admin certificate copied earlier. The historical exposure must be
assessed separately; a CA rotation was not performed in that work.

The `homelab-project-observer` ClusterRole exists without human bindings.
get/list/watch of specific workload/network objects is allowed; no Secrets,
exec, logs or node access. An IdP group name does not itself become a
Kubernetes/Rancher principal. A namespace RoleBinding and project grants need a
separate owner decision.

A node's root is a trust boundary for that node's workloads/secrets. RBAC cannot
make root an untrusted observer of the pods running there. A namespace maintainer
able to create pods/exec can also potentially reach the namespace's secrets. Do
not call these powers a harmless read-only.

## 9. Network and public entrances

The current public edges are `109.173.40.247` and **`109.120.141.97`**. The old
`176.98.185.59` is history before November 5. The reviewed Grafana/Rancher
entrances are public with native SSO/roles; Grafana MCP is bearer-only. Ordinary
public DNS works without Mac overrides; anonymous org access to Grafana is off.
Only the agreed traffic-light native share is available without login. Do not
publish additional private APIs for branding/healthcheck reasons.

NetBird is the primary human ingress; standalone WG is recovery; the inter-node
WG is preserved; we do not touch the mandatory Mac Tunnelblick. The user/device
approval requirement is off, but personal MFA/genuine JWT admission are
preserved. There is no automatic app/Linux/Kubernetes grant. Four routing agents
and two relays give bounded data-plane redundancy; management/Signal and
Authentik are not HA; a cold start without management previously failed.
Current lifecycle/overlay guard/Mac/TV cleanup:
[network-access.md](../../network/README.md), [NetBird](../../network/netbird/README.md).

Harbor provides private images/robots for workload delivery, but its OIDC does
not replace registry robot passwords. Harbor HA is also deferred; see
[harbor.md](../../platform/harbor/harbor.md).

## 10. What not to consider finished

- The Kuma public/admin boundary is closed, but native OIDC is not deployed;
  n8n is an MFA gateway, not native SSO. Exhaustive owner/app recovery
  acceptance remains separate.
- A full inventory of all human auth paths and the lifecycle of old sessions is
  still needed.
- The owner-only local fallback is fully server-side verified for the wiki; do
  not extend this conclusion to the whole cluster. LiteLLM keeps the owner DB
  password, but its real recovery acceptance is separate from the confirmed
  owner SSO.
- Tim must receive credentials safely and register a personal factor; a fixture
  TOTP does not prove his personal readiness. SSH private-key acceptance is
  separate too.
- Scheduled independent backups, key escrow and full DR are not implemented by
  the mere existence of manual backup scripts. The old bootstrap token is
  retired; the new machine API is still broad; its scoped RBAC/rotation is a
  separate task.
