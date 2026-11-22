# Application access: current B2C contract

**External password:** [password change page](../authentik/operations/password-self-service.md) —
https://auth.socrat.alchemmist.xyz/change-password; `/if/user/` is closed for External.

This is the current entry point for granting access to individuals. Historical
owner-only/observer bootstrap descriptions do not replace this contract.
Technical runbook and private receipt references: [app access groups](app-access-groups.md).

## What the owner does in the UI

1. Creates/selects the person's active Authentik account. Type **External** is
   allowed: Internal/External is not an application permission.
2. Assigns only the required app groups from the table.
3. Hands the person the ordinary login address through a safe channel. The user
   performs the first login/MFA on their own; the assistant does not reset
   password/MFA and does not log in on their behalf.

| Group | Application and role |
|---|---|
| `app-litellm-user` | LiteLLM `internal_user`, own keys/cabinet, not proxy admin |
| `app-open-webui-user` | Open WebUI, regular user |
| `app-grafana-viewer` | Grafana Viewer |
| `app-grafana-editor` | Grafana Editor, not GrafanaAdmin |
| `app-wiki-reader` | Wiki reader |
| `app-wiki-editor` | Wiki editor |
| `app-lms-student` | LMS student |
| `app-lms-teacher` | LMS teacher; with both LMS groups, teacher takes precedence |

One app group grants access only to its own application. Existing extra rights
are additive: adding viewer does not demote an already existing administrator.
An LMS role does not mean access to all lessons: lesson grants remain separate.
Usually the native account appears on the first successful SSO login (JIT), not
immediately when the person is created/added to a group. There is no global
copying of all people into all applications. Public pages do not become
private because of this scheme.

Do not give a B2C user `homelab-owner`, `homelab-platform-operator`,
Authentik Admins/Read-only or automation/admin groups. `homelab-observer` is
an old broad staff profile across several services, not a replacement for a
dedicated app group. `homelab-chat-user` remains legacy chat access; the new
choice is `app-open-webui-user`. Having VPN/NetBird, SSH, sudo or kubectl is a
separate permission.

## What the code/Ansible does

- Source of roles: `deploy/identity/services.json` (`appRoles`, `accessManagement`).
- The shared `identity_app_access` hook is invoked during the routine Authentik
  application registration and native integration setup; it creates
  `app-<slug>-<role>` groups and verified admission bindings. Groups/PKs must
  not be created manually in addition.
- The reconciler also discovers already-registered Authentik applications.
  Unknown ones get an empty reserved user group **with no access**.
- For a new application, the assistant describes its SSO, native roles and a
  verified adapter; then the shared mechanism creates the groups. A new
  Pod/Ingress by itself does not tell the application the right roles and does
  not wire up SSO automatically.
- Manual registration outside Ansible will be discovered at the next
  reconcile. There is no permanent watcher/background writes; an ordinary Git
  push does not trigger this IdP writer by itself.
- B2C membership of people is managed in the Authentik UI, not mandatory
  per-human rows in Git. The shared people reconciler is not involved. The old
  `prepare_app_iam.py` is a historical limited migration tool, not the current
  onboarding command.

Plan defaults to GET-only for the API; apply requires a fresh hash, lock,
private preimages, CAS/drift guards. It does not manage passwords/MFA, does not
delete groups, does not rotate client secrets. An unexpected privileged group/
complex policy/foreign ownership — stop, not an automatic fix. The separate
playbook and commands are in the runbook above.

## Native compatibility and identity

The wiki role map accepts the new reader/editor groups. In app-local OIDC
claims, Open WebUI receives the needed legacy user-role alias, LMS —
student/teacher aliases. This does **not** add global observer membership and
does not open neighboring services. Default scope mappings were not changed;
they must be selected by exact upstream name, not all mappings with
`scope_name=profile`, otherwise aliases could leak between apps.

LiteLLM: immutable UUID → `authentik:<UUID>`; app member → `internal_user`.
Only the verified owner UUID gets `socrat-admin` / `proxy_admin`. A matching
email/username does not turn someone into the owner. Vladislav is now only in
`app-litellm-user`; his former account is preserved, the direct user binding and
UUID role exception removed, `litellm-users.json` is empty. In the verified
snapshot there are just 3 LiteLLM users; the current version's conservative
gate is **5 total users**. Groups do not bypass the license and do not provide
unlimited B2C provisioning.

## What not to present as ready B2C access yet

The reserved `app-n8n-user`, `app-harbor-user`, `app-rancher-user`,
`app-argocd-viewer` and the discovered NetBird/SPI/RustFS groups were not
granted new access. Their presence in the list does not mean a working native
account/role.

- n8n: no accepted native OIDC/JIT scheme; the IdP gate does not create an
  n8n account.
- Harbor: needs project grants and a separate check of CLI/session revocation (#134).
- Rancher/Argo CD: staff infrastructure and separate native RBAC/cache adapters,
  not automatic B2C cluster privileges.
- NetBird/SPI/RustFS: separate owners/controllers, policies preserved.

## Revocation and verification boundaries

Removing an app group blocks new SSO access, **but does not prove an instant
logout of all sessions/keys**. For offboarding, separately revoke native
sessions/API keys per each application's rules. The wiki checks current
membership with a limited cache; an LMS session may keep the role until a new
login/expiry; LiteLLM API keys are independent of the ability to log in again
via Authentik. Do not delete a user with data instead of a proper revocation.
The previously accepted observer revoke is not acceptance of the new app
groups in all applications.

Accepted snapshot: 8 native mapping/admission-graph cases with the disabled
passwordless fixture (removed), real owner/Vladislav mapping results, native
LMS role selection, empty live reconcile plan, LiteLLM read-only preflight,
isolated Ansible plan `changed=0`. 125 selected offline tests: 124 passed/1
skipped. Previous groups/memberships, LiteLLM identities/roles and master/OIDC
Secret data preserved; applications Ready. This is not a full browser/MFA/JIT
E2E and not a universal session/key revocation acceptance. Git publication adds
no runtime evidence; live rights had already been applied before the current
documentation/source closeout.
