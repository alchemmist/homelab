# Authentik: users, access and daily operations

**External password:** [password change page](password-self-service.md) —
https://auth.socrat.alchemmist.xyz/change-password; `/if/user/` is closed for
External.

> **Current B2C contract:** [separate app groups and native roles](../../applications/application-access.md).
> Eight enabled roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS;
> the remaining reserved groups do not imply admission. Internal/External is
> not an app permission. The old owner-only/preparatory snapshots below are
> history; browser E2E and instant revocation of all sessions/keys are not
> claimed.

## Current B2C access: separate application groups

Use the [current app-groups table and rules](../../applications/app-access-groups.md).
Active: `app-litellm-user`, `app-open-webui-user`, `app-grafana-viewer/editor`,
`app-wiki-reader/editor`, `app-lms-student/teacher`. The groups are created by a
common Ansible hook at the standard application registration; a person's access
is granted by membership in the Authentik UI, and the native account is usually
created at first login. External is supported. `homelab-observer` is the former
bundle of several staff services, not a default B2C group. `homelab-owner`,
Authentik Admins/Read-only and platform-operator are not given to clients.
Reserved unsupported groups do not grant login. The owner-only LiteLLM
description and the only-prepared app groups below are history; full
browser/JIT/revocation acceptance of all the new groups is not yet claimed.

> Current November 7 snapshot: [logins, first login and native roles](identity-current-state.md),
> [NetBird/network](../../../network/README.md), [monitoring owners](../../../observability/monitoring/observability-current.md).
> The dated rollout/smoke sections below are history of their stage, not
> general readiness.

Start: [identity.md](../../architecture/identity.md). Protocol/boundaries:
[identity-architecture.md](../../architecture/identity-architecture.md).
All operations with real rights require the owner's approval of the scope.

## 1. How a user logs in

**Precondition:** the password is already set through the agreed standard
process. For the fresh `antropophag` this has not happened yet; without a
password and a configured alternative login there is no way in. Create user
does not mean auto-enrollment, and the MFA requirement does not mean a forced
password setup/change. Invitations/email recovery are not configured here; a
separate custom activation flow was deleted. Do not hand out the old link.


1. Open **https://auth.socrat.alchemmist.xyz/** over trusted HTTPS.
2. Use your personal username, not the shared `akadmin`.
3. On first login enter the issued initial password, register **your own**
   TOTP in an authenticator app and confirm with the code. Do not pass the QR/seed
   to a helper.
4. If the administrator set the password, arrange his personal change and check
   that the next login works with his own factor. Do not consider the change
   automatically enforced.
5. Pick an available tile or the Authentik/SSO button inside the application
   itself.

The ordinary form now combines native identification/password. The password
eye is a stock password-stage feature; MFA after it remains mandatory.
If a live MFA session already exists in Authentik, the application may open
immediately. That is not an MFA bypass. For a clean test use a private window;
do not delete devices.

Direct LiteLLM SSO link: **https://llm.alchemmist.xyz/sso/key/generate**.
LiteLLM's local owner recovery: `/fallback/login`; do not confuse it with the
normal login. Wiki: `/login` is OIDC, `/login?local=1` is an exception for the
existing owner ID only.

If an application is missing from the library: check the user's activity, the
application group bindings and the actual provider. Adding a picture/tile does
not fix OIDC. Do not grant owner/superuser just to make a card appear.

### If an application still asks for its own password

3x-ui and the current n8n use an **external MFA gateway, not native account
SSO**. After Authentik the application's ordinary form without an Authentik
button may remain; the application's former password is entered there, not the
IdP password. An active parent MFA session can make the first stage
imperceptible. Do not promise one login instead of two.

In 3x-ui the cross-origin fetch on a missing/expired gateway cookie was fixed:
the XHR gets 401, and the native UI performs top-level reauthorization. After
an idle period the fields may require re-entry — this is not a silent refresh.
For n8n the owner reported a failure, but the symptom was not yet reproduced;
do not declare it fixed. Diagnostics and recorded boundaries:
[identity-gateway-troubleshooting.md](../integrations/identity-gateway-troubleshooting.md).

## 2. Who exists now and what the roles mean

| Group | Purpose and limit |
|---|---|
| `homelab-owner` | The single personal owner `alchemmist`; Authentik superuser, explicitly mapped app admin |
| `homelab-observer` | Observation only in admitted applications; this is not root/Secrets/exec |
| `homelab-project-maintainer` | A potential reviewed project scope; not arbitrary cluster admin |
| `homelab-platform-operator` | Infrastructure scope only after review; in Argo CD configuration gives admin |
| `homelab-machine-owner` | Ownership of a specific machine, not automatic ownership of the whole cluster |

The last three groups were created without speculative handouts to people.
Tim is the personal **`antropophag`**, observer. After the native IdP recreation
his UUID was updated in the exact app links; the WebUI/Wiki/Grafana IDs are
preserved, Rancher has the new native SSO record with the same grants (the old
records disabled). No password is set yet, no MFA/real first login:
[current identity](identity-current-state.md). The Wiki keeps his former editor
exception by exact subject; that is not editor for the whole observer group.
In WebUI he is a user, not an admin. The LiteLLM production app is owner-only.

