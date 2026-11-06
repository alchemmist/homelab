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

## Dedicated SPI writer runtime (source complete; activation gated)

`storage_runtime.py` is called by `service.serve` before Store recovery or dispatch.
`SPI_EVIDENCE_BACKEND=legacy|s3` selects only new unlocked jobs; durable job backend
locks remain authoritative. OFF without `SPI_S3_WRITER_FILE` is unchanged. OFF
with retained credentials loads the S3 client for already-S3-locked jobs. ON
requires `/s3-writer/credentials.json`, an at-most-8192-byte JSON object containing
only `access` and `secret`. Invalid/missing files stop startup, never fall back.
Projected Secret symlinks and root:fsGroup1000 mode0440 are supported; public
read or group write is rejected. No credentials in env, argv, logs or repr.

Offline provisioning: `python3 scripts/rustfs/spi_writer_secret.py --private-dir PRIVATE_DIRECTORY`
reads existing private `storage.json` and `bootstrap-journal.json`; it does not
bootstrap anything or call APIs. It verifies distinct root/reader/writer access
and secret values and exact journal ownership hashes. Only writer credentials
are serialized into `automation/spi-evidence-writer`, key `credentials.json`.
Output is private0600, exclusive-create, idempotent only on exact match; drift
is refused. Never print or commit the output. Separate authorized review/apply
must install only that writer Secret, not root/reader credentials or broader IAM.

Rollout sequence (not executed by this source change):
1. Independent source/security review and live gates first. Keep evidence OFF.
   BEFORE any push, take a fresh consistent SQLite backup using SQLite backup
   API (not a raw copy of a WAL-active database), verify restore/integrity and
   record immutable byte counts/SHA256 checkpoints. SPI is auto-synced on push.
2. Review measured inventory of pending/locked legacy jobs and ambiguous primary
   intents. Legacy-only locked continuations retain their original backend;
   resolve review states without resetting queues, leases or retry budgets.
3. Provision only the writer Secret offline, review its metadata privately, then
   separately authorize apply. Enable only SPI automation/app=spi-triage to
   RustFS namespace/app=rustfs TCP9000 AND-selector peers; no broad RBAC.
4. Before activation, independently prove live RustFS conditional create/race,
   immutable readback byte/SHA, and ambiguity reconciliation semantics. Offline
   tests do NOT claim those live semantics. Observe patient retries and independent
   storage/LLM budgets; allow their bounded retry windows, never force resets.
5. Activate new-job S3 selection only after consistent inventory and gates pass.
   Capture immutable per-artifact and manifest byte/SHA checkpoints before publish.
   Never use a dump fallback or overwrite a conflicting object.
6. Roll back new-job selection with `s3Evidence.enabled=false` and
   `s3Evidence.retainCredentials=true`, retaining Secret mount and exact network
   peers while S3-locked jobs continue. Do not remove credentials until measured
   inventory proves no S3 continuations need them.

Historical comments and the existing downloader remain available. Standalone
Retain storage is not HA, quota enforcement, or an independent backup. Original
workflow/credential IDs, PVC/encryption and calendar/Yandex/blog WRITE_ENABLED=false
are unchanged. No live RustFS conditional semantics have been tested by this phase.
