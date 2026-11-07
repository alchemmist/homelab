# Scoped human RustFS administrator (2026-11-07)

User explicitly authorized full RustFS administration for their own ordinary SSO login. Live Authentik API and model inspection validated active internal `alchemmist`, PK `5`, UUID `9e33877a-3eaa-4541-98eb-8cdc10088ef6`. Native RustFS provider uses `sub_mode=user_uuid` and signed ID-token claims.

The dedicated `spi-rustfs-policy` scope mapping now emits `consoleAdmin` only when **all three** PK, UUID and username match. Its previous owner/platform `spi-console-reader` fallback remains unchanged for everyone else. Canonical expression is in `scripts/rustfs/provision_identity.py`; provisioning remains explicit/offline and drift-failing, not an Argo workload. No service rollout is required. No group membership, Authentik role or other application's policy was edited.

Live pinned RustFS 1.0.4 builtin `consoleAdmin` was inspected through its supported policy-info API: `admin:*`, `kms:*`, `s3:*` on `arn:aws:s3:::*`, and `sts:AssumeRole`. This is full policy-based RustFS administration, not readonly and not the shared root identity. Root has an owner authorization short-circuit; OIDC sessions remain temporary, subject to normal policy checks and session expiry. Version-specific protections (e.g. rejecting deletion of temporary users or policy attachment directly to temporary session keys; parent-scope restrictions for derived service-account import) still apply. These are not solved by calling an SSO user “super root”.

Only the dedicated claim mapping changed live. Reader/writer policies, app keys, private bucket/object data, TLS/authentication, networks, root credentials, and deployments were untouched. No new local password was created.

Private rollback receipt is under operator private state `rustfs-foundation/20261105T133000Z/human-admin-20261107/`, with old/new mapping and validated identity snapshots (directory 0700, files 0600). Rollback: authenticated PATCH only the saved old `expression` to mapping `d48f9eec-1288-4701-9fd0-0b1c961a74c7`; restore canonical expression accordingly; reauthenticate only the affected RustFS session. Never expose credentials or invalidate unrelated SSO sessions.

Open https://rustfs.socrat.alchemmist.xyz/rustfs/console/browser/ . If an existing session still shows Reader, sign out of **RustFS only**, then use the normal Authentik OIDC sign-in again. Verify bucket enumeration and IAM/admin pages without creating buckets or changing data. Browser verification is recorded separately in the run receipt.
