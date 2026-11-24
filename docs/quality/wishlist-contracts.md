# Wishlist runtime contracts

The wishlist release (`charts/wishlist`, pinned image
`harbor.socrat.alchemmist.xyz/homelab/wishlist@sha256:49160de2...`) is a Python
application whose runtime credentials are supplied exclusively through the
environment: `WISHLIST_DATABASE_URL` (secret wishlist-postgres) plus the optional
`wishlist-secrets` envFrom (SESSION_SECRET and application tokens). There is no
file-based configuration interface for those values; secrets are managed out of
band.

Hardening in this pass: non-root uid/gid 1000, read-only rootfs, dropped
capabilities, seccomp RuntimeDefault and resource budgets on the main and init
containers, /tmp emptyDir, liveness/readiness probes on the app's `/` endpoint,
and a NetworkPolicy limiting ingress to traefik/monitoring and egress to
postgres, rustfs, DNS and public HTTPS. Docker run of the pinned image as uid
1000 under `--read-only` reached the database connection step without any
filesystem-write error; a valid postgres DSN is intentionally required at
startup. The cluster's existing database-backed health endpoint remains the
probe target.
