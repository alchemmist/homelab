# Granular application IAM

> **The current mechanism is already enabled:** [App access groups](app-access-groups.md).
> Eight app roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS are working.
> The dynamic reconciler and the Ansible hook replace manual group creation;
> `prepare_app_iam.py` and the empty migration described below are a historical
> stage, not the current B2C onboarding command. Reserved staff/unsupported
> groups do not mean working access. The original boundaries of the old
> migration are preserved below.

## What changes — and what does not

This is an **additive migration with no new rights granted to people**.
`homelab-*` and `lms-students` remain active; the existing permissions of the
owner and Tim, their UUIDs, local emergency accounts and the exact subject
links are not replaced. The current `lifecycle.json` contains only these two
existing users, `state: preserve` and empty `appGroups`. It disables no
accounts and removes no old groups (the owner also keeps `lms-students`).

Sources of truth:

- `deploy/identity/services.json`: the former `groups` plus `appRoles`,
  `admission`, `groupsScope`. The new group name: `app-<service>-<role>`.
- `deploy/identity/account-mappings.json`: **reviewed old links**, not a
  catalog of future staff. Tim's UUID was confirmed by a GET audit; the old
  application IDs, the email for verification and the roles are unchanged.
  Email is **not** a join key.
- `deploy/identity/lifecycle.json`: exact username + UUID, desired **only
  app-** memberships and the state of the existing people. Deleting a row does
  not mean dismissal.
- `deploy/identity/access-policy.yaml`: the policy index and responsibility
  boundaries.

`prepare_app_iam.py` prepares only empty app groups without superuser, parents,
children, users and RBAC roles, with the marker
`attributes: {homelab_app_iam: 1}`. A foreign group of the same name is not
adopted. **The full `configure.py` is NOT a command of this migration.** It has
top-level side effects: it can change owner privileges, MFA stages, scopes,
providers, applications and the outpost. Do not run or import it for the sake
of creating app groups/bindings. For pinned Authentik **2026.8.5**, explicit
`is_superuser: false`, **`parents: []`** (M2M, not the obsolete singular
`parent`) and `roles: []` are checked. Missing/null/incomplete responses are
forbidden; **any** inheritance, including owner-superuser or an RBAC ancestor,
is blocked **before** assignment, not after the grant. The fake-API tests cover
the current fields; that is not a substitute for a GET audit and the real
MFA/consent browser acceptance by the owner/Tim. Until it happens, new live
assignments are forbidden. Existing app memberships are not rewritten by the
foundation controller. The owner does not get another administrative group: his
former `homelab-owner` remains the single source of the administrative mapping.

**Admission to an Authentik application ≠ a role inside the application.**
The application bindings have mode `any`: the former groups OR the new app
groups. An app group does not inherit a global role. An unknown/disabled/
inverted binding, a user/policy binding, a duplicate or another mode is an
error, not a reason to silently overwrite changes in the UI. The preparatory
tool adds only the missing permitted links and deletes nothing. There is no
full transaction/CAS between objects/APIs: a partial failure means STOP, a
manual GET inventory and a new review — not an automatic retry, rollback,
adoption of foreign objects, or restoration of old passwords.

## The matrix: admission apart from authority

