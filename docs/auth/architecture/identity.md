# Socrat cluster authorization: the master reference

> **Current B2C contract:** [separate app groups and native roles](../applications/application-access.md).
> Eight enabled roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS;
> the remaining reserved groups do not imply admission. Internal/External is
> not an app permission. The old owner-only/preparatory snapshots below are
> history; browser E2E and instant revocation of all sessions/keys are not
> claimed.

> Current November 7 snapshot: [logins, first login and native roles](../authentik/operations/identity-current-state.md),
> [NetBird/network](../../network/README.md), [monitoring owners](../../observability/monitoring/observability-current.md).
> The dated rollout/smoke sections below are history of their stage, not
> general readiness.

**The identity foundation is November 1, 2026; network/public access updated November 6.** The owner's verification of LiteLLM and the native inspector/redirect controls belong to the original identity session. This is a consolidated description of the whole session: how login, MFA, rights, integrations, frontend, deployment and recovery are arranged. It contains no
passwords, tokens, MFA seeds, browser sessions or private saved HTML.

**Updated November 2, 2026:** gateway/SSO limitations, the 3x-ui Login fix, the open n8n diagnostics and the current frontend. The preliminary n8n checks do not mean the owner's issue is closed.


**Network closeout November 6:** [the current summary](../../network/README.md) takes priority over the older journal below. Public HTTPS needs no Mac overrides; Grafana anonymous org access is off, native Viewer/Editor/Admin are separated; the Kuma status/admin boundary is closed without native OIDC; NetBird primary, standalone WG recovery, Tunnelblick kept; the internal TV WG and the temporary TV domain are removed.

## Read by task

| Question | Section |
|---|---|
| How Authentik, OIDC, sessions and trust boundaries work | [Architecture](identity-architecture.md) |
| How to log in, add a person, grant/revoke rights, work with MFA | [Daily operations](../authentik/operations/identity-operations.md) |
| Double login, consent offline_access, Failed to fetch, the open n8n issue | [SSO and gateway diagnostics](../authentik/integrations/identity-gateway-troubleshooting.md) |
| What was done for each service and how to connect the next one | [Integrations](../authentik/integrations/identity-integrations.md) |
| The VPS/DNS/public entrances/Mac/TV outcome and security boundaries | [Network and access](../../network/README.md) |
| How NetBird works, adding an admin/node, failover status | [NetBird: current reference](../../network/netbird/README.md) |
| How to add a username + public SSH key to the nodes with one Ansible playbook | [SSH: short instructions](../host-access/ssh-user.md) |
| How Linux/SSH, sudo, kubeconfig and Kubernetes RBAC are separately arranged | [Host access](../host-access/identity-host-access.md) |
| Where the frontend/CSS, shadow DOM, photos/fonts/icons, inspector, rollback live | [Quiet Mono frontend](../authentik/custom-ui/README.md) |
| Backups, restore checks, incidents, diagnostics, tests and a safe push | [Recovery and maintenance](../authentik/operations/identity-recovery.md) |

This is a unified reference made of several files, not independent sources of
policy. The real configuration is the source-controlled manifests/controllers
plus the runtime Authentik/app state; the detailed file map is in the sections.
Before operating, check the version and live state. The old notes below are an
implementation journal, not the current list of open tasks; later acceptance and
fixes are described above.

## Brief current status

- Portal: **https://auth.socrat.alchemmist.xyz/**, Authentik **2026.8.5**,
  server/worker/PG17.11 on `socrat-0`, retained PVC. **Not HA**.
- The owner `alchemmist` is a personal MFA identity, the only member of
  `homelab-owner`. `akadmin` was decommissioned after a separate API migration;
  recovery is node-admin. The Outpost and identity-automation machine accounts
  are not people. See [admin automation](../authentik/operations/admin-automation.md).
- Tim's login is **`antropophag`**, a new stock IdP identity with a pinned UUID.
  As of the November 7 check no password is set, no MFA/first login. The old
  separate activation flow is deleted; SMTP invitation/recovery is not
  configured. App data preserved; Rancher uses the new native SSO record with
  the same grants. Current contract:
  [identity-current-state.md](../authentik/operations/identity-current-state.md).
