# Native observer profile (issue #105)

**Status: activated configuration; final synthetic round-trip blocked by internal SSH access (2026-11-07).**
See [the exact activation checkpoint](observer-activation-20261107.md).
Rancher observer RBAC is enabled. The guarded bootstrap applied safe new-user
defaults and the 60-minute human session setting. Legacy WebUI admission was split
into `homelab-chat-user` without changing the existing person's subject or data.
Danila is not onboarded until the four admitted services pass acceptance.
CI remains scoped; this does not claim branch protection or independent approval.

**Harbor is deliberately gated, not a supported observer service today.** Real
synthetic acceptance proved that its native Guest cannot push/delete, but a CLI
secret still obtains `pull` after the IdP observer membership is removed. The
profile/bootstrap therefore removes only the observer group's three project
Guest memberships and its Harbor admission. Owner, robots and unrelated project
grants remain unchanged. Do not reopen it based on a configuration receipt.

## Ordinary onboarding after the one-time bootstrap

An authorized administrator adds a person to Authentik `homelab-observer`. The
person uses the application's native SSO. Native services create the local account
and resolve the group role themselves. No `account-mappings.json` entry, per-human
Rancher user/binding, SQL edit or agent invocation is needed. A small native
membership-cache reconciler handles Rancher revocation; it never creates users or
assigns personal roles. Wiki checks current reader admission in native auth. An already-open session may need a fresh login to obtain new claims.

NetBird network admission is separate. Do not add `authentik Admins` or
`authentik Read-only` to obtain application permissions. A group is an **additive
grant, not a deny**: unrelated owner/editor/direct/native roles still contribute.
Existing owner/antropophag identities and grants are intentionally not downgraded.
An existing privileged account is not made read-only by adding this group.

| Service | Native mapping | Scope / important restriction |
| --- | --- | --- |
| Rancher / Kubernetes | OIDC `genericoidc_group://homelab-observer` → custom RoleTemplate / native group binding | `local` cluster and future namespaces; explicit reads, no Secrets, ConfigMaps, pod logs, exec/attach/port-forward, proxy, writes, project/cluster creation, grants; extension credential APIs denied. Legacy self-credential API remains possible, always constrained by current native viewer authorization |
| Grafana | Existing OIDC group mapping → Viewer | Role sync must remain enabled; do not reuse Editor or administrator roles |
| Wiki | Existing signed OIDC groups → reader | Legacy subject-specific editor/owner overrides remain separate and must not be mistaken for a strict observer |
| Argo CD | Existing `homelab-observer → role:readonly` and OIDC groups | Add native application admission; no sync/actions/delete/exec; verify live Secret redaction and all negative actions before rollout |
| Harbor | **Gated: native CLI revocation failed** | No observer admission or project Guest grant. Reserved future scope is only `homelab`, `library`, `spi-triage`; admin-only project creation remains enforced |

If Harbor is later reopened after a separate revocation acceptance, additional
projects need their group membership declared in code as part of project creation. There is no invented global Harbor Viewer that silently
covers all future projects. This is per-project configuration, not per-user work.

Other services are excluded explicitly in `deploy/identity/observer/profile.json`:
n8n, Kuma admin, Syncthing GUI, 3x-ui and ordinary WebUI users are not advertised
as safe infrastructure viewers. LiteLLM and the private RustFS console require
separate native-role review. A synchronizer cannot make an administrative native
account read-only. Public search, evidence previews and status pages stay public.

## Native configuration as code

* `deploy/identity/observer/profile.json`: reviewed admission / session / project scope.
* `deploy/platform/rancher/public-entry/files/observer-rbac.json`: actual native
  CRD bodies, rendered by the existing Rancher public-entry Argo application.
  No inherited `Cluster Member`, `User`, wildcard or aggregated Kubernetes `view`.
* `scripts/observer-access-plan.py`: pure fail-closed plan against a private snapshot.
* `scripts/observer-access-bootstrap.py`: bounded **one-time configuration** tool,
  not an identity lifecycle controller. Default API access is GET only. Apply
  requires the exact fresh plan hash, a second snapshot, Kubernetes UID/RV tests,
  private before/after/progress receipts and an uncertain-write stop marker.
* Existing identity integrations retain already-open group admission when safe
  defaults exist, but cannot open it instead of the reviewed bootstrap; Harbor's authoritative native configuration retains admin-only project
  creation. Foundation does not newly admit Harbor observers without the private
  bootstrap readiness receipt. No client secret or redirect URI is changed.

### Dangerous defaults addressed