| Application | New groups | What they actually grant | Limit |
|---|---|---|---|
| Grafana | `app-grafana-viewer`, `app-grafana-editor` | OIDC admission + Viewer / Editor | GrafanaAdmin still only `homelab-owner`; the Editor is not a server admin but can change dashboards — grant only after a review |
| Open WebUI | `app-open-webui-user` | OIDC admission + user | Admin only `homelab-owner`; email merge off; old user IDs/chats preserved |
| Wiki | `app-wiki-reader`, `app-wiki-editor` | OIDC admission + reader / editor | The exact subject overrides take precedence over groups: Tim **remains editor**, the owner admin; public reading and MCP are separate |
| Harbor | `app-harbor-user` | OIDC admission, not system administrator | Projects/repositories/robots are native Harbor RBAC, a separate agreement; the admin group does not change |
| n8n | `app-n8n-user` | Only the Authentik MFA-gate of the browser UI | **Not native SSO and not an n8n role**; the native account/role are needed separately; machine routes are unchanged |
| Rancher | `app-rancher-user` | Only app admission prepared | `assignable: false`: the restricted principal allowlist and native grants stay exactly for the reviewed UUIDs. New people need separate scoped bindings, without copying the owner |
| LMS | `app-lms-student` | Only app admission prepared | `assignable: false`: the deployed image accepts a single `LMS_OIDC_ALLOWED_GROUP=lms-students`; one cannot promise that the new group grants access |
| LiteLLM | No new groups | The former owner-only native OIDC + the exact UUID → `socrat-admin` | We do not widen the reviewed identity expression and do not grant proxy_admin |
| Uptime Kuma | No new groups | Only the former portal tile | The tile does not protect the native admin UI/socket; the SSO migration is not finished |
| Argo CD / x-ui | Not managed by this catalog/controller | The separately managed existing policy | See ownership below; no unauthorized widening of owner-only/reviewed access |

All the new OIDC group checks get an explicit `groups` scope with the claims
object `{"groups": [...]}`; this is not a change of `sub_mode`. Native MFA,
`default-provider-authorization-explicit-consent`, strict callback URIs, TLS
and PKCE are not weakened. The n8n/x-ui proxy keeps its implicit-consent flow:
that is not a substitution of the native consent of the other applications.

## Who will overwrite changes from the UI

| Controller / files | Authoritative area | Where manual changes are acceptable |
|---|---|---|
| `authentik/files/prepare_app_iam.py`, `services.json`, `account-mappings.json` | Only create-only empty allowlisted app groups; a separate stage — empty app bindings | No human assignment, repair, PATCH/DELETE or native rollout; any divergence requires review |
| `authentik/files/configure.py`, `services.json` | The full Foundation app/providers, groups, bindings, scopes, MFA validation; **not a command of the app-IAM migration** | Password, MFA devices, recovery codes, native consent belong to the person. Edit managed provider/MFA/settings in Git. Repeating a full run requires a separate review of the whole write surface |
| `authentik/files/lifecycle.py`, `lifecycle.json` | Only the explicit manual application of app memberships and active/disabled | UI membership diverging from the declaration, and the next **explicitly approved** apply will remove it; there is no background apply. Other groups/passwords/MFA are not managed |
| `identity_integrations/files/integrate.py` + identity overlays | Grafana OAuth env, Harbor `CONFIG_OVERWRITE_JSON`, WebUI OAuth env; the Wiki Secret with role/subject maps | Changing these parameters in the UI/Secret is temporary. Harbor project RBAC, native n8n roles are separate, not derived from an app group |
| Rancher branch `integrate.py` | The restricted principal list; managed mirror bindings for old local identities | A manual edit of an `identity-*` binding will be reconciled with the original. Changing the source grants directly is a separate privileged operation, not automatic onboarding |
| Wiki `deploy/wiki-runtime/oidc/oidc.py` + integration Secret | Group roles and the reviewed subject overrides | An ordinary UI role edit will be replaced at the next OIDC login. Extension changes require a **rebuild/deploy of the runtime**, not only the Secret |
| Grafana monitoring Helm / Harbor Helm | Load the identity overlay if the activation Secret is present | Do not run a full monitoring upgrade for the sake of OAuth: it touches resources unrelated to IAM |
| WebUI playbooks | A conditional identity reconcile after deploy/upgrade | `ENABLE_OAUTH_PERSISTENT_CONFIG=False`: the UI OAuth config is not the source of truth; do not overwrite the OTel env with a whole old snapshot |
| Argo CD `argocd_oidc/files/configure.py`; `deploy/argocd/values.yaml` and `deploy/platform/argo-cd/values.yaml` | A separate provider/bindings and native Argo RBAC | The legacy platform-operator already maps to admin; **we do not widen this**. The controller expects the bootstrap-token env in the pod and a single groups mapping: after its retirement/the appearance of a second mapping, a separate fixed migration is needed, not a bypass of the protection |
| Authentik Helm / Argo `deploy/argocd/apps/authentik.yaml` | K8s deployment, values from `deploy/platform/authentik/values.yaml`, selfHeal | This is not a declaration of the Authentik user DB. The full `authentik.yml` uses bootstrap values from another path; do not mix the upgrade with this app-policy migration |
| LiteLLM / x-ui controllers | Their own strictly reviewed owner policy/UUID | Do not widen via foundation/lifecycle; x-ui has a separate SSH-lane boundary; the files were not changed |

