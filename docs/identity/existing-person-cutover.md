# Existing non-owner browser account cutover — 2026-11-07

The owner explicitly requested Authentik-only sign-in for the existing second
human (`tim` in the reviewed account mappings), preserving data and existing roles.
Desired expectations are recorded in `deploy/identity/browser-auth-policy.json`;
this is an audit policy, **not** a scheduled writer or an additional authorization
grant. Do not infer that admission to Authentik grants application administration.

## Identity and admission

Existing IdP UUID, reviewed email, native account IDs and configured subject links
were reconciled before mutation. No email-based automatic account merge, new human,
role expansion, owner password change, MFA bypass or impersonated human login.
The existing Authentik user is active, non-superuser and has a usable password;
it was not reset. No MFA devices were enrolled yet. The bound authentication-flow
validator requires configuration, so first login must enroll a personal factor.
This is not evidence that the person has completed a real first login.

## Applied and checked

| Service | Result |
| --- | --- |
| Rancher | Disabled only the old local human record. Existing OIDC user remains enabled with exactly the same reviewed user-base/cluster-member grants. No old-user Rancher tokens found. Disabled record and inert grants retained as audit/role-mirroring history; no user or data deletion. |
| Grafana | Bound exact current provider subject to the **existing** native user. Provider is `hashed_user_id`: use the installed IdP resolver, not the UUID or a guessed email. Cleared old password/salt, rotated reset nonce, revoked target sessions. Native API reports Generic OAuth; local Basic tests return401. Original Viewer membership and other users/service-account keys unchanged. |
| Open WebUI | Existing UUID and OIDC subject preserved. Replaced old password with an application-native hash of a cryptographically random credential whose plaintext is discarded, and rotated only that user's session stamp. Prior JWT stamp is rejected. Active auth row **must remain true**: this runtime uses it for OAuth too. Six existing chats, profile, role and factors preserved. No personal API keys found. Local login negative check400. |
| Wiki | Already owner-only local recovery; this user is not a recovery owner. Reviewed subject mapping and editor role preserved. No old local sessions or API tokens found; native password attempt401. No need to delete or recreate the account. |
| Umami | **Temporarily suspended, not migrated to working OIDC.** Existing local password replaced with discarded random bcrypt credential; set only its soft-disable timestamp, retaining row identity and every website/team/statistics record. Current compiled getUser/getUserByUsername filters exclude this state, rejecting login and existing JWT/API auth, including legacy tokens without a password fingerprint. No personal API keys found. Owner, website rows and team memberships unchanged. Public UI/tracker/heartbeat200; local login401. |

Harbor, n8n, Uptime Kuma and 3x-ui native account inventories did not contain this
person. No corresponding local human account was deleted there. This is not a
rotation of shared owner credentials or proof about passwords a person might
remember; existing public admission remains independently enforced.

## Why Umami access is paused

Umami3.4.1 does not currently have our native OIDC integration. Authentik in front
of another password prompt would not satisfy this request. Fail closed for this
human rather than keep the old bypass or falsely claim SSO. **Issue#85 remains
open**: https://github.com/alchemmist/homelab/issues/85. Re-enable only after reviewed
native OIDC preserves the existing identity/data/roles and acceptance passes.
Do not call the native delete-user action: it cascades deletion of analytics data.
The soft-disable operation here deliberately did not invoke that destructive path.

## Change safety and remaining boundaries

Live changes used exact-ID/email/subject checks, private before-state backups,
locks, approved fresh state hashes, SQLite transactions/CAS or Kubernetes
UID/resourceVersion preconditions. Uncertain-write markers guard failed applies;
all completed steps have private receipts. Credentials, session material and
backup contents are not in Git. No application image, node, database or pod restart,
unrelated Argo sync/prune, machine credential or infrastructure route change.

Personal SSH keys/Linux sudo and WireGuard/NetBird transport are distinct from web
SSO; this was not a network/device offboarding. Existing machine accounts and
owner recovery remain. Fresh browser password/MFA login by the real human has not
been performed on their behalf. A future restore must not silently reintroduce
old passwords/stamps or re-enable the disabled local identities. In particular,
restoring Umami access requires OIDC first, not just clearing its disable timestamp.
