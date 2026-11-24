# n8n runtime contracts

The n8n release (`charts/n8n`, pinned image
`docker.io/n8nio/n8n@sha256:624a1f10...`) reads its database credentials and
workflow encryption key from the environment via `secretKeyRef`:
`DB_POSTGRESDB_USER`, `DB_POSTGRESDB_PASSWORD` and `N8N_ENCRYPTION_KEY`. There is
no file-based alternative for those values; the secrets are managed out of band.

Docker verification: with uid 1000, read-only rootfs, `/tmp`, the `.n8n` PVC and
a dedicated `/home/node/.cache` emptyDir, the pinned image completed asset
compilation and logged `n8n ready on ::, port 5678`; GET `/healthz` returned
HTTP 200. The chart now applies that exact read-only/cache layout, adds a
liveness probe to the xray sidecar using its existing loopback health checks,
and isolates the main workload and backup CronJob with NetworkPolicies.