The 2026-11-02 GET audit confirmed the Helm release labels of Grafana, Harbor,
WebUI, Authentik, Argo and Wiki. `managedFields` in a normal kubectl response
were empty: that is **not** proof that no other writers exist. The ownership
information above comes from controller/Helm/Argo sources; all UI writers are
not inventoried.

## Preparation without granting rights: two separately reviewed stages

In this implementation **nothing was applied to production and nothing was
pushed**. Code/test readiness does not mean live approval. Below is the tool's
boundary, not permission to run apply. First an independent owner break-glass,
a protected backup and a verified recovery certificate; then a change window
and a pause of all UI/controller writers. Do not read/print the private cache
as a whole, API responses or Secret diffs. Verify the live API schema of pinned
Authentik **2026.8.5** before writing.

### Write boundary

`ansible/roles/authentik/files/prepare_app_iam.py` is a standalone CLI; it does
not import `configure.py`. Default is `plan`; `plan` and `check` call **only
GET**. `check` returns 1 if creates are needed, 0 if the chosen stage is
already done. Locally they create only the private lock, not the journal and
not API objects.

- **Stage A `groups-only` (default):** at most nine `POST core/groups/`, only
  the nine names from the matrix above and the exact appRoles list from
  `services.json`. The payload explicitly sets `is_superuser: false`,
  `parents: []`, `children: []`, `users: []`, `roles: []`, `attributes:
  {homelab_app_iam: 1}`. An existing group requires the same explicit fields;
  missing/null, inheritance, membership, RBAC, a foreign marker, an extra
  `app-*` group or a duplicate — STOP, not a “fix-up”.
- **Stage B `groups+empty-bindings`:** a separate plan/review **after Stage
  A**. All nine groups must already exist: the tool does not guess their future
  PKs. At most nine `POST policies/bindings/`, the exact application/group PK
  pairs from a fresh inventory. `enabled: true`, `negate: false`,
  `failure_result: false`, `order: 100`; no user, no policy. Only the seven
  existing applications with `policy_engine_mode: any` and existing provider
  links. Unknown, duplicate, missing-field, disabled, negated, user/policy
  bindings on these targets — STOP. All legacy bindings must already be
  present; they are neither changed nor created. Other applications/bindings
  remain a protected baseline, outside management.

In both stages the owner/Tim must be active internal identities with a
**pinned UUID** from the reviewed mapping and unchanged legacy memberships. Any
app membership blocks this preparatory tool. No PATCH/DELETE, no creation of
users/apps/providers, no membership/MFA/outpost/roles/native writes. Empty
bindings grant no one access and do not prove that the native role mapping
works. Stage A alone does not complete the admission foundation: a lifecycle
check may legitimately refuse until Stage B. Rancher/LMS stay nonassignable.

### Plan, evidence and the separately approved apply

1. From the reviewed commit, copy to socrat-0 into the existing **owned 0700**
   cache `~/.cache/homelab-authentik/` only `prepare_app_iam.py`,
   `services.json`, `account-mappings.json` (0600). Do not replace
   credentials, login files, clients, journals or signing keys. Use the former
   verified SSH host key/alias. `credentials.json` must be an owned regular
   0600 file, not a symlink; the preferred key `AUTHENTIK_API_TOKEN`, the
   compatibility alias `AUTHENTIK_BOOTSTRAP_TOKEN`. If both are present, the
   values must be equal. The token is not passed in argv. Only a fixed HTTPS
   origin, system TLS verification; redirects are forbidden, there is no
   `--insecure`. Do not widen permissions to bypass a STOP.
