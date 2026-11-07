# Native observer profile (issue #105)

**Status: inactive implementation prepared for merge/review, not rolled out.** No Danila group,
password, MFA, native account or application role has been changed. The Rancher
chart switch remains **off** until review and the deployment acceptance below.
CI is scoped to this policy; this file does not claim repository branch protection
or mandatory review/check enforcement has already been configured.

## Separate activation gates (not blockers to merging the inactive code)

* Current legacy `homelab-observer` admission also opens ordinary Open WebUI use.
  That is **not** a viewer role. Before adding a strict observer, migrate existing
  chat users to a separate explicit `homelab-chat-user` group without losing their
  access or data, then remove only the old observer admission.
  `scripts/observer-chat-migration.py` stages this one-time migration for the
  existing reviewed subject: plan/hash, fresh UUID checks, preserved owner binding,
  additive existing-user group grant, readback, then exact old-binding removal.
  Unexpected observer members stop it for review; no future observer is added to
  the chat group. The bootstrap rejects any
  observer binding outside its five reviewed native services; it does not silently
  preserve a write-capable legacy app and call the profile read-only.
* Native group/session/CLI-secret revocation and browser allow/deny acceptance are
  still unproven. The bootstrap receipt is configuration readback, not acceptance.

## Ordinary onboarding after the one-time bootstrap

An authorized administrator adds a person to Authentik `homelab-observer`. The
person uses the application's native SSO. Native services create the local account
and resolve the group role themselves. No `account-mappings.json` entry, per-human
Rancher user/binding, SQL edit, agent invocation, minute polling job or n8n workflow
is needed. An already-open session may need a fresh login to obtain new claims.

NetBird network admission is separate. Do not add `authentik Admins` or
`authentik Read-only` to obtain application permissions. A group is an **additive
grant, not a deny**: unrelated owner/editor/direct/native roles still contribute.
Existing owner/antropophag identities and grants are intentionally not downgraded.
An existing privileged account is not made read-only by adding this group.

| Service | Native mapping | Scope / important restriction |
| --- | --- | --- |
| Rancher / Kubernetes | OIDC `genericoidc_group://homelab-observer` → custom RoleTemplate / native group binding | `local` cluster and future namespaces; explicit reads, no Secrets, ConfigMaps, pod logs, exec/attach/port-forward, proxy, writes, project/cluster creation, grants, personal API token or kubeconfig minting |
| Grafana | Existing OIDC group mapping → Viewer | Role sync must remain enabled; do not reuse Editor or administrator roles |
| Wiki | Existing signed OIDC groups → reader | Legacy subject-specific editor/owner overrides remain separate and must not be mistaken for a strict observer |
| Argo CD | Existing `homelab-observer → role:readonly` and OIDC groups | Add native application admission; no sync/actions/delete/exec; verify live Secret redaction and all negative actions before rollout |
| Harbor | Native OIDC group type 3 → project Guest role 3 | Explicit projects `homelab`, `library`, `spi-triage`; **admin-only project creation** is a prerequisite; no owner admin-group change, robot changes or image push |

Harbor projects added later need their group membership declared in code as part
of project creation. There is no invented global Harbor Viewer that silently
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

### Revocation is an acceptance gate, not a fabricated one-minute guarantee

OIDC claims are snapshots. Grafana, Wiki, Argo CD, Rancher and Harbor have different
session, refresh-token, native membership and CLI-secret caches. Rancher's legacy
generic OIDC provider must not be assumed to refresh groups on a polling timer.
The 60-minute setting alone is **not proof** of bounded revocation: active renewal,
old tokens, Harbor CLI credentials and native group caches must be tested.

Before production onboarding, use a dedicated synthetic identity (never somebody
else's password/MFA) to test group add → first native login → allow/deny matrix →
group removal → existing cookie/API/refresh/CLI-token behavior → new-login denial.
Record the actual stale-access window for each service. If native expiry/refresh
cannot meet the agreed removal behavior, keep that service gated and propose a
small scoped revocation reconciler separately (n8n is possible). Do not ship an
unproven forever-cached membership under a claim of automatic revocation.

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
   Harbor bootstrap `harborUsername`, `harborPassword`). Never put values in shell
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
