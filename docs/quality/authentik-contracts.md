# Authentik runtime contracts

This document covers `authentik-server` and `authentik-worker` (Deployments).

The authentik release (upstream 2026.8.6 chart/image, namespace identity) reads
its runtime secrets from the environment through its secret-backed environment
bindings: the secret key and PostgreSQL/Redis credentials. The server and worker
have no alternative file-based channel for those values; secrets are managed out
of band.

Docker verification: `ghcr.io/goauthentik/server:2026.8.6` was run as uid 1000
with read-only rootfs and a writable /tmp. The server reached the intentional
PostgreSQL connection loop without any filesystem-write error, so the new
`readOnlyRootFilesystem` contract is valid. The chart now applies non-root + RO
rootfs + dropped capabilities + RuntimeDefault and /tmp emptyDir to server and
worker, and NetworkPolicies restrict server/worker traffic to the expected
postgres, redis, DNS, monitoring and outbound-HTTPS paths. The external
identity-runtime ServiceAccount remains loaded from the reviewed foundation
objects by the gate.
