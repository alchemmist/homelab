# pgAdmin

`pg.socrat.alchemmist.xyz` → Traefik → `postgres/pgadmin` (one replica, persistent settings).
Native OAuth2 only, provider `homelab-pgadmin`, strict `/oauth2/authorize` callback,
`homelab-owner` binding and matching group claim. The bootstrap account has no local web login.
PostgreSQL login is separate from Authentik: use an authorized database role, not the bootstrap password.
Shared server definitions use the three CNPG `-rw` Services and per-cluster CA certificates.
There are no shared SQL passwords. A read-only DB role is recommended for browsing.
The removed async standby was outside `pg-critical`'s synchronous quorum.

Desired state: `charts/postgres-platform/templates/pgadmin.yaml`. Keep `pgadmin-bootstrap`
and `pgadmin-oidc` Secrets out of Git. The DNS playbook `pgadmin-public-dns.yml` checks all
four authoritative zone writers before a serial approved record addition; don't use a client
hosts override to declare the public deployment complete. Verify public TLS, anonymous redirect,
owner sign-in, and denied access for a nonmember before acceptance.
