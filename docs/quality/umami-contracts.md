# Umami runtime contracts

The umami release (`charts/umami`, pinned
`ghcr.io/umami-software/umami@sha256:e69d1a79...`) reads its runtime credentials
from the environment via secret bindings: `DATABASE_URL` and the application
secret bundle from `umami-env`. The application has no file-based configuration
channel for those values; secrets are managed out of band.

Docker verification: uid 1000 with read-only rootfs and writable /tmp reached
Prisma's database connection checks without any filesystem-write error. The
chart now adds a dedicated ServiceAccount, non-root + RO rootfs, resource
requests/limits, /tmp emptyDir and a NetworkPolicy (traefik ingress; postgres,
DNS and public HTTPS egress).
