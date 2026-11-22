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
never enable the postgres superuser for UI access. Browse catalogues with normal PUBLIC
permissions; on `pg-common/lms` this role also has USAGE on public and SELECT on its existing
tables. No grant of `pg_read_all_data` or administrative privileges.
The removed async standby was outside `pg-critical`'s synchronous quorum.

Desired state: `charts/postgres-platform/templates/pgadmin.yaml`. Keep `pgadmin-bootstrap`
and `pgadmin-oidc` Secrets out of Git. The DNS playbook `pgadmin-public-dns.yml` checks all
four authoritative zone writers before a serial approved record addition; don't use a client
hosts override to declare the public deployment complete. Verify public TLS, anonymous redirect,
owner sign-in, and denied access for a nonmember before acceptance.

DNS is HOME-only: the VPS ingress does not watch namespace `postgres`. Do not grant the edge controller watch access to database Secrets to publish this UI.

Non-owner SharedServer rows omit the owner's CA filename. Keep `verify-full`; the init container builds libpq's default `root.crt` from only the three public CNPG CA certificates. Roll pgAdmin when a cluster CA rotates. Verify a connection **without** supplying `sslrootcert`, using the shared login and its password helper.