Before assigning a group, read **all the app mappings**, not just its name. For
example, platform-operator in Argo CD is admin; in Grafana an admitted non-owner
is Viewer, except for the separately assigned `app-grafana-editor` → Editor.
Group names are an integration contract. Renaming can revoke/change access.

## 3. How to add a new person

**If this is a new cluster administrator:** the full procedure is
[Authentik/MFA → NetBird identity/device + JWT policy → separate SSH and
Kubernetes/app rights](../../../network/netbird/README.md#how-to-add-a-new-administrator).
None of these steps grants the others automatically. The Linux account is created
manually via [Ansible username + public key](../../host-access/ssh-user.md),
without sudo and n8n.

### Before creation

Compose a request: personal username, verified identity, which applications,
exact roles/projects, whether Linux/VPN is needed, duration and who approved.
Separately determine whether old app accounts with data exist. Do not create a
duplicate on top of an old account.

Make a private pre-change backup of the IdP and important app DBs. Prepare the
owner recovery and a separate open owner session; do not experiment on the only
available access. User passwords/QR/tokens must not go into tasks, PRs, logs or
screenshots.

### Option A: a new ordinary user via the UI

In the Authentik admin interface open Directory / Users management (the menu
names may change between versions) and create an active personal record without
superuser. Set a strong temporary password through the stock Set password
action. Select only the approved groups. UI settings are not automatically
considered transferred to Git.

Deliver the initial credential via a password manager / an independent protected
channel, not public chat, Git or shell arguments. SMTP invitation/reset delivery
is not yet considered configured. Verify the actual delivery to the recipient in
person. The first login and TOTP enrollment are performed by the person
himself; he stores the recovery codes safely. You must not register a device
“for him, for a test”.

After creation, record the reviewed immutable UUID and the needed app ID
mappings. If the user is later moved under bootstrap automation, you must not
simply add his username to the mapping: the initializer stops at an existing
user without a bootstrap journal. That is an intentional guard against
capturing an existing name.

### Option B: controlled bootstrap from source

`deploy/identity/account-mappings.json` is the registry of pre-reviewed people
and old application IDs. Follow the format of the existing records, but add
old-app-ID fields **only when the IDs themselves are really verified**. Do not
invent UUIDs.

`configure.py` creates a private `<username>-login.json` with the initial
password and the `initialized` marker. On first bootstrap the password is set
once; after `initialized=true` re-application must not return the initial
password. An existing username without a journal is an error for manual identity
review, not a reason to delete the user or synthesize a journal. Do not flip the
marker to false.

Do not copy the owner mapping to a new person and do not add him to
`homelab-owner`: the initializer deliberately forbids a second owner and
unexpected owner membership.

**Important:** the current initializer is not a full user lifecycle controller.
After initialization it is not an authoritative reconciler of all
`is_active`/groups and does not implement safe adoption of UI-created users.
Membership and revokes must be changed explicitly and checked live;
documentation intent is not the same as enforcement.

## 4. How to grant access to an application

Check three things independently:

1. **Admission in Authentik:** the application binding admits the needed
   group/person.
2. **Account linking:** the exact subject matches the expected application ID.
3. **Application authorization:** the needed project/role, without extra global
   privileges.

For foundation apps the intent list is `services.json` / `groups`; for Argo CD
a separate `argocd_oidc` controller; for app-specific roles their own mapping.
The `groups` field in an account mapping describes bootstrap intent, not all
current grants.

Example: to give read-only access to Grafana, an approved observer admission
and an actual Viewer on the Grafana API are needed. Harbor access additionally
needs reviewed project membership/permissions. A Kubernetes namespace needs a
restricted Rancher/RoleBinding, not carrying over the owner kubeconfig. LiteLLM
admission is currently owner-only: do not add an observer group without a
separate review of the free-SSO limits, roles, financial/key APIs and
existing-user linking.

After a change, verify a clean login and server-side rights. A negative check
is mandatory: a non-owner cannot become admin, read others' data or gain
authority merely by editing email/name.

### The trap: removal from the catalog is not revocation

`configure.py` **adds missing application bindings** but does not
automatically delete old extra bindings. Removing a group name from
`services.json` does not by itself revoke the already-created binding. The extra
live binding must be explicitly removed/disabled after review, and the absence
of an alternative allowing path checked.

A re-apply can restore a deleted binding if it remained in source. So change
both the source intent and the live enforcement. The Argo CD controller
separately stops on unexpected application group bindings; that is a different
mode, not a universal revoke.

## 5. MFA and a lost device

The native validation stage `default-authentication-mfa-validation` is set to
`not_configured_action: configure`, not skip. TOTP/WebAuthn/static classes are
allowed; the stock configuration stage is TOTP setup. This does not mean every
person has already registered all factor types or recovery codes.

If a code is not accepted: check the device and server clocks, the correct
entry, the current code period and the real stage. Do not weaken the MFA
policy/do not enable skip as a universal fix. For tests use a separate fixture
identity.

Loss of the owner's device is a recovery incident: verify identity outside the
lost channel, use independent break-glass/backup codes, revoke the lost factor
and the related sessions in an agreed order. The mere availability of the admin
API is not permission to silently reset the owner's MFA. Do not replace the
working password with a value from the old `owner-login.json`: the initial file
may be long stale.

## 6. Disabling a person / offboarding

An action plan, not a promise of instant global logout:

1. Remove him from the desired grants/mappings wherever the source would
   otherwise return access.
2. Disable the user in Authentik, revoke live IdP sessions, grants/refresh
   tokens with the tools of the installed version; check that a new authorize
   does not pass.
3. Revoke **separately** each application's sessions, personal/API tokens,
   virtual keys, project membership and legacy local access. Check old cookies.
4. Do not rely only on a vanished tile or a closed browser. JWTs can remain
   valid until expiry; applications do not necessarily consult the IdP on every
   request.
5. With Linux/VPN present: remove keys/peer grants declaratively on the needed
   hosts, check effective sudo/groups and already-established connections.
   Removing a key does not by itself end a process/SSH session; owner/root
   disablement is a separate incident plan.
6. Do not revoke shared production machine keys together with the person
   without a dependency assessment. Move ownership/rotations under control and
   check the consumers.
7. Keep the needed audit without credentials; check negative cases in new and
   old sessions. Do not delete user data without a separate decision.

For the Wiki, old non-owner local sessions and local passwords are already cut
off by the server. For the other applications the same level of fallback/old
session closure cannot be claimed automatically: that is part of the remaining
cluster-wide lifecycle inventory.

## 7. SSH and administrator access to operations

For a new personal Linux account without sudo, the
[manual `ssh-user.yml`: username + public `.pub`](../../host-access/ssh-user.md)
is enough. Authentik/n8n are not needed for that; NetBird, application roles
and Kubernetes are granted separately. The old `users.yml` below remains
exact-key inventory management.

A separate [host-access runbook](../../host-access/identity-host-access.md)
describes the exact assignments, key replacement, the disabled state, sudo
verification and revocation on the former hosts.

From the owner's Mac, with an existing verified SSH identity:

```sh
ssh -o Hostname=109.173.40.247 \
  -o 'HostKeyAlias=[socrat.alchemmist.xyz]:2222' socrat-0
```

Run Kubernetes commands on the node with an explicit kubeconfig:

```sh
K3S_CONFIG_FILE=/dev/null kubectl \
  --kubeconfig /etc/rancher/k3s/k3s.yaml -n identity get pods,pvc
```

Do not disable host key checking. Do not copy the admin kubeconfig into
someone else's home. Request sudo rights for Ansible safely; do not store
passwords in the inventory. The privileged check of Tim's keys/PAM/sudo passed
on four nodes, but the actual login with his private key must be checked by
himself — private keys are not requested.

Read-only inventory: `scripts/identity-audit.py --output <PRIVATE_NEW_FILE>`.
It reads no shadow, private keys, tokens or Secret bodies, but contains
usernames, key fingerprints and RBAC topology: the result is still private, not
auto-publishable.

## 8. Applying the configuration

From `ansible/`, with the current inventory and verified owner SSH:

```sh
# Foundation — real IdP/ingress changes, NOT a dry-run and NOT CSS only.
ansible-playbook playbooks/authentik.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"'

# Only an explicitly selected integration; the default empty list migrates nothing.
ansible-playbook playbooks/identity-integrations.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e '{"identity_oidc_services":["litellm"]}'
```

Look up the supported dedicated integrations in `integrate.py` and the roles;
do not invent a service name. The n8n gateway belongs to the foundation
manifests, Argo CD to the separate `argocd.yml`. A Wiki Secret alone will not
add OIDC to the old image: the corresponding immutable runtime/chart is needed.

`authentik.yml` imports `vpn-edge.yml` for namespace watch/RBAC; this is not a
harmless UI-theme operation. Before running, re-review the whole imported play
graph. To change only the appearance, use the separate branding playbook.

## 9. What to check after any rights grant

- Trusted HTTPS, the correct hostname/issuer/callback, no `verify=False`.
- The personal password+MFA chain; positive and negative admission.
- Server-side profile/ID/role, not just a dashboard caption/screenshot.
- Old data on the former app ID, without an empty duplicate profile.
- The owner recovery remains available and is checked by the owner himself
  separately.
- The machine API with a working scoped key; without a key — 401/403, not
  login HTML.
- Webhooks/API/public status did not end up behind an interactive redirect.
- No fixture users, MFA devices, app keys or temporary bindings left after a
  smoke.
- Source, runtime Secret references and the post-upgrade reconcile are
  consistent.

## Network changes of November 6

The [summary](../../../network/README.md) and [NetBird](../../../network/netbird/README.md)
replace the old mandatory device-approval procedure: approval flags are now
off, admission remains personal MFA/JWT group-restricted. A new person does not
automatically receive Linux/sudo/app roles. Do not restore Mac resolver files,
the internal TV profile or the separate TV domain at onboarding. Native Grafana
anonymous org access is off; the public traffic-light share is a separate
explicitly agreed exception.