The live audit found Rancher's new-user `User` default enabled: it can create
clusters, infrastructure and Fleet resources. `User Base` also permits token and
kubeconfig minting. Neither is a viewer baseline. The bootstrap disables those
**new-user default flags only**, after the custom minimal login default exists;
it does not delete roles or remove existing people's bindings.

The minimal global login role keeps normal self-service preferences, own-user
bootstrap and activity endpoints needed by the native UI. Those are not grants
to mutate Kubernetes workloads/RBAC or administer Authentik. The cluster role is
read-only. Viewing ordinary workloads can still reveal plaintext accidentally
embedded in their specs/events: a viewer role is not a secret-scrubbing DLP system.

Rancher browser session TTL is proposed as 60 minutes (live default was 960).
This affects future human sessions, **not** `auth-token-max-ttl-minutes` (machine
credentials preserved), and does not retroactively revoke existing tokens.

### Native revocation and its explicit limits

OIDC claims are snapshots. Rancher's legacy generic OIDC cache is not reliably
refreshed natively, and its legacy `/v3/tokens` API can mint a self-owned key even
when `ext.cattle.io` token/kubeconfig creation is denied. Synthetic acceptance
created and deleted a short-lived test key; it did not grant infrastructure writes.

* `observer-membership` CronJob refreshes **only** the `homelab-observer` entry in
  existing native Rancher UserAttributes every minute. A complete fresh IdP
  snapshot is required before writes. UID/RV/subject/group-list JSON Patch tests
  stop races. Owner and existing explicitly admitted subjects are excluded; all
  other cached groups remain untouched. There is no user or role provisioning.
  Removing the cache entry was verified to make an existing browser session lose
  nodes/namespaces/workload access immediately. Legacy bearer keys are expected to use the same current authorization; their
  independent live removal/re-add acceptance remains pending. Do not claim this
  from a successful browser/cache check alone.
* Wiki's pinned native OIDC implementation is preserved byte-for-byte by an init
  container. The native hook checks current IdP admission for linked **reader**
  cookie and MCP-token authentication, caching a complete snapshot for at most
  60 seconds. Read failures deny reader authentication, never extend stale
  access. Owner/editor/unlinked machine identities are not changed. No wiki
  account, password, session table, token or article is written by this hook.
* Grafana keeps its native eight-hour maximum login lifetime and role refresh.
  Argo CD's default is an unprivileged `role:unassigned`, not a fallback Viewer;
  reviewed groups remain explicit. Existing `mcp` machine read access is explicit
  as well, preserving its prior default-reader behavior and separate sync grant.
* Harbor stays gated because native CLI cached authorization survived removal.
  Already issued registry JWTs are independently valid for up to 30 minutes;
  removing project membership is not a retroactive JWT-signature revocation.
* Public Wiki articles, search/evidence and public status remain public. Observer
  removal is not a promise to make public material private.

The membership reader is a dedicated **machine** service account with just
`authentik_core.view_user` and `authentik_core.view_group`, not an IdP admin token.
Its private token is installed once as `observer-membership-reader` in
`cattle-system` and `wiki`. The Rancher worker can read users/attributes and patch
UserAttributes, but cannot mutate users/RBAC/workloads, read Secrets or exec.
It stops without mutation on incomplete/failed IdP reads. An unavailable worker
can delay Rancher revocation: monitor failed/missed CronJobs; one minute is a
healthy-operation polling interval, not an unconditional SLA.

One-time machine setup is source-controlled in
`scripts/observer-membership-service-bootstrap.py`. Default is a credential-free
policy/hash preview. `--apply --approve-policy-sha256 HASH --state PRIVATE_DIR`
requires operator-owned 0700 state with private `credentials.json`; existing
role/group/service/Secret names stop rather than being adopted. Inspect private
progress after any partial failure; never blindly rerun. No future human setup
runs this tool and no secret is stored in Git.

## Review and deployment order

1. Review issue #105 / linked PR, local tests and configured scoped CI. Review the
   global new-user-default and human-session impact with alchemmist. Do not merge
   or change live permissions merely because offline tests passed.
2. In the reviewed activation change set `observerAccess.enabled: true` in the
   Rancher chart; render and server-dry-run, sync **only** the new RBAC resources.
   No broad Argo sync/prune, workloads, restarts, secrets or IdP membership changes.
   Check CRD schema and controller-generated roles before admission is opened.
