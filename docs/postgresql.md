# Socrat PostgreSQL: operator reference

[Unexpected loss of `socrat-1`, 21 November 2026](context/socrat-1-loss-20261121.md): `pg-critical` failed over from node `1` to node `5`, and the former primary rejoined using `pg_rewind`. The test did not cover other clusters.

This snapshot follows the switchovers on 20 November 2026. See the [user guide](https://wiki.socrat.alchemmist.xyz/platform/postgresql/) for an overview and the [operations runbook](postgres-platform.md) for maintenance and CA rotation. Configuration is owned by `charts/postgres-platform`, Argo Application `postgres-platform`, namespace `postgres`.

| In-cluster writer endpoint | Database and service | Durability contract |
|---|---|---|
| `pg-common-rw.postgres.svc.cluster.local:5432` | `umami`, `lms`, `certification`, `socrat` (bot), `litellm`, `registry` (Harbor) | The primary normally runs on NVMe on `socrat-0`, with an asynchronous HDD standby on `socrat-5`. Commits do not wait for the HDD. Emergency promotion can lose WAL that has not reached the standby. |
| `pg-critical-rw.postgres.svc.cluster.local:5432` | `authentik` | Three instances on `socrat-0/1/5`; `synchronous_commit=on`, `ANY 1`, `dataDurability=required`, `failoverQuorum=true`. Losing all standbys blocks commit acknowledgments. Do not automatically relax these settings. |

CNPG reports the actual primary in `.status.currentPrimary`; it need not be on the original node after a switchover. Clients verify the TLS hostname and use separate roles. `lms-ha` is hibernating and its CronJob is suspended. It is not the LMS data source. Backups and PITR are not configured for the new clusters. When investigating degradation, start with `up{job="postgres-platform"}`, replication status and free space on the **actual filesystem**. A `Bound` PVC does not prove there is free disk space.

## Do not delete or rename the `app` databases in `pg-common` and `pg-critical`

In addition to the service databases above, each cluster has its own `app` database: both CNPG resources set `spec.bootstrap.initdb.database` to `app`. Under the [CNPG 1.30.2 monitoring rules](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.2/docs/src/monitoring.md), this is the default database for exporter queries, not a metrics store. Short-lived `cnpg_metrics_exporter` connections were observed reading WAL statistics in `pg-critical/app`. An absence of user tables or active sessions during an inspection does not mean the database can be removed.

Both databases have an English comment explaining their purpose (`\l+ app` in `psql`). The comment warns operators; it does not prevent deletion.

## Migration closeout: user acceptance and source retention are separate decisions

- **Not witnessed:** a user signing in to LMS in a fresh session, completing MFA and opening a protected page. Working OIDC discovery and redirects are technical checks only. Do not claim acceptance based on someone else's login, an existing session or administrator access.
- Nine old PVCs were checked by UID and PV. All were `Bound`, no active pods were found consuming them, and no direct mount of the old Umami hostPath was found. **Retain the sources.** The [review after 2026-12-05 UTC](https://github.com/alchemmist/homelab/issues/216) sets conditions for a separate decision; it is not a deletion timer. See the [inventory](postgres-retained-pvcs.tsv).
