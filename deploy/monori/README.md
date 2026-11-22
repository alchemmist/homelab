# Activating native Monori SSO

Use Monori front **and** back images from `2c9d0dd` or later. Its publisher
updates the Harbor digest pins; do not substitute a mutable tag. Password login
stays enabled. No ingress auth proxy, PVC modification or sync-service change.

1. From this reviewed checkout and the approved operator environment, provision
   the IdP client **before** the backend rollout:
   `cd ansible && ansible-playbook playbooks/identity-monori.yml`.
   Do not replay the identity foundation. This scoped playbook creates the
   `homelab-monori` provider, binds `homelab-owner` and the UUID-checked `antropophag` user (Monori only) before attaching it to
   the app, and writes `monori/monori-oidc` without displaying credentials.
   Keep the private `monori-client-secret` in the identity backup; never rotate
   automatically to repair a missing file. A replay must be able to read and
   match the provider secret; on drift or a masked value it stops before writing
   the Kubernetes Secret. The playbook can be safely retried.
2. Merge the chart configuration and let Argo reconcile. If the Secret was
   absent when the backend pod started, SSO stays disabled: after provisioning,
   arrange a targeted backend rollout through GitOps so it reads the Secret.
3. Check `https://auth.socrat.alchemmist.xyz/application/o/monori/.well-known/openid-configuration`
   for the exact configured issuer and `https://monori.alchemmist.xyz/api/auth/oidc/status`
   for `{"enabled":true}`. Neither check is proof of a successful browser login.
4. For an existing budget, **first** sign in with the local password, then use
   **Settings → Account → Link SSO to this account**, complete Authentik MFA,
   sign out of Monori and use **Sign in with SSO**. Verify the same accounts and
   transactions; verify an unassigned user is denied. Do not link by email or
   edit the production database. Never post tokens or authorization codes.

Rollback: set `oidc.enabled: false` in the production values and reconcile.
This preserves password access, identity associations, budgets and secrets.

## Socrat closed admission

With the SSO-only-capable backend and `oidc.onlyUserIds: [1, 3]`, only the two
prelinked budgets are admitted. Password sign-in, registration and self-linking
are unavailable. Removing the key restores mixed authentication; setting it to
an empty list blocks everyone. Disabling OIDC alone does not enable passwords.

### Schema 0022 rollout prerequisite

Before syncing, verify a recoverable PostgreSQL backup and provision the `monori-pg-migrator` Secret (`DATABASE_URL`) in namespace `monori` using the schema owner with verified TLS. Never put the credential in Git or grant the app/console schema ownership. Ensure the pinned backend contains `/app/server/postgres/0022_refunds.sql`. The transactional PreSync hook accepts 0021/0022 only. Use a full Argo application sync (selective sync skips hooks); inspect a failed Job before retry. Do not downgrade production data as an image rollback.
