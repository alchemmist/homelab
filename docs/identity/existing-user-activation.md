# Existing-user password/MFA activation — 2026-11-07

The owner requested a clean first-use experience for the existing second human.
**Reset the existing identity, do not delete/recreate it.** Its UUID, native app
links, groups and roles must survive. See `deploy/identity/browser-auth-policy.json`
and the audited flow expectations in `deploy/identity/existing-user-activation.json`.
These declarations record expectations; they do not schedule token issuance.

## Applied state

- Existing `tim` identity and stable provider subject preserved. No new human
  account, email-based merge, role expansion or service data deletion.
- Previous IdP password made **unusable** using the native user model. The operator
  did not set or retain a replacement human password. Old sessions/OIDC access/
  refresh/API tokens were inspected/revoked for this user only (none present).
- Removed the initial plaintext password from the active private `tim-login.json`
  bootstrap journal, retaining `initialized=true` and ownership/mode0600. Routine
  configuration therefore must not recreate/reset the initial password.
- Issued one user-bound FlowToken: expiring24h, revoke-on-execution. Credential
  value stays in protected delivery files, **never Git, chat, wiki or issue**.
- Owner password/groups and ordinary auth/recovery flows unchanged. No service,
  IdP or database restart. Earlier app-password cleanup remains in force;
  Umami access stays suspended pending genuine native OIDC (#85).

## Flow and security boundary

The instance originally had **no Brand recovery flow configured**. A narrow
`homelab-existing-human-activation-v1` flow was created instead of changing global
Brand recovery or enabling public signup. Authentication requirement is
`require_token`; password and repeated-password prompts preserve the existing
password-validation policy. A separate never-create UserWrite stage updates only
an existing pending user, followed by the existing mandatory MFA validator and
native login stage. Flow/write policy requires the active token-bound nonowner
user and rejects superusers/owner-group members. No editable username/email/role
fields or group grants.

**FlowToken intent is `verification`, matching the native recovery-link factory.**
Do not label it `recovery`: that is the separate emergency recovery-key mechanism
and must not become an alternate password/MFA bypass. Flow designation `recovery`
and Token intent are different concepts. Final active token was verified to use
`verification`, with the same unconsumed key. Native ExpiringManager excludes
expired tokens; no manual expiry bypass or global token policy change.

The token is consumed when the flow starts, not only after completion. Do not
open the real link to test it, and do not forward it through public/untrusted
channels or link scanners. If the tab/session is lost or the link expires, revoke
and reissue explicitly after checking actual user state; never blindly rerun a
password-reset script after the human has enrolled.

## Delivery and acceptance

The owner delivery file is local Mac
`~/Library/Application Support/homelab/identity-onboarding/tim-activation.txt`.
Parent0700, file0600, transferred over pinned internal SSH with checksum validation.
It contains the link, exact expiration and instructions. The owner forwards only
to the intended person via a trusted channel. The person opens it in a fresh/private
browser window, sets a personal password and enrolls MFA. A normal username/password
login before activation will not work: the old password was intentionally disabled.

Before touching the real identity, a disposable, groupless, nonprivileged user
completed the native HTTPS challenge sequence: password/repeat → TOTP setup →
exact fixture session. Token replay from a fresh client and tokenless flow access
were denied. Fixture user/factors/sessions removed by exact PK/UUID. No real human
password, TOTP secret or MFA login was supplied or observed. Final metadata checks
confirmed old password unusable, actual link unconsumed/unexpired, owner excluded,
fixture absent, user UUID/provider subject unchanged and no real-user first login.
Native expiry-manager code was checked. This is protocol acceptance, not a visual
browser or completed first login by the real person.

Private receipts and issued-token metadata are on socrat-0 under
`/var/lib/homelab-person-auth-migration/`; protected snapshots can retain invalidated
historical credentials. Never restore an old snapshot/journal to reintroduce them.
Routine operators must use guarded issuance, preserve identities and revoke an old
link before reissue. This does not enable public email recovery or claim that SMTP
invitations were configured/sent.
