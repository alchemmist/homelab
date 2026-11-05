---
title: "RustFS evidence foundation"
weight: 35
---

## Current state (2026-11-05)

Private RustFS foundation and protected reader are deployed through the dedicated
manual-sync Argo Application. SPI backend/publisher remains unchanged. Public
console/evidence ingress is **disabled**, not accepted for production browser use.

The full operator evidence/runbook is repository
`docs/rustfs/live-foundation-20261105.md`; activation/rollback checklist is
`docs/rustfs/activation-checklist.md`. These include exact source/runtime/image
revisions, backup verification references, tests and limitations.

Actual storage PUT/GET bytes, scoped IAM denials, nonroot startup, retained PV,
controlled restart persistence and native OIDC authorization redirect/PKCE passed.
This does not prove real human SSO, STS issuance or authenticated browser download.
No personal cookies/tokens or fabricated identities were used.

Private consistent SPI SQLite backup was taken before deployment and verified
header/integrity/foreign keys; IDs/state/intents/attempts were not reset or edited.
No incident/model/Telegram/GitHub tests or changes to original workloads occurred.

Single-node retained local storage is not HA or an independent backup. Its20Gi
PVC request is not an enforced filesystem quota. Runtime memory limit stays4Gi;
explicit2Gi reservation is Burstable and carries overcommit/eviction risk.

## Publication still gated

- Existing secure sudo/become mechanism is needed for additive two-record Knot DNS
  deployment on the authoritative hosts; source is prepared, hosts not changed.
- Shared edge currently has one host-network replica with Recreate strategy and
  automatic Argo sync. A namespace-watch change would restart the VPS entrance;
  parent must coordinate safe ingress cutover/maintenance before publishing it.
- Only then enable tracked browser routes, verify certificates/SNI and real
  owner/platform MFA/native OIDC/session, reject unaffiliated users, and verify
  authenticated fixture download/hash/size and deployed slow-peer behavior.

Do not switch SPI while these gates remain open, widen IAM to make errors vanish,
or expose raw S3/root login outside the protected console. Root recovery remains
private. Preserve retained data/fixtures and private credential journals on rollback.