2. The first GET-only plan can be viewed without evidence:

   ```sh
   CACHE="$HOME/.cache/homelab-authentik"
   umask 077
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups-only
   ```

   The inventory of **all pages** includes groups, users/memberships,
   providers/all plus detailed OAuth2/proxy, applications, global bindings,
   MFA validation/TOTP and stages/all, flows/instances/bindings,
   propertymappings/all and outpost instances. Only allowlisted requests, the
   tool SHA and hashes go to stdout; raw responses and provider credentials
   are neither printed nor written to the journal. MFA devices, factors,
   recovery codes and native databases are not read/validated by this tool.
3. In a separate private 0600 JSON `preparation-evidence.json` the operator
   records **real** evidence, not placeholders:

   ```json
   {
     "version": 1,
     "reviewed_commit": "<40 lowercase hex: reviewed source commit>",
     "reviewed_tool_sha256": "<64 lowercase hex: tool_sha256 from plan>",
     "backup_sha256": "<64 lowercase hex: protected current backup evidence>",
     "restore_test_sha256": "<64 lowercase hex: reviewed recovery test evidence>",
     "recovery_owner": "<responsible operator and protected evidence location>",
     "change_window": "<approved window/change reference>",
     "writers_paused": true
   }
   ```

   This is an **operator attestation**: the helper checks the structure,
   hashes and the match of its own source, but does not open the backup, does
   not perform a restore, does not confirm break-glass reachability and does
   not check the review commit in Git on the remote host. Verifying the
   backup's currency, restoration and the review commit/input diff is a
   mandatory external gate, not a property of the JSON's existence. Do not
   write secrets/response bodies into the evidence. With the evidence, get a
   **new** plan:

   ```sh
   EVIDENCE="$CACHE/preparation-evidence.json"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups-only \
     --evidence "$EVIDENCE" > "$CACHE/preparation-plan.json"
   ```

   The digest includes the tool hash, the full catalog/mapping, the stage, the
   evidence, the hashes of the **fresh full baseline**, the exact
   method/path/payload operations. The review must cover all these inputs and
   the exact list of requests; store the approval digest separately. Do not
   derive approval automatically from the current plan in the apply shell.
4. Only after separate approval for this digest:

   ```sh
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" apply --stage groups-only \
     --evidence "$EVIDENCE" --approve-sha256 "$REVIEWED_PLAN_SHA256"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" check --stage groups-only
   ```

   Apply without evidence or with a different baseline/approval refuses
   before the POST. Before the first POST one more full fresh snapshot is
   taken; after **each** POST — a full GET and a check that only the returned
   created object changed. Then the final GET/check. Any foreign change stops
   further POSTs. Already existing objects are compared without
   “normalization”/repair. A change even in protected config or a person's
   activity requires a new plan/review.
5. If admission bindings are needed, the separately reviewed Stage B:

   ```sh
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups+empty-bindings \
     --evidence "$EVIDENCE" > "$CACHE/preparation-bindings-plan.json"
   # STOP for independent review of the new baseline, PK pairs and digest.
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" apply --stage groups+empty-bindings \
     --evidence "$EVIDENCE" --approve-sha256 "$REVIEWED_BINDINGS_PLAN_SHA256"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" check --stage groups+empty-bindings
   ```

   After Stage B the current preserve/empty manifest must yield zero lifecycle
   operations: `lifecycle.py plan`, then `check`. **No lifecycle apply is
   needed.**

### Lock, journal and partial failure

All CLI actions take an exclusive nonblocking local lock
`.app-iam-prepare.lock`; it is not removed on release. That protects only
cooperating invocations on **this cache**, not the UI, other hosts/caches or
full controllers. There is no distributed lock and no conditional API
transaction/CAS; competing writers must be stopped for the whole window. The
GET snapshot is not a server transaction either.

