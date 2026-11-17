# Per-application access groups: current implementation

## Owner workflow

Create an active personal user in Authentik (external is supported), set up their
normal initial credential securely, then assign only the required application
roles. The person completes their own login/MFA. Do not add owner, observer or
Authentik administration roles merely to make an application visible.

| Group | Application / effective role |
|---|---|
| `app-litellm-user` | LiteLLM `internal_user`, personal dashboard/keys, not proxy admin |
| `app-open-webui-user` | Open WebUI ordinary user |
| `app-grafana-viewer` | Grafana Viewer |
| `app-grafana-editor` | Grafana Editor, not GrafanaAdmin |
| `app-wiki-reader` | Wiki reader |
| `app-wiki-editor` | Wiki editor |
| `app-lms-student` | LMS student |
| `app-lms-teacher` | LMS teacher; teacher wins when both LMS roles are present |

One app group grants admission only to its own application. Existing legacy
memberships/explicit privileges are additive, not automatically removed or
downgraded. Public pages are independent of private application admission.
Users without another app's admission cannot use its SSO to create an account.
Native accounts normally appear at first successful login (JIT), not at Authentik
user creation or group assignment. This is not a background account copier.
LMS role does not itself grant every course/lesson: existing lesson permissions
remain a separate LMS concern.

Vladislav now has only `app-litellm-user`. His existing immutable-UUID LiteLLM
account was preserved; the former exact-user admission binding and per-UUID role
exception were removed. `litellm-users.json` is empty. No password, MFA, owner
membership or machine API key was changed/generated.

## Historical manual Grafana preparation entrypoint

`scripts/grafana-app-admission.py` is retired and refuses every invocation with
exit2before reading arguments, credentials, locks, HTTP state or application data.
It does not repair its historical malformed writer, import a reconciler, or forward
`plan`/`apply`. Its previous implementation remains in Git history. The current
catalog-driven owner and its independently reviewed plan/apply prerequisites are
listed below; retirement does not authorize running them. Offline AST/capability
and negative-mutation tests protect this refusal before any import execution.
No live identity state, groups, users, bindings or credentials changed here.

## Automatic creation and registration contract

Sources:

- `deploy/identity/services.json`: app roles, native role intent,
  `accessManagement.state`, optional app-local legacy claim aliases.
- `ansible/roles/authentik/files/reconcile_app_access.py`: bounded independent
  reconciler, no import/execution of the full foundation/bootstrap controller.
- `ansible/roles/identity_app_access/`: automatic post-registration/native-integration
  Ansible hook. Both the Authentik role and identity integration role invoke it.
- `ansible/playbooks/identity-app-access.yml`: isolated plan/apply entrypoint.

At normal application registration/deployment through these Ansible paths, the
hook reads registered Authentik applications and the catalog, creates missing
`app-<slug>-<role>` groups and configures reviewed app admission. The administrator
does not manually create groups, find PKs or edit policy bindings. An app registered
outside this deployment path is discovered on the next reconciler run; there is
no polling daemon or Git-push-triggered production writer.

An unknown registered app automatically gets an empty `app-<slug>-user` group,
**not** automatic admission/admin rights. To onboard a new supported app, the
implementer adds the registration and native role contract to the catalog and
its integration path; the group hook is already common. Example:

```json
{
  "appRoles": {
    "user": {"nativeRole": "user", "assignable": true}
  },
  "accessManagement": {
    "state": "ready",
    "reason": "Reviewed native OIDC user-role adapter"
  }
}
```

Do not label an app ready based only on OIDC connectivity. Its native role/JIT,
existing identity linking, revocation limitations, API authorization and applicable
license capacity must be reviewed. An arbitrary new Pod/Ingress cannot tell us
what that application's roles mean. Unsupported apps fail closed with a reserved
group; there is no guessed admin role or fake account provisioning.

## Reserved groups are not working B2C grants

The current reserved groups include `app-n8n-user`, `app-harbor-user`,
`app-rancher-user`, `app-argocd-viewer` and discovered NetBird/SPI/RustFS groups.
They were created empty without new admission. Existing native staff permissions
were not changed. Their contracts remain blocked:

- n8n: no reviewed native OIDC/JIT integration. An IdP gate is not an n8n account.
- Harbor: project grants plus CLI/session revocation need separate acceptance;
  observer issue #134 remains gated.
- Rancher / Argo CD: staff infrastructure, separate native RBAC/cache adapters;
  no B2C cluster privileges granted by this rollout.
- NetBird / SPI / RustFS: dedicated controllers and independent policies remain
  authoritative. Discovered empty groups do not take ownership of those systems.

## Native role adapters and isolation

LiteLLM keeps `authentik:<UUID>` as user and SSO ID. The exact reviewed owner UUID
alone selects `socrat-admin` / `proxy_admin`; `app-litellm-user` selects
`internal_user`. Email/name cannot merge into the owner. The current free-tier
conservative gate remains five total LiteLLM users; three were present after this
rollout. Group automation does not bypass licensing or provision unlimited B2C
accounts. No keys were generated for users by this change.

Wiki's existing native role-map Secret now also includes the two Wiki app groups.
The single Wiki deployment was restarted with its existing Recreate strategy and
verified ready; owner/editor/reader mappings and other Secret data were preserved.

