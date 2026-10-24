# Uptime Kuma v2 with MariaDB

Uptime Kuma runs as a floating single-replica Deployment. Its database is MariaDB on the local disk of `socrat-0`; the Kuma Pod has no node selector and may move between cluster nodes. MariaDB is intentionally a separate single-node dependency for now, not an HA database cluster.

The production migration preserved the 21 monitors, public groups, custom status-page CSS and heartbeat history. The old SQLite directory remains only in the dated backup archive outside the live workload; it is not mounted by the chart.

The chart creates the database Secret on a fresh install with generated credentials. Existing Secrets are retained on upgrades. The MariaDB data directory is `/srv/uptime-kuma-mariadb` on `socrat-0`; back it up with MariaDB-aware tooling before upgrades or node maintenance.

The live status endpoint is `https://status.alchemmist.xyz/status/socrat`. Validate both public ingress addresses after any chart change.
