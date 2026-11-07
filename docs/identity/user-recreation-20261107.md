# Native Authentik user recreation — 2026-11-07

The owner explicitly rejected the added existing-account activation mechanism and
requested a fresh native Authentik user. This supersedes the previous activation
proposal/deployment; do not reinstall that flow or use its old delivery file.

## Subsequent native username change

On explicit owner request the same user was renamed from `tim` to `antropophag`
by native username-only PATCH. UUID, hashed provider subject, email, display name,
groups and unset-password state remain unchanged. Active account/lifecycle/pilot
keys and the initialized bootstrap journal now use `antropophag`; Linux user `tim`,
VPN device names and existing Rancher resource IDs are separate and unchanged.

## Completed

- Native `POST /api/v3/core/users/` created `tim`, display name Tim, same reviewed
  email and four existing groups. Native API creates an **unusable/unset password**.
  No password-setting endpoint, new invitation, recovery token or enrollment flow
  was used. User active/internal, nonsuperuser, no MFA and no completed login.
- New IdP UUID: `6015c85b-82e9-49ce-a4e3-0270c676e26d` (PK92).
  Previous UUID `0d2c194a-dee7-4226-b599-0a44ce2f2b76` (PK6) was first disabled
  and temporarily renamed, then removed by native `DELETE /api/v3/core/users/6/`
  after reviewed mappings were reconciled. It is no longer a second live IdP user.
- Revoked the previously issued activation token and removed only the owned
  `homelab-existing-human-activation-v1` flow, its never-create write stage and
  expression guard. Shared default password/MFA/login stages and Brand settings
  untouched. Removed the now-invalid delivery file from the owner's Mac and the
  declarative activation definition from the current repository.
- Updated reviewed UUID pins, lifecycle/NetBird pilot metadata and the active
  bootstrap journal. `initialized=true`, no initial plaintext password. Do not
  restore an old journal to reintroduce credentials or an old subject.

## Existing service data and native constraints

| Service | Native result |
| --- | --- |
| Grafana | Same native user2/UID and Viewer membership; changed only Generic OAuth subject from the old to the new installed IdP `user.uid` hash. No email merging or password change. |
| Open WebUI | Same native user, profile, role and six chats; changed only the existing `oauth.oidc.sub` UUID under CAS. Auth row/session-stamp and discarded legacy password remain unchanged. |
| Wiki | Same native editor and entire account-table fingerprint. No previous completed subject binding for this user. Changed only its subject-map keys in the existing Secret, then one scoped Recreate rollout to load environment settings. Same image and PVC. |
| Rancher | **Principal IDs are immutable**, confirmed by native admission dry-run; do not bypass the webhook. Created native `u-authentik-tim-v2` with the new principal, mirrored exactly the existing user-base/cluster-member grants, and changed the restricted admission entry. Old `u-authentik-tim` disabled; old records/inert grants retained. New controller mapping/prefix ensures future reconciliation uses the reviewed replacement and does not rewrite immutable bindings. |
| Umami | Remains suspended pending genuine native OIDC (#85). No analytics deletion or restoration of old credentials. |

Owner identity, groups, password, recovery, machine credentials and VPN/SSH access
were not recreated or rotated. No node/database restart or unrelated Argo sync.
The scoped Wiki rollout above is necessary for its existing environment-based
subject map; it is not a new authentication mechanism.

## What the fresh native user can do now

This is **a freshly created user without a password**, not a completed onboarding.
Native Create user does not automatically grant a first-login password-setting
screen. In this installation no Brand email-recovery/enrollment invitation flow
was configured before this task; the task intentionally does not configure one.
The owner can use the standard Authentik **Directory → Users → antropophag → Set password**
operation. Password-based login cannot work until password establishment is handled
through a deliberately chosen native procedure. Normal existing MFA policy still
requires enrollment afterward. No invitation was sent and no real-user login was
performed on the person's behalf.

Private exact-ID backups, receipts and reviewed failure/reconciliation notes remain
under the protected person-migration directories. A pre-write cleanup guard failed
on Authentik's distinct policy-binding parent UUIDs and was corrected only after
live binding inspection; the transaction rolled back without modifying the user.
Rancher's immutable-principal failure was likewise inspected before switching to
its supported new-user path, not retried or bypassed.