3. On socrat-0, keep the complete matching checkout and use an existing protected
   0700 operator directory / 0600 credential JSON (`authentikToken`, built-in
   Harbor bootstrap `harborUsername`, `harborPassword`, or explicit existing
   `harborJobserviceSecret` machine identity). Never put values in shell
   arguments, Git, PRs or public logs; do not enroll/impersonate human accounts.
4. First review/audit the one-time legacy chat split:
   ```sh
   python3 scripts/observer-chat-migration.py --credentials /PRIVATE/bootstrap.json
   # Only after reviewing its exact fresh plan hash:
   python3 scripts/observer-chat-migration.py --credentials /PRIVATE/bootstrap.json \
     --apply --approve-plan-hash REVIEWED_CHAT_MIGRATION_HASH
   ```
   This preserves the existing reviewed chat subject in an explicit app-use group;
   it is not future-user service provisioning. Do not run broad foundation
   reconciliation across the old observer chat binding before the migration:
   its unknown-binding guard correctly stops rather than silently adopting it.

   Audit the one-time native viewer configuration:
   ```sh
   python3 scripts/observer-access-bootstrap.py --credentials /PRIVATE/bootstrap.json
   ```
   Inspect its targets/hash. If the native Harbor config is locked by the existing
   configuration override, first deploy the reviewed authoritative Harbor native
   configuration (admin-only project creation); do not bypass its ownership.
5. After approval, apply that exact fresh hash:
   ```sh
   python3 scripts/observer-access-bootstrap.py --credentials /PRIVATE/bootstrap.json \
     --apply --approve-plan-hash REVIEWED_HASH \
     --authentik-directory /home/alchemmist/.cache/homelab-authentik
   ```
   Kubernetes default-role/session changes precede Harbor project guards and Guest
   groups, Rancher group admission, then additive app admission. Existing principals
   and bindings are preserved. Any uncertain operation stops; inspect private
   receipts and read live state before a reviewed recovery. No blind retries.
6. Complete the synthetic positive/negative and removal tests above, including
   fresh future users without static mappings and existing user privilege unions.
   Offline tests evaluate the declared rules; they do not prove Rancher controller
   propagation, browser usability or native token revocation.
7. Only then change Danila's IdP membership: add observer, remove the erroneous
   Authentik Read-only membership, preserve approved NetBird membership. Verify
   UUID against the earlier private audit. Do not set a password or enroll MFA.

### Rollback / failure recovery

Stop new admission first: remove only the reviewed observer app binding(s) and
Rancher group principal using fresh UID/RV/target guards. Preserve owner and other
allowed principals. Existing sessions still need explicit service-specific
revocation; admission removal is not logout. Keep the safer admin-only Harbor
creation/default/login settings unless rollback of those global settings is
separately approved; blindly restoring broad defaults is an escalation.

Disable only this chart's observer resources after admission/session handling and
resource ownership review. Do not prune the Rancher application, modify immutable
native principals, delete users/projects/images or replace machine credentials.
Private bootstrap receipts contain configuration and identity metadata and stay
0600 under the 0700 state directory.

## Checks

```sh
python3 -m unittest discover -s tests -p 'test_observer_access.py' -v
helm template rancher-public-entry deploy/platform/rancher/public-entry \
  --set observerAccess.enabled=true
```

The scoped GitHub workflow also runs current identity/admission/browser-auth
regressions without infrastructure credentials. The older preparation suite has
a separately reproduced baseline failure: its allowlist still requests retired
`n8n` from the native-only catalog. Do not hide that as a passing repository-wide
suite or reintroduce n8n's retired auth gateway to fix its fixture.

### Concurrency boundary

The ordinary Rancher integration retains admission only if it was already open;
it re-reads default roles/session settings immediately before the authconfig write
and uses JSON Patch UID/resourceVersion tests against the original authconfig.
A concurrent authconfig edit therefore fails closed rather than losing another
writer's principal changes. This is **not a transaction across roles, settings,
secrets and authconfig**. Keep a single operator/configuration writer during
bootstrap/reconciliation; do not concurrently edit default roles or TTL. A failure
can follow earlier legacy reconciliation/Secret writes: inspect private backups
and current objects, never assume that the entire integration was rolled back.


Harbor's native solution identity uses `Authorization: Harbor-Secret` and
`GET /api/v2.0/internalconfig`. Do not send it to the regular human configuration
GET, whose deployed solution-user response path returns HTTP 500. The internal
response includes sensitive configuration and stays in memory/private receipts.
Both modes keep the existing credentials unchanged; there is no password reset,
SQL membership write, human impersonation or newly provisioned privileged robot.
