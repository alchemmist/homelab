# LiteLLM vendored PostgreSQL and Redis manifest findings

As of the `dc4ee377` manifest review, the vendored charts under
`charts/litellm/charts/postgresql` and `charts/litellm/charts/redis` are upstream
Bitnami chart defaults. They are not the production LiteLLM database or
coordination service: the standalone PostgreSQL dependency is disabled unless
`db.deployStandalone` is enabled, and Redis is disabled unless `redis.enabled` is
enabled. Production LiteLLM uses the externally owned `pg-common-rw` PostgreSQL
service. Keep those service ownership and enablement boundaries unchanged.

## Residual findings

The remaining default-render findings are:

- PostgreSQL (8): `image-digest`; `no-read-only-root-fs`;
  `read-secret-from-env-var`; `unset-cpu-requirements`;
  `unset-memory-requirements`; `use-namespace` (3).
- Redis (16): `image-digest` (2); `no-read-only-root-fs` (2);
  `read-secret-from-env-var` (3); `unset-cpu-requirements` (2);
  `unset-memory-requirements` (2); `use-namespace` (5).

These findings belong to standalone upstream-default renders, not the active
production release configuration. The bundled public Bitnami image references
are no longer available at their pinned original registry/tag. Do not silently
repoint them to another registry, guess image digests, change database versions,
or alter credentials, persistence, filesystem permissions, network policy, or
resource requests to make the lint pass.

## Decision required to proceed

An owner must choose one of the following before modifying the bundled charts:

1. Supply authoritative provenance for the exact old PostgreSQL and Redis image
   artifacts (including all images used by each chart) and approve a maintained
   downstream fork of the upstream defaults; or
2. Approve a specific replacement chart/image and a tested migration plan that
   preserves PostgreSQL data compatibility, Redis persistence/ACL behavior, and
   credential rotation.

After that decision, validate the actual chart defaults and enabled parent
renders with disposable positive and negative tests. Include image provenance,
PostgreSQL existing-data compatibility and rollback, Redis persistence/ACL and
credential behavior, and workload filesystem/resource requirements. No runtime,
cluster, deployment, or migration tests were performed here. Until then these
findings remain blocking and unresolved; this note is not a waiver or acceptance.
