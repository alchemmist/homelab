# RustFS SPI artifact migration — implementation contract

Status: authorized implementation, 5 November 2026; NOT deployed yet.

Goal: put bounded, redacted SPI evidence files into private RustFS S3 storage;
GitHub receives narrative and concise permanent authenticated file links, not
large evidence payload comments. Keep existing evidence comments until a separate
verified historical migration. Never silently fall back to comment dumps on S3 failure.

## Baseline and deployment safeguards

- Isolated worktree /tmp/homelab-rustfs-spi, fetched main be3a561.
- Existing n8n workflow identities, credentials and PVC/encryption key stay intact.
  Calendar unchanged, blog WRITE_ENABLED=false. No fake production incidents,
  test Telegram spam, automatic issue closure/repair or resetting queues/leases.
- All four cluster nodes Ready. socrat-0: about10Gi free memory, filesystem592Gi
  free on884Gi NVMe. Other nodes have much less available memory. Candidate:
  standalone RustFS on socrat-0, separate20Gi Retain local-path PVC, CPU/memory
  requests/limits. This is NOT HA or an independent backup; monitor real disk
  usage (local-path requested size is not an enforced filesystem quota).
- Pin a verified official release/image digest; inspect current RustFS support,
  security advisories, resource needs and IAM/health compatibility first.
- Root RustFS credentials only in dedicated precreated Kubernetes Secret. SPI
  receives only narrowly scoped bucket/prefix write/read credentials, never root.
  Download gateway receives read-only credentials. No secrets committed/logged.
- GitOps source via a new Argo application. No external S3 API or console exposure
  by default; protect eventual browser routes with existing Authentik access
  policy, valid TLS, no arbitrary forward headers or unconditional access.
- Foundation may be deployed before publication switch. Keep SPI S3 switch OFF
  until real bucket/credential, upload/download/hash and auth checks pass.

## Artifact contract

- Private bucket spi-evidence; immutable content-addressed prefix
  spi/v1/<64hex event_key>/<64hex manifest_sha256>/.
- Preserve the exact bounded ASCII JSON bytes produced by existing prepare_bundle;
  concat parts in order to reconstruct each artifact and manifest, then verify
  all existing SHA256 values before upload. Truncation/redaction/unreviewed data
  remain explicit. No widening evidence scope or limits as part of storage work.
- Deterministic names manifest.json and E001-<sanitized-name>, etc. Validate keys,
  event/hash/id/name at publisher and gateway. Reject traversal, unsafe encodings,
  unexpected query parameters, redirects and arbitrary upstream URLs.
- Separate index file can list filenames, hashes and permanent download URLs;
  do not introduce a self-referential manifest hash.
- Proposed stable URL origin https://spi-evidence.socrat.alchemmist.xyz. Browser
  access requires Authentik authorization. No expiring presigned issue links,
  public bucket, credentials in URLs or anonymous contents/listing. Serve as
  attachment with correct MIME, nosniff, bounded reads, no browser-executable HTML.
- Use verified S3 SigV4/SDK. If using standard library, add deterministic signing
  test vectors, URI/query/header/UTF8 coverage and redirection safeguards.
- Same deterministic PUT may be reconciled/retried after ambiguous transport;
  existing bytes must match size+hash, never silently overwrite a mismatching key.
  Upload/checkpoint files before GitHub publishes links. Upload/retry never reruns
  model analysis or duplicates the primary GitHub publication. Temporary object
  storage failures should remain durable safe deferred work with backoff.
- Preserve current GitHub publication intent/marker reconciliation and explicit
  WRITE_NEEDS_REVIEW. Lock backend choice per publication; never reinterpret an
  ambiguous old comment intent or silently abandon in-flight legacy artifacts.
- S3 mode: primary narrative + compact file index/links only, no raw artifact
  comment parts. Old mode/jobs remain interpretable. Historical downloading and
  replay remain supported, with hashes checked independently.

## Gates before enabling writes to the new backend

1. Helm render, schema/policy and unit tests pass; source review resolves P0/P1.
2. Consistent SQLite backup verified before rollout; existing jobs preserved.
3. RustFS ready, Retain PV/PVC verified, no public bucket/console/API, no root
   credentials mounted into SPI/gateway. IAM negative tests: denied other prefix,
   reader PUT/delete denied, writer delete/admin denied.
4. Small isolated fixture upload/get/checksum (not an incident); transport retry
   and checksum mismatch tested offline. Gateway auth-negative/TLS/path tests and
   authenticated download produce identical bytes. Human login is not claimed
   without an actual session.
5. Enable only new publication flow; inspect one real queued incident naturally,
   exact primary URL and its file links, no new Telegram messages for testing.
6. Preserve prior files/comments and rollback switch. Record actual commit/revision,
   tests independently run, monitoring, backup/HA limitations and remaining work in
   runbook + LLM-wiki. Recurring backup is not claimed unless deployed and verified.

## Foundation source continuation (not activated)

The disabled foundation source now includes private IAM/Secret/Authentik
provisioning tools, protected read-only artifact gateway with SigV4/hash/security
tests, verified health routes, optional TLS browser routing and explicit rollback.
Read `docs/rustfs/foundation-review.md` for source evidence and
`docs/rustfs/activation-checklist.md` for actual phased runtime gates.
All committed activation switches remain OFF. Independent source review and real
runtime bucket/IAM/SSO/TLS/download tests are still required. No publisher switch
is implemented by this foundation change; foundation must be up and tested first.

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
