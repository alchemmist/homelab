---
title: RustFS foundation (source only)
---

RustFS foundation **source is implemented but inactive**, awaiting independent
review and a separately authorized runtime rollout. It is **not deployed** and SPI
publisher behavior is unchanged. All committed activation defaults remain false.

Read `docs/rustfs/activation-checklist.md` for real provisioning, private input
formats, phase order, IAM/SSO/TLS/download tests and rollback; official release
and Authentik semantics are recorded in `docs/rustfs/foundation-review.md`.

The source pins official RustFS 1.0.4 by digest, retained socrat-0 standalone
20Gi storage, nonroot runtime/probes/resource bounds/network isolation. Root keys
are only for storage/private operator bootstrap. Separate writer/reader SigV4
users have exact private spi/v1 prefix policies, never root. Writer is not mounted
into SPI or enabled in this phase.

Humans use existing Authentik owner/platform authorization. Whole-console proxy
admission plus native confidential RustFS OIDC (PKCE S256/client_secret_post,
fixed callback, explicit read-only policy claim) is configured separately from
machine keys. No public raw S3 or ungated console/root-login route exists.

The authenticated read-only artifact reader serves
`https://spi-evidence.socrat.alchemmist.xyz/spi/v1/<event64hex>/<manifest64hex>/...`
as bounded exact-byte attachments, checks manifest and artifact SHA256, rejects
unsafe keys/queries/encodings/redirects and never trusts browser identity headers.
Evidence uses Authentik forward_single, not the console's full-proxy mode.
Anonymous requests return 401 with a fixed authenticate Link; establish an
Authentik evidence session first, then reopen the deterministic file link.

Private idempotent provisioning tools do not modify existing users/roles or
memberships. No secret RBAC/ConfigMaps, image push, IdP/cluster mutation or browser
login was performed by this source change. Offline tests are not runtime proof.
The reader image still needs an approved build/digest and the full activation
checklist, actual session and IAM tests must pass before any SPI switch.

Single-node Retain local storage is **not HA or independent backup**. Requested
local-path capacity is **not an enforced filesystem quota**. Existing n8n IDs,
credentials/PVC/encryption key, calendar, blog write-disabled state, historical
comments and queued jobs remain untouched. No fake incidents or publication tests.

## Public continuation 2026-11-06

Protected public entrances are now deployed with valid cert-manager TLS on both
public IPs. Network isolation recheck passed after external NetBird fix. Native
console URL is https://rustfs.socrat.alchemmist.xyz/rustfs/console/ (not root).
**Foundation acceptance still requires real owner/MFA/native OIDC and evidence
file download/hash, outsider and logout tests; SPI remains off.** Full evidence,
fixture URL and exact hash/manual steps: `docs/rustfs/public-foundation-20261106.md`.
Single-node Retain storage is neither HA nor independent backup. Rollback must
preserve PVC/PV and account for manual prune-OFF ingress removal.