Apply creates a private 0700 `app-iam-prepare-journal/<run-id>/`: an atomic
0600 `run.json` and a separate JSON per request, fsync of the durable intent
**before the POST**, then the PK/status and the hashes of the GET check.
Neither response bodies nor credentials are stored. A crash, timeout, schema
mismatch, drift or an error on the N-th POST: **fail-stop**, without
rollback/retry and without further creates. Pending may mean the POST already
arrived. An unfinished journal blocks all subsequent applies, even if the new
plan is empty.

Keep the journal, do a manual read-only inventory and match the created
PKs/payload/results with the approved plan; do not adopt foreign resources of
the same name. Only after a separate incident review may one manually archive
the investigated run **outside the active journal directory**, document the
partial result, get a new plan/approval and continue. There is no automatic
resume or journal clearing. Do not delete the lock/journal “for repair”, do
not replay `configure.py`, and do not restore the whole IdP for the sake of
empty groups. Deletion/cleanup is a separate reviewed administrative change,
not a function of this helper.

## Native integrations: a separate gated rollout

The preparation above **does not run the integrations playbook** and is not
permission for it. Native OAuth env/Secret/role maps, the Wiki runtime rebuild
and browser login change a different write surface and need their own reviewed
plan, backup/recovery, change window and per-service acceptance. Do not run
the full integrations playbook, a monitoring/Helm upgrade or a prune “for the
sake of empty groups”; do not re-include Rancher/LiteLLM/Argo in this change.

Before granting new app memberships, separately confirm the owner/Tim login
with their own MFA/consent (without extracting factors), the former
UUIDs/native user IDs, Tim editor Wiki / viewer Grafana / user WebUI, owner
admin; machine keys/webhooks and the independent owner fallback. The Wiki
extension needs a separate rebuild/deploy per
`deploy/wiki-runtime/oidc/README.md`. Existing smoke helpers may create
accounts/sessions — those are production writes, not read-only acceptance.
Only after successful native acceptance permit separate reviewed lifecycle
changes; the app-group migration is not needed for the existing people.

## Onboarding a real person

1. The owner approves specific applications/roles and native scopes. Do not
   give `homelab-owner`, platform-operator or kubeconfig for “convenient
   login”.
2. Create a **separate** person through the ordinary Authentik
   admin/enrollment flow. Self-registration/SMTP are not enabled here.
   Initially without superuser and without app/legacy grants; deliver the
   enrollment/temporary password over a protected independent channel,
   require a password change and his own MFA. Do not copy someone else's
   TOTP.
3. Obtain the exact UUID by a GET check; add only the real account to
   `lifecycle.json` (`state: preserve` or a deliberate `active`, specific
   appGroups). Native account linking needs a separate review of the existing
   ID, not an email match. Do not add a person to `account-mappings.json` just
   for provisioning: that is the legacy migration contract. If a pinned
   owner/Tim is missing, the foundation now stops instead of creating another
   identity with the old name.
4. On the owner node run `plan`, review all operations and the digest.
   Application:

   ```sh
   python3 "$CACHE/lifecycle.py" "$CACHE" apply --approve-sha256 "$REVIEWED_PLAN_SHA256"
   python3 "$CACHE/lifecycle.py" "$CACHE" check
   ```

   The digest is bound to the input, the UUIDs, the current groups/active and
   the operations. A state change needs a new plan/review. The lock protects
   only this tool; the UI and other controllers are not blocked. There is no
   distributed transaction/CAS: stop competing writers. A partial apply —
   plan again, not a rollback of the whole IdP.
5. Verify the positive login and the **denial** for other applications/
   operations. Harbor project RBAC, the n8n native account and machine
   credentials are arranged separately. For Rancher/LMS with `assignable:
   false` the tool will refuse to assign.

## Offboarding and the revocation horizon

