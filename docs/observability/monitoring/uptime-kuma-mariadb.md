# Uptime Kuma v2 with MariaDB

Uptime Kuma runs as a floating single-replica Deployment. Its database is MariaDB on the local disk of `socrat-0`; the Kuma Pod has no node selector and may move between cluster nodes. MariaDB is intentionally a separate single-node dependency for now, not an HA database cluster.

The production migration preserved the 21 monitors, public groups, custom status-page CSS and heartbeat history. The old SQLite directory remains only in the dated backup archive outside the live workload; it is not mounted by the chart.

The chart creates the database Secret on a fresh install with generated credentials. Existing Secrets are retained on upgrades. The MariaDB data directory is `/srv/uptime-kuma-mariadb` on `socrat-0`; back it up with MariaDB-aware tooling before upgrades or node maintenance.

The live status endpoint is `https://status.alchemmist.xyz/status/socrat`. Validate both public ingress addresses after any chart change.

## Credential ownership and November 2026 recovery

Argo renders now **omit** the DB Secret (`database.bootstrapSecret: false`). The existing Secret is kept privately, has `helm.sh/resource-policy: keep`, and was detached from the obsolete exact Argo tracking ID with a metadata-only, hash-approved operation. Do not enable automatic pruning or regenerate this Secret during normal upgrades.

A controlled application-only restart on 2026-11-06 exposed a mismatch between the Secret and the actual database account password. The application was unavailable during investigation and recovery; this was not a zero-downtime rollout. MariaDB itself was not restarted. Existing native Kuma users/auth settings were fingerprinted before and after and matched exactly.

The working root credential was validated from the running MariaDB container. The old application's plaintext DB password was not recoverable from the checked copies. **No existing SQL account password was reset.** The bounded `kuma-db-account-recovery` maintenance task created `homelab_kuma_app` with the original account's exact schema-only grant (including the escaped underscore), validated it, and updated only the existing Secret data. The old SQL account/grants were checked unchanged. `applicationDatabaseUsername` selects the new application identity independently of `database.username`, so this change does not roll the MariaDB Deployment. Private snapshots and receipts remain on the controller/server, not in Git.

Audit recovery with `playbooks/public-web-maintenance.yml -e public_web_maintenance_task=kuma-db-account-recovery`; apply requires its fresh hash. A partial/uncertain write blocks reruns. Do not adopt a pre-existing same-name account or delete the old account speculatively.

For a genuinely fresh, empty-datadir installation only, explicitly approve bootstrap and select matching application/database usernames. Helm rejects `database.bootstrapSecret=true` with mismatched usernames. Do not change the live `database.username` to bypass this guard.

The public status page remains anonymous read-only. Its policy bridge does not publish Socket.IO or the administrative API. Native administration is at `https://kuma.socrat.alchemmist.xyz/dashboard`, behind personal Authentik MFA and owner/`uptime-kuma-web-admins` admission, followed by Kuma's own existing native authorization. Admission alone does not make someone a native administrator. Machine push endpoints retain their native token validation.