- Native SSO: Grafana, Harbor, Rancher, Open WebUI, Wiki, LiteLLM; Argo CD has
  its own separate native OIDC controller. Their roles/limitations differ.
- **LiteLLM owner SSO confirmed by the owner.** Owner-only admission, the
  reviewed UUID → the existing `socrat-admin`; machine API keys preserved. The
  recovery password was not reset and is not considered verified by this
  confirmation.
- n8n is an Authentik MFA gateway, **not native account SSO**. Kuma has a
  separate MFA-gated admin entrance and a public status, **without native
  OIDC**.
- Foundation registry: eight apps plus Argo CD separately, with local icons.
  Additional public gate applications are managed by `deploy/public-web/services.json`;
  nine is not the total of all current entrances.
- Quiet Mono v5 runs on top of the native executor, without replacement auth
  JS. `Redirecting` without raw `%(app)s`; the Follow redirect anchor styled;
  the magnifier aligned; native history preserved, height-limited, not
  prototype-generated.
- The language picker is hidden, default English/light; old URL/session locale
  overrides are not yet forced to English. Native JSON highlighting/Copy is a
  separate backlog item.
- Machine APIs/MCP/robots/webhooks are not moved to browser redirects. The
  inter-node WireGuard is preserved; NetBird is deployed as the human ingress
  under Argo CD.
  [Current scheme and adding an admin](../../network/netbird/README.md); do not
  disable the legacy recovery WG. A full cluster-wide human-auth inventory,
  offboarding/old-session enforcement, independent backups/DR and HA are not
  finished yet.

## Quick orientation in the sources

`deploy/identity/{services.json,account-mappings.json,access-policy.yaml}` —
intent and reviewed linking; `ansible/roles/authentik/` — the IdP foundation;
the `identity_integrations` role — native backend reconciliation;
`deploy/authentik/quiet-mono/` — the production theme and frozen reference;
`assets/service-icons/` — pinned artwork; `scripts/identity-*` —
audit/backup/acceptance tools. Not all scripts are read-only: the fixture smokes
and the restore check modify test resources; run them consciously.

The older records below are kept as historical evidence. Mentions of “LiteLLM
not yet migrated”, “seven apps” or a former Git stage do not cancel the current
status and the detailed runbooks above.

---

# Historical implementation records (read with the reference above in mind)

**November 1, 2026, after the second rollout.** The user confirmed working
under `alchemmist`, reported the Grafana failure and allowed applying
sudo/further migration. **At that stage NetBird was excluded from the scope;
that ban was later lifted by a separate task. Current state:
[NetBird is deployed](../../network/netbird/README.md).** Preserve unrelated
OTel/VPN changes.

## What works

- **Authentik:** https://auth.socrat.alchemmist.xyz/, chart/app **2026.8.5**,
  pinned SHA-256; server + worker + PG17.11 on socrat-0, retained local PVCs.
  **Not HA**.
- Mandatory MFA. The owner `alchemmist` has already logged in and set up his
  factor. Do not register other devices' MFA for him/do not reset the password
  over a stale initial file.
- Only `homelab-owner` is superuser; its only human is alchemmist.
- At the initial stage a **tim** account, the **homelab-observer** group and
  the private `tim-login.json` were created. **That initial credential is no
  longer valid:** on November 7 the account was recreated and renamed to
  `antropophag`, no password set. Do not pass around the old file and do not
  claim a completed first login; there is no SMTP invitation.
  [Current status](../authentik/operations/identity-current-state.md).
- Nine current tiles with local SVG icons uploaded into Authentik's own media
  store; all icon URLs verified 200. Assets/hash/attribution:
  `assets/service-icons/`.

## Grafana: the cause of the error and the fix

`Login provider denied login request` was due to a **disallowed grant_type**.
For new OAuth providers explicitly set
`grant_types=[authorization_code,refresh_token]`. Do not disable TLS/MFA and do
not widen groups while trying to fix this protocol error.

**Native OIDC + PKCE is active**, owner → **GrafanaAdmin**,
`app-grafana-editor` → Editor, other admitted groups → Viewer. Insecure
email-based linking is off. **Anonymous org access is off**, public
Basic/password login is blocked; private recovery is kept. The only
no-login exception is the native public share `socrat-traffic-light`, not the
whole organization.

