---
title: RustFS foundation review
---

RustFS foundation is **inactive and incomplete**, not a deployed artifact service.
The source runbook is `docs/rustfs/foundation-review.md`; implementation contract
is `docs/n8n/spi/rustfs-migration-plan.md`. Native OIDC exists in the pinned 1.0.4
release, but Authentik group authorization and the download gateway have not yet
been implemented or verified. No public S3 or console ingress exists in the new
chart. Never expose root login publicly or mount root keys in SPI/readers.

Storage is intended for a single socrat-0 node, using a retained local volume.
This is not HA or independent backup. Requested local-path capacity is not an
enforced filesystem quota. A separate reviewed rollout and runtime security
checks are mandatory; keep all activation switches off.
