# Safety constraints and outstanding risks

- Preserve accounts, roles, passwords, keys, sessions, history and native SSO/TLS/PKCE. Signing in on someone's behalf is not user acceptance. Do not bypass MFA.
- Use Git first and reconcile only the target. No blanket sync or prune, forced deletion, live image overrides, arbitrary schema upgrades or network restarts.
- Do not replay workflows, publish, run paid inference or sync bank data for a test. Keep secrets and private receipts outside Git; use mode `0700` for directories and `0600` for files. Do not print payloads.
- Leave VPN workloads on `socrat-2` alone. Do not change Mac VPN, DNS or routes, AllowedIPs, WireGuard identities, operator keys or permanent sudo access for convenience.
- The `socrat-0` relay between `socrat-1` and `socrat-5` is a non-HA mitigation. The underlying cause has not been established. Healthy applications do not prove VM recovery or HA.
- Historical Prometheus corruption is a separate issue. Do not clear the WAL. A VM cold boot and full independent restore require separate maintenance acceptance.
- Backups: the daily n8n job uses the current claim. The latest paired archive on `socrat-3` passed SHA verification; its SQLite database was independently restored and passed a read-only integrity check. One unpaired archive was not accepted. See the [coverage matrix](../records/handoffs/backup-coverage-20261116.md) for datasets still outstanding. A retention policy is not a backup.
- Preserve the historical Wishlist OutOfSync state, SPI failure and limits on human callbacks and the production telemetry child. Do not mark them resolved without a test.

## Interpreting historical results

- “Synced/Healthy”, test results, screenshots and counters apply only to the resource and time recorded. Do not add counts across suites or generalize an owner or fixture test to a new user, another device or ISP, or full disaster recovery.
- `tim` in old identity-provider logs is a former login. The Linux account `tim`, Rancher resource names and `wg-socrat` are separate identifiers; do not rename them in bulk.
- NetBird access does not grant SSH, sudo or cluster-admin rights. Authentik MFA does not replace application RBAC.
- Pushing an image or commit does not prove rollout. Check auto-sync settings and hooks.
- Historical migration scripts can change production. Before running one, perform a fresh audit, verify scope, UID and hash, make a private backup and check locking or compare-and-swap protection. Investigate uncertain writes before retrying.
- Never publish credentials, QR codes, private keys, subscriptions or share, recovery or activation URLs that contain tokens. A public hostname does not imply anonymous API access.
