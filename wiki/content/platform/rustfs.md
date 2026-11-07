---
title: "RustFS evidence foundation"
weight: 30
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


## Natural S3 publication acceptance — COMPLETED (6 November 2026)

This supersedes the earlier pending-natural-publication gate, not historical
OFF/ON observations. Real completed job
`8670f2cafead0c31fcae610e583ecebc54b5e7124c11178ea320fe231e577f41`
has exactly one primary marker at
https://github.com/alchemmist/homelab/issues/38#issuecomment-6686850025 .
Canonical manifest:
https://spi-evidence.socrat.alchemmist.xyz/spi/v1/8670f2cafead0c31fcae610e583ecebc54b5e7124c11178ea320fe231e577f41/52689870254b295cdddb20312d84ade226c277082c9dea2fdcbf45b1c1d84479/manifest.json

Renderer correction `637118ed9f2f4bcd40f69088ff6f9733bdbf9efc` is deployed;
runtime evidence_bundle.py SHA256
`997b864cf45a2ee9edf412b7107b8c50d3f666f3714fd5538f77018d576fea81`,
backend `s3`, deployment Ready; Argo readback Synced/Healthy at
`20258f437238a0248625c9bcbc866dc7104e8635` before this docs-only commit.
The existing own App comment was repaired with one supported body-only PATCH,
exactly eight bucket-prefix removals, no new publication. Original body SHA256
`e817ade6f50bb21a0102aea2b80cab2347a1d0da693c6f29776446701f0136e8`;
repaired full-readback SHA256
`87dddbfada45fbb0d2ecf80fcd047d14bde8eae2eabe5a97ce2c261497c7a6c8`.
The earlier conditional PATCH returned400 (cause not established). GitHub does
not generally support conditional unsafe requests: correction used fresh exact
body/updated_at/fingerprint preflight and postreadback, no If-Match or
If-Unmodified-Since. This is NOT atomic CAS; a small concurrent-edit race remains.

Fresh deployed Reader GETs proved exact original ASCII bytes, size and SHA256
for manifest plus all7 artifacts against durable storage receipts; no PUT,
ensure_object or reupload. Manifest 9,417 bytes, SHA256
`52689870254b295cdddb20312d84ade226c277082c9dea2fdcbf45b1c1d84479`;
7 artifacts,5 missing entries,0 truncated artifacts. All8 canonical URLs tested
with verified TLS on BOTH109.173.40.247 and109.120.141.97 (64 requests): anonymous
HTML302 only to the fixed-origin auth start with exact return URI; API and forged
groups401/empty; obsolete bucket-prefixed HTML paths401/empty, not aliases.
Telegram desired/applied revision2/2 remains verified, attempts1, error null;
this is delivery acknowledgement, not proof of human viewing.

The previously authorized logical queue purge retained119 cancelled tombstones;
all119 IDs/intents/results still match the private pre-renderer backup. It was
not physical deletion or successful processing; active queue was not reset,
replayed or reselected. The runtime remains S3 ON. No baseline/45min observation
or infrastructure tests were rerun for this bounded correction.

Prior nativeOIDC human login and verified45-byte download are attributed earlier
evidence, not a new session test. Human logout/outsider-session tests were NOT
performed here. Console GetOnly is not upload/admin access. Standalone Retain is
not HA or an independent backup. No network/IAM/DNS/shared-edge/PVC/workflow,
calendar/blog, Telegram test, model invocation or other comment change occurred.