A full HTTP browser-equivalent flow was verified with a temporary observer:
password → TOTP → consent → code/PKCE → `/api/user` and the Viewer role, not
server-admin. Test identities were deleted from both Authentik and Grafana.
Script: `scripts/identity-grafana-smoke.py`. Never use the real owner
password/TOTP for an automated smoke. The private Grafana nginx deliberately
strips the Authorization header; admin cleanup goes through the internal
service from the owner node, without weakening the gateway.

## The remaining services

- **Harbor — native OIDC enabled**, `systeminfo.auth_mode=oidc_auth`. The
  supported CONFIG_OVERWRITE_JSON from a Secret was used; the initial admin
  password was not reset. An encrypted off-node backup was made before. The
  pull-only robot, after the switch, got the private BusyBox manifest 200, the
  digest preserved. Local admin is break-glass. Browser owner login still
  needs a human acceptance check.
- **Rancher — native Generic OIDC + PKCE enabled**, restricted exact-UUID
  principals. The immutable principalIds of old users are NOT bypassed via a
  webhook bypass. External `u-authentik-alchemmist` and `u-authentik-tim` were
  created; the verified former Rancher GlobalRole/ClusterRoleTemplate/
  ProjectRoleTemplate grants are mirrored to them. The old local identities
  remain emergency/transition. These are separate identities, not rewritten
  local IDs; native controllers generate the K8s RBAC. Stale managed mirrored
  grants are removed during reconciliation. A real browser acceptance by the
  owner/Tim is needed; the mere presence of the provider is not enough.
- **Open WebUI — native OIDC enabled**. The two former user IDs and chats are
  preserved, linked via the exact Authentik UUIDs and the application model
  method. Email auto-merge is off. Reviewed mappings in
  `deploy/identity/account-mappings.json`. Owner admin, Tim user. Public
  canonical and known private callback strict allowlist. The local emergency
  login is kept; the owner must check the ordinary browser flow.
- **n8n — an MFA/group gate on the UI and REST via an embedded Authentik
  proxy**, owner only. **NOT native account SSO**: the corresponding native
  integration needs a license; n8n can ask for its own password after
  Authentik. The UI and `/rest/settings` give 302 through both IPs. The
  machine endpoint ingress has higher priority and goes straight to n8n:
  webhooks, forms, health, the native `/api/v1` and credential OAuth callbacks
  do not depend on the IdP. Verified: health200, no-key API401, missing
  webhook404, not a login page.
- **Wiki — native OIDC enabled 2026-11-01**, `/login` leads to Authentik. Only
  the owner keeps the local fallback `/login?local=1` (username `admin`, the
  current password). Tim keeps his former editor ID/role by exact UUID; his
  local password/old local sessions are not accepted. The other observers are
  readers. A real temporary observer password/TOTP/consent/OIDC/PKCE passed,
  write403; the MCP read works. Source/image/chart and backup:
  `deploy/wiki-runtime/oidc/README.md`. The initial saved owner password is
  stale401; we did not reset it; the hashes of the original two users are
  preserved. The direct WG-IP:443 currently serves a foreign cert due to
  missing Wiki VHs in the live gateways; public on both IPs works. Do not
  disable TLS and do not blindly run the old wiki-editor-access role against
  the already-removed private gateway.
- **The Kuma boundary closed November 6:** public status/read/push are
  separated from the personal-MFA admin host and native account controls; the
  public Socket.IO is closed. There is still no native OIDC. The credential
  recovery incident with a ~35min heartbeat gap is reflected in the
  [network summary](../../network/README.md).
- LiteLLM, CI/robots, MCP/API, VPN and other machine credentials are not to be
  replaced by SSO. The catalog covers the eight foundation-managed portal
  services (Argo CD separately), not literally every cluster endpoint.

## Linux / kubeconfig — already fixed live

On socrat-0 there was a root:root **0644** admin kubeconfig. Now
**root:alchemmist 0640**, the owner group's exclusivity checked, the K3s
mode/group preserved both in the live config and in the initial install/HA
templates. The owner's kubectl works; Tim cannot read the credential.