- Record an explicit `state: disabled`, `appGroups: []` and apply the checked
  plan. First disable in the IdP, then remove the managed app memberships. The
  owner is protected from disable/app-membership changes by this tool. Legacy
  groups are preserved: **this is not a full removal of rights** and not a
  reason to automatically re-enable the account.
- Removing a user from the manifest is **not** deactivation. A repeated
  foundation run does not enable initialized disabled accounts and does not
  change their password/MFA.
- Separately revoke IdP sessions, OAuth grants/access/refresh tokens by the
  ordinary Authentik means; record the verification of the login denial. The
  tool does not guess the API endpoint for mass session revocation and does
  not promise a successful browser logout.
- Revoke native sessions and local login methods **in each** application:
  Grafana, WebUI, Harbor, Wiki, Rancher, n8n, LMS and others. Group/role are
  usually recomputed on a new login/refresh, not on every request. For the
  Wiki, Tim's editor subject override remains a reviewed exception; revoking
  an app group does not delete the native session, and the legacy observer
  still admits a new login while the account is active. A native
  session/token should be revoked separately, not by silently changing this
  override.
- The native OIDC provider TTL is now 5 minutes access / 8 hours refresh —
  **not** the upper bound of a native session. Grafana/Argo have an 8-hour
  policy; other cookies, proxy sessions and already-issued JWTs may live by
  their own rules. The n8n proxy had 1 hour access / 30 days refresh in the
  read-only audit; it was not shortened without a review.
- Revoke personal API keys/PATs, personally owned Harbor robots, WebUI keys,
  LiteLLM keys, wiki API tokens/MCP, Rancher tokens/kubeconfigs and sharing
  links; do not break organizational machine accounts without transferring
  ownership.
- Host/SSH/VPN and active shell/tunnel sessions are a separate agreed
  runbook. This commit changes no NetBird/SSH/WireGuard lane. Removing a
  group in the IdP is not enough to close those channels or an
  already-copied certificate.
- Record the per-service result, time and the residual windows; do not claim
  “all sessions revoked” from one successful lifecycle check. Restoring an
  old backup can resurrect an account/grants: repeat the current offboarding
  before opening entry.

## Rollback

Before granting app memberships, the rollback is to return only the new
public OAuth settings/role maps to the reviewed previous version and,
separately, to remove only the new app bindings if that is really needed. Do
not remove legacy bindings, exact subject links, passwords, MFA or user
databases. Do not restore a whole old Deployment over OTel/other parallel
changes and do not apply an old IdP backup for the sake of OAuth env. After
rights have really been granted/revoked, a rollback needs a new review: an
automatic reverse lifecycle apply can resurrect already-revoked access.

## Tests and remaining blockers

`tests/test_prepare_app_iam.py` verifies the current-schema fake API, both
limited stages, GET-only default/plan/check, pagination, pinned UUID, all the
explicit empty relations/marker, unexpected objects/bindings, protected
snapshot drift, the repeated pre-write check, the absence of any other
permission side effects, TLS/token alias, the exclusive lock and the private
atomic per-request journal. Partial failure, a POST accepted by the server
with a lost response, journal failure before a POST, post-Create foreign drift
and the ban on automatic retry/adoption are checked. These are isolated tests,
**not live schema verification, backup/restore or native acceptance**.

`tests/test_app_iam.py` verifies the absence of source grants, idempotent
add/remove, disable-before-remove, stale hash, UUID mismatch, owner
protection, refusal of service accounts/foreign groups/inheritance, pagination
and UI binding drift. `tests/test_identity.py` keeps the MFA/consent checks,
client credentials, legacy membership and the non-superuser Tim. The native
browser acceptance of the new app roles **was not done**: that is a
post-deploy task.

Unfinished: native session revocation automation, LMS multi-group admission,
new scoped Rancher principals, a separate safe modernization of the Argo
controller, the Kuma SSO/admin/socket boundary, a full live inventory of all
human entrances. The presence of a portal tile or an empty app group does not
close these blockers.
