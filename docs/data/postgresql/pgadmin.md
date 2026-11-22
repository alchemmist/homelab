# pgAdmin

`pg.socrat.alchemmist.xyz` → Traefik → `postgres/pgadmin` (one replica, persistent settings).
Native OAuth2 only, provider `homelab-pgadmin`, strict `/oauth2/authorize` callback,
`homelab-owner` binding and matching group claim. The bootstrap account has no local web login.
PostgreSQL login is separate from Authentik: use an authorized database role, not the bootstrap password.
Shared server definitions use the three CNPG `-rw` Services and per-cluster CA certificates.
Owner-only shared connections use `pgadmin_browser`, a non-admin CNPG-managed login per cluster.
Provision distinct Kubernetes basic-auth Secrets `pgadmin-browser-{common,critical,internal}`
(username `pgadmin_browser`, independently generated passwords) before deploying. The named
password helper accepts only OAuth2 and the exact database hosts, port and login. Keep the
Secrets outside Git. No password saving or master-password prompt. Rotate through CNPG;
never enable the postgres superuser for UI access.
The removed async standby was outside `pg-critical`'s synchronous quorum.

Desired state: `charts/postgres-platform/templates/pgadmin.yaml`. Keep `pgadmin-bootstrap`
and `pgadmin-oidc` Secrets out of Git. The DNS playbook `pgadmin-public-dns.yml` checks all
four authoritative zone writers before a serial approved record addition; don't use a client
hosts override to declare the public deployment complete. Verify public TLS, anonymous redirect,
owner sign-in, and denied access for a nonmember before acceptance.

DNS is HOME-only: the VPS ingress does not watch namespace `postgres`. Do not grant the edge controller watch access to database Secrets to publish this UI.

Non-owner SharedServer rows omit the owner's CA filename. Keep `verify-full`; the init container builds libpq's default `root.crt` from only the three public CNPG CA certificates. Roll pgAdmin when a cluster CA rotates. Verify a connection **without** supplying `sslrootcert`, using the shared login and its password helper.

## Access as of 22 November 2026

**Active:** Authentik admits `homelab-owner`; all three shared connections use `pgadmin_browser`. PostgreSQL sees that shared role, not the SSO username. SQL privileges determine data access, not the user's pgAdmin administrator status.

| Cluster | Databases verified from the pgAdmin pod |
|---|---:|
| `pg-common` | 18 |
| `pg-critical` | 7 |
| `pg-internal` | 1 |

At verification time, `pgadmin_browser` could connect to all 26 non-template databases that allowed connections. It had `CONNECT` on those databases, `USAGE` on application schemas and `SELECT` on existing tables, views and sequences. These are explicit SQL grants, not `pg_read_all_data`. New databases and objects do not automatically inherit them. Row-level security was not disabled.

**Prepared but not enabled:** Authentik has `pgadmin-reader`, `pgadmin-writer` and `pgadmin-admin` groups. Membership of `alchemmist` in `pgadmin-writer` was verified. That membership alone does not yet grant sign-in without `homelab-owner`, or write access. Each cluster has a separate `pgadmin_writer` SQL role (`NOLOGIN`) with read access, `INSERT`/`UPDATE`/`DELETE` on existing application tables and permission to use sequences. It has no `TRUNCATE`, DDL, `SUPERUSER` or `BYPASSRLS` privileges. The pgAdmin connections do not use this role yet.

**Acceptance criteria:** in a browser, verify that a writer can perform DML on a test table and roll back the transaction. A reader must be denied, including when attempting to use the writer connection directly. Separately verify admission for a UI administrator and denial for a user without the groups. Do not expand the privileges of the shared `pgadmin_browser` role. Write access across databases includes Authentik data: once enabled, `pgadmin-writer` membership will be highly privileged.

**Troubleshooting:** if the server expands but one database returns `permission denied for database`, check `CONNECT` on that database. If libpq reports a missing `root.crt`, check the file in the running pod; do not disable TLS verification. After the CA fix, a temporary Chrome user completed OAuth2 and TOTP and expanded all three servers. The test account and profile were removed. This verified connectivity, not write access.