The users role was applied on **all 4 nodes**: exact authorized_keys instead of
append, present/disabled states, hosts, a ban on root-equivalent
groups/implicit sudo. A root check on all nodes: 2 intended Tim keys, pubkey=yes,
PAM=yes, effective sudo denied, the admin kubeconfig inaccessible. We do not have
Tim's private key; an actual network SSH login as him was not emulated.

`sudo -l -U tim` can return rc0 even with "not allowed" text; the verifier
checks the policy text in the C locale, not only rc. On Arch mind the shell OSC
markers. `ansible/roles/users/files/verify.py` prints only safe metadata.

The owner's sudo password must NOT be stored in Git/inventories/logs. sudo
worked on all four nodes; the socrat-3 inventory was switched from su to the
verified sudo. The temporary helper/inventory files used were deleted; the
helper only read transient environment, not the password. Do not repeat the
secret from chat.

**Important:** chmod does not revoke a previously copied cluster-admin client
certificate. The historic exposure/rotation plan is to be assessed separately.
The CA was not rotated, the nodes were not powered off. The observer
ClusterRole still has no human bindings; an IdP group is not equal to a
kube-apiserver/Rancher principal. No new cluster-admin kubeconfigs to people.

## Sources and reconciliation

- `docs/auth/architecture/access-management.md` — the current matrix,
  operations and limitations.
- `deploy/identity/{services,account-mappings}.json` — reviewed
  services/identities.
- `ansible/roles/authentik/`, playbook `authentik.yml` — the foundation and
  the proxy gate.
- `identity-integrations.yml`, explicit `identity_oidc_services` (default
  empty).
- The Grafana/Harbor Helm charts load separate identity overlays on the
  activation Secret.
- The WebUI playbooks deployment/HTTPS/upgrade/tool-guard import the
  conditional `identity-webui-reconcile.yml` so the following Helm changes do
  not erase OAuth.
- Do not overwrite the OTel changes in the shared files; do not run a full
  monitoring upgrade for the sake of auth. Do not disable ordinary local login
  before a verified emergency path.

## Backups and unfinished work

Encrypted AES-256-GCM backups outside Git on the Mac `~/.config/homelab/`, key
`identity-backup.key` 0600, never sent into the cluster. CLI:
`identity-backup.py --service authentik|harbor|open-webui`,
`identity-restore-check.py --service ...`.

Verified: isolated Authentik PG restore; Harbor PG18 restore + 3 blob SHA-256;
WebUI SQLite integrity + the two original user IDs. This is **not full app/site
DR**. The WebUI restore check uses a private temporary SQLite file with
cleanup because of the WAL header. The archives are encrypted; do not copy
plaintext credentials into evidence/Git.

Open: exhaustive app/role acceptance and the owner-only legacy fallback in the
other apps, the n8n native license decision, owner/Tim browser acceptance of
the other apps, coordinated onboarding/offboarding and session revocation,
API keys/SSH/VPN, scheduled independent backups/key escrow/full restore,
scoped RBAC/rotation of the new machine admin API, the historic kubeconfig
exposure/rotation. Disabling the IdP does not automatically revoke already
issued app/API/SSH credentials.

During the November 1 identity session, WG keys/routes/firewall were not
changed; **this is not a description of the subsequent network work of
November 5–6**, listed in the [summary](../../network/README.md). Do not
assign one subnet to several direct WG peers: a gateway+ACL/failover is
needed. Root on another person's node = trusting the workloads/secrets on it;
SSO/taints/NetworkPolicy do not remove that boundary. At that stage NetBird was
not yet deployed; the subsequent deployment and its limitations are described
in the [current reference](../../network/netbird/README.md).

### Wiki implementation: the historical November 1 acceptance

- Native Authlib code/PKCE/nonce/signature/aud/exp with a pinned issuer; no
  custom JWT validation.
- Narrow reproducible derivative in `deploy/wiki-runtime/oidc/`, a vendored
  chart + Secret hook. The actual REGISTRY manifest digest is
  `sha256:64d27d6f320ab7440be82578d1d73193278e6b12f77127776b715c2e98b17515`.
  Podman's local RepoDigests was different after the registry manifest
  conversion; the first rollout was automatically rolled back, then corrected,
  pre-pulled and accepted.