The deployed LMS accepts legacy `lms-students`/`lms-teachers`. Open WebUI currently
accepts legacy owner/observer roles. Per-client profile/groups mappings project
new app memberships into those native legacy claims. In the WebUI token only,
`app-open-webui-user` (and existing `homelab-chat-user`) adds the legacy
`homelab-observer` user-role claim. This does **not** add the global observer group
in Authentik and does not admit the person to Rancher/Grafana/Wiki/Argo CD.
LMS projection similarly adds only its student/teacher legacy claims. Both profile
and groups scopes agree, so claim merge order cannot erase the projection.
No global/default mapping was modified; other OIDC clients keep their scopes.
Provider client secrets, redirects, flows, PKCE, consent and MFA remain unchanged.

Default scope selection is by exact upstream mapping names, not only scope name:
multiple app-local `profile` scopes must never be attached to another client.
Full foundation preserves existing app-local scopes. Dedicated Argo/n8n entries
are not adopted by that generic foundation controller.

## Safety, operator commands and verification

Run from `ansible/` for the standalone path:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/identity-app-access.yml -e ansible_host=socrat-0
ansible-playbook -i inventory/hosts.yml playbooks/identity-app-access.yml -e ansible_host=socrat-0 -e identity_app_access_apply=true
```

On the owner Mac, the runtime `ansible_host=socrat-0` selects the existing public
SSH alias and its strict known-host file; inventory/routes are not edited. The
bare historical inventory address did not select that alias's pin file and the
first attempted plan stopped at host-key verification before copying anything.
The pinned alias run then passed with `changed=0`; no host-key bypass was used.

The isolated playbook does not deploy/upgrade Authentik, reset humans or run its
full bootstrap. CLI defaults to GET-only plan; apply uses a fresh plan hash,
private preimages, ownership checks and current-object comparisons. It never
manages human memberships, deletes groups, resets credentials or rotates client
secrets. Unknown/complex/disabled/negated policy and foreign or privileged group
ownership stop the operation. Partial failures stop; inspect the private journal
and construct a fresh plan, never blindly retry uncertain writes.

The old `prepare_app_iam.py` is a historical hard-allowlisted empty migration tool,
not this dynamic system; it deliberately rejects the expanded current catalog.
The legacy explicit internal-human lifecycle file is not the B2C membership
source: normal B2C app memberships are assigned in Authentik UI, not per-human Git
rows. There is no scheduled lifecycle apply that will overwrite those UI grants.

Acceptance completed:

- 125 selected offline tests across access reconciler, LiteLLM identity, foundation,
  legacy lifecycle, historical migration preparation, NetBird and observer
  compatibility; 124 passed, one existing test skipped.
- Ansible syntax checks for isolated access and native integration playbooks;
  live isolated playbook plan passed end-to-end with `changed=0` via the pinned alias.
- Eight native Authentik mapping cases using one disabled, passwordless external
  fixture; each app group admitted only its own app in the current binding graph.
  Fixture deleted; no app account/session/API key created for it.
- Native mapping tests for real Vladislav (`internal_user`) and owner
  (`proxy_admin`), without logging in as either person.
- Running LMS role function: student, teacher, teacher precedence, empty-group deny.
- Final live reconciler plan empty; dedicated LiteLLM read-only preflight passed.

These are native mapping/configuration tests, **not full browser login/MFA/JIT or
end-to-end session/API-key revocation acceptance** for all apps. Human browser
acceptance remains to be confirmed. Do not test by resetting a real user's MFA.

Private operation roots on socrat-0, under `~/.cache/homelab-authentik/`:
`app-access-controller-gd9z1lrd`, `app-native-roles-x8577s_n`,
`app-access-iyt_btle`, `app-access-ui2b1qsy`, `app-access-ylgj0hir`,
`app-litellm-group-migration-fvtar5bt`, `app-access-native-test-kg352qfh`,
`app-access-source-final-jnusgeic`.
Initial API guard / reduced PATCH serializer / embedded `provider_obj` verification
stops were inspected with independent GETs, fixed and covered by regressions.
Fresh plans completed remaining operations without duplicate groups/bindings.
No broad restart, SQL writes, real credential changes, VPN/host/network mutation
or cluster-wide synchronization/pruning was performed. An unrelated cached full
foundation script had a different hash and was left untouched/not executed.

## Source publication checkpoint

Functional source: `e38b9053`, following original onboarding `3d8b7fe1`.
The owner subsequently authorized wiki refresh and publication of all completed
work. Shared/local histories were integrated by normal merge, preserving remote
n8n recovery authority and deployed Grafana status as well as local network/DNS
records. Initial divergence/merge-preview notes were a historical safe stop,
not a permanent deployment limitation. See the closeout commit and origin/main
for publication; no force push/reset or live migration is part of this closeout.
The live IAM configuration and cached controllers were already verified before
source integration. No new browser/session acceptance is implied by a Git push.

## Removing access

Removing an app group blocks new SSO admission; existing local/session and API-key
lifetimes are application-specific. Wiki checks current reader membership with a
bounded cache; LMS existing sessions retain their role until re-login/expiry.
LiteLLM API keys are independent machine credentials and need explicit revocation.
Do not promise instant universal logout or delete users with data as an offboarding
shortcut. A complete account/session/key offboarding workflow is separate work.
