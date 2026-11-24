# LMS runtime contracts

The lms release (`charts/lms`, pinned image
`ghcr.io/alchemmist/lms@sha256:4f8dea99...`) reads its database DSN and OIDC
client credentials from the environment via `secretKeyRef`:
`LMS_DATABASE_URL`, `LMS_OIDC_CLIENT_ID` and `LMS_OIDC_CLIENT_SECRET`. The app
has no file-based configuration interface for these values; secrets are managed
out of band.

Docker verification: the pinned image runs as uid 10001 with read-only rootfs
and writable /tmp through configuration parsing and reaches its intentional
PostgreSQL availability check without a filesystem-write error; startup aborts
only when a real database is absent, as designed. The chart adds a dedicated
ServiceAccount, non-root + RO rootfs, /tmp emptyDir, /healthz liveness probe and
a NetworkPolicy (traefik ingress; postgres/authentik/public HTTPS + DNS egress).
The authentik release objects are loaded as NetworkPolicy peers offline.
