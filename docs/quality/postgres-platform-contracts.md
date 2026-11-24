# Postgres platform runtime contracts

## Operator-managed pods behind selectors

`charts/postgres-platform` renders the CloudNativePG `Cluster` resources and the
NetworkPolicies/Services that govern them. CNPG creates the instance Pods from
those clusters at runtime; no offline Helm render contains them. Consequently
these policies/services intentionally reference selectors that are valid only in
the live cluster:
- `pg-common-ingress`, `pg-critical-ingress`, `pg-internal-ingress`
  (NetworkPolicy): select `cnpg.io/cluster` instance pods and admit their peers,
  the CNPG operator and runtime prometheus metrics scraper. The operator-created
  pods and the operator-managed prometheus pod cannot be rendered offline.
- `pg-common-writer-service-probes` (NetworkPolicy): targets the pg-common
  primary instance (also runtime-created) for the monitoring probe.
- `pgadmin-database-access` (NetworkPolicy): selects the three CNPG tiers for
  pgAdmin database access.
- `pg-common-primary-metrics` / `pg-critical-primary-metrics` (Service):
  scrape the runtime primary instance of each tier.

This is the same evidence-backed runtime-provider class as the operator-managed
postgres/prometheus peers already handled by the release peer registry; the
instance pods cannot be produced by the offline renderer.

## pgAdmin image contracts

The pinned pgAdmin image is `dpage/pgadmin4:9.19@sha256:3591b3d0...`. It reads
`PGADMIN_DEFAULT_PASSWORD` from Secret `pgadmin-bootstrap` via `secretKeyRef`;
the application has no file-based alternative for the bootstrap credential. The
OIDC client secret is deliberately file-mounted, but the bootstrap password is
an env-only input. Secrets are managed out of band.

Docker verification during this pass:
- with uid 5050, read-only rootfs and the stock entrypoint, startup initially
  failed at `/pgadmin4/config_distro.py: Read-only file system`;
- the image's documented `PGADMIN_CUSTOM_CONFIG_DISTRO_FILE` override moves
  that generated file to `/tmp/config_distro.py`. With that override, writable
  `/tmp` and the pgAdmin state volume, the same pinned image completed pgAdmin
  application initialization and started gunicorn. This supports the applied
  `readOnlyRootFilesystem` plus /tmp emptyDir fix instead of registering the RO
  finding as unavoidable.
- `/misc/ping` is the upstream pgAdmin health endpoint used by both the existing
  readiness probe and the newly added liveness probe.

Evidence file covers all registered object names above.