- At that old acceptance the Wiki was on socrat-3. **The Wiki is now on
  socrat-0**: runtime f52cf2a, digest
  `sha256:dc5b15b391cd94fad3db51dc7fa917e138d77ea345e27518371073538c5a78d9`,
  retained PVC. The old digest above is not production.
  [Upgrade](../../records/handoffs/wiki-upgrade-20261107.md).
  Discover the actual PVC affinity before any backup pod.
  A frozen full-volume copy was made with the writer stopped; the old app
  resumed during the encrypted off-node transfer; snapshot DB integrity/IDs/
  hash preservation checked. Temporary backup/image/smoke resources deleted.
  Do not repeat a slow network transfer with the production writer stopped.
  Full application DR is still not tested.
- A fresh Authentik backup after adding the Wiki client exists on the Mac. The
  local owner Wiki **saved initial password** returned 401; the CURRENT
  password was not changed/reset. The owner must test his current fallback.
  The policy/no-IdP fallback was tested with known fixture credentials; the
  real owner did not enroll any fake factor.
- The native Wiki observer MFA flow passed; write403; the existing configured
  MCP tool `wiki_list_pages` still works. Callback access logging disabled via
  a UVICORN env var.
- An additional **Open WebUI** observer OIDC flow passed with an active native
  Auth row. **Do not set Auth.active=False just to disable passwords**: get_auth
  in its native MFA subsystem also rejects OIDC (verified on a temporary
  fixture, cleaned up). No such change was applied to Tim. A native
  password-only restriction needs another mechanism; do not falsely mark
  other services as owner-only fallback.
- The generic source and 9 regressions are recorded in hugo-docs commit
  `c6ffb18`; no new tagged release. The homelab patch is
  self-contained/reproducible, and the source publication is organized
  separately from unrelated dirty work. Historical evidence records the
  pre-publication state, not the current Git status. After pushing main, check
  the Argo CD Application and the running image rather than assuming a commit
  alone proves GitOps acceptance. Fleet GitRepo checks are retired.

### The owner's clarification about the full scope

A migration of **all cluster services with human authorization** is needed,
including the **LiteLLM admin UI** (now native OIDC + PKCE; real acceptance by
the owner is still needed), not only the portal apps. The old server-side login
methods are for the owner only, as a fallback. A full live inventory and a
check of all direct/private auth paths are not finished. Machine API keys,
robots, webhooks and MCP are separate: they cannot be replaced by interactive
redirects. Do not consider the current work the completion of the whole
migration.


## LiteLLM and dashboard icons — 2026-11-01

- Fixed the real absence of LiteLLM: created a native Generic OIDC
  provider/application with the exact `/sso/callback`, PKCE, the usual
  mandatory MFA and owner-only admission. Login:
  `https://llm.alchemmist.xyz/sso/key/generate`.
- The reviewed Authentik UUID of the owner → the existing `socrat-admin` /
  `proxy_admin`; neither email nor name selects the administrative ID. The
  passwords/IDs/roles of the old records were not changed. The real owner MFA
  was not substituted by a test one.
- Browser smoke: a temporary observer got a separate UUID-based read-only ID,
  passed TOTP/consent/OIDC and the server-side role check. His single
  temporary admission binding, accounts and UI keys were deleted. Production
  admission is again owner-only.
- The existing Open WebUI virtual key still reads models; without a key 401,
  without browser redirects. The master/salt/DB Secrets, config and explicit
  OTel env matched the encrypted pre-change snapshot. vLLM was not restarted;
  LiteLLM was updated by the usual graceful rollout.
- `/fallback/login` is kept for the old owner DB password. The password itself
  was not reset/checked; a full owner login/recovery acceptance is still
  required. The free SSO of the installed version is limited to five users;
  there are no license bypasses.
- Argo CD got the official pinned SVG; the Wiki was switched from BookStack to
  the original round Socrat from `deploy/litellm/branding/socrat-icon-v1.png`,
  512px version. LiteLLM uses the same own favicon. All nine permitted media
  URLs were really verified HTTPS 200 + SHA-256; the Argo CD provider/policies
  settings were not changed.
- Encrypted backup `litellm-before-oidc-20261101.aesgcm`:
  decrypt/authentication and archive listing checked, a full restore NOT
  performed. Details and commands: `docs/applications/ai/litellm.md`.
