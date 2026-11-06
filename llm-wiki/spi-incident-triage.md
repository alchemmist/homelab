# Socrat SPI incident triage

Latest production acceptance: **4 November 2026**. Recorded acceptance evidence is
not a substitute for checking live queue state when investigating a new incident.


## Current Telegram SPI acceptance — 4 November 2026, 10:49 UTC

**ENABLED and verified on real original cards.** This supersedes historical
staging/push-blocker checkpoints below. RustFS was selected for the later S3
artifact-storage phase; nothing S3-related is deployed or migrated yet.

- Activation and LLM-wiki commits were pushed; original SPI workflow
  `J9akzlydrf9XZiID` and Socrat Alerts `b2TlucyOTiZP9CzN` remain active, IDs and
  credentials preserved. Runtime `SPI_TELEGRAM_LINKS_ENABLED=true` verified.
- Fixed a LIVE registration defect: an active custom n8n trigger without
  `webhookId` returned404 and accumulated a backlog. The trigger now retains
  stable webhookId `9c393df1-a66f-41bf-acaf-b2b66f31a393`; original graph was
  updated/reactivated in place. Authenticated callback returned202; real jobs
  progressed. Regression assertion is in test_event_workflow.py.
- Real episode `b5d05ddf28dd8eae8a2d1c5fde19a007bc34507b43c36ea6708d5e5c7a4e237b`:
  firing primary created https://github.com/alchemmist/homelab/issues/26;
  revision1 applied to2 expected original copies,2 acknowledged. It applied
  while artifact publication was still stage3, demonstrating separate delivery.
- Its ALREADY QUEUED real resolved observation published the exact primary
  recovery comment:
  https://github.com/alchemmist/homelab/issues/26#issuecomment-6628732862 .
  Revision2 applied to the SAME2 original copy IDs,2 acknowledged, no pending
  copies. Native rows both remain resolved, generation1, desired/applied
  revision2 and exactly ONE SPI anchor with that permalink.
- GitHub readback confirmed the exact resolved-event marker and immutable bot
  authorID351189559. Link is the narrative, not artifact/index comment.
- LIVE stale revision1/root request rejected409. LIVE idempotent revision2
  reassertion returned200 with both copies acknowledged and no pending copies.
  No test Telegram send, synthetic alert, fabricated incident or model bypass.
- Acceptance selected two already queued real jobs via temporary availability
  deferral of OTHER queued jobs, with maximum600s expiry. Active leases, event
  timestamps, creation times and attempts were not bypassed/reset. Normal
  exclusive claims selected targets; ALL holds restored immediately afterward.
- Prepared Grafana pending-link rule `spi-triage-telegram-links` provisioned201.
  Parent suites passed:114 Python,9 ingress JS,29 bot tests. No controlled
  production Telegram outage was injected; failure/restart cases remain covered
  by offline regressions, not a claim of a live outage drill.
- Three Argo applications were Synced/Healthy at revisionf4ad594 (descendant
  including trigger fix0304a6d). Native live schema0009 verified. Source bot
  commitfe67913 already deployed. Check current GitOps revision during incidents;
  concurrent unrelated changes advance main.

Private backups: pre-enable SQLite83jobs; accepted-final SQLite7,131,136bytes,
109jobs, verified SQLite header/integrity/foreign keys; schema9 pre-acceptance native PG dump
67,536bytes, pg_restore listing checked; active original workflow JSON snapshots.
Paths under `~/.config/n8n/diagnostics/spi-telegram/`; no private copy IDs/credentials
are published here. These are snapshots, not a recurring backup/restore drill.

**Remaining operational state, not a completed/drained queue claim:** final
snapshot66complete,2dry_run,1processing,38queued,2retry;2applied episode targets,
3pending. Historical unaddressable legacy episodes retain visible WAIT_RECEIPT;
do not invent immutable proof or attach their results to reused keys. Shared
inference429/backoff and accumulated backlog delay new results. External outages
and dead/inaccessible copies still require monitoring/operator intervention.
Blog remains write-disabled, Yandex/calendar unchanged, no issue auto-closure,
repair or suppression. Historical evidence comments remain until the separate
RustFS design/migration task is approved and implemented.


## Operator contract

**GitHub issue title, description and all generated comments MUST be English.**
Issue titles start with `[SPI]`. Workflow names/nodes/diagnostics are English.
The model must compare the new incident with all open SPI issues; closed issues
are not semantic candidates. Same root problem → comment; new problem → new issue.
Technical duplicate delivery is separate from LLM semantic matching.

Assess both service defects/impact and the quality of the alert itself: noise,
actionability, duplicate conditions, thresholds and pending/recovery behavior.
Self-resolution does not prove noise. Facts, hypotheses, confidence and missing
context must be explicit. Never fabricate root cause or automatically change rules.

## Source of truth

- Runbook: `docs/n8n/spi/setup.md`; workflow JSON alongside it.
- Code and pinned single-worker deployment: `charts/spi-triage/`.
- Sanitized authenticated native trigger: `charts/n8n/extensions/SocratAlert*`.
- Existing Socrat Alerts workflow is updated in place, not recreated.
- `scripts/n8n/sync_spi.py` refuses active workflow mutation.
- Secrets bootstrap: `scripts/n8n/provision_spi_secrets.py`; no values in git.
- Private mapping: `~/.config/n8n/spi-credentials.json`.
- Operator checklist: `/tmp/socrat-spi-implementation-plan.md` (local, not a secret).

GitHub App `socrat-steward` already has Issues:write and an installation on homelab.
Do not put its private key in the triage worker. Namespace-local broker issues
one-hour repo-scoped tokens every 20 minutes without PR write and patches only a named Secret.
Worker uses Viewer Grafana access and a separate capped LiteLLM qwen3.8-27b key.
Dedicated SQLite PVC is NOT the n8n database; never modify n8n SQLite for this feature.

## Workflow topology and responsibilities

| Workflow | Preserved instance ID | Responsibility |
| --- | --- | --- |
| Socrat Alerts | `b2TlucyOTiZP9CzN` | Authenticate, persist the group, deliver Telegram |
| SPI Incident Triage | `J9akzlydrf9XZiID` | Claim and analyze durable jobs, publish through the App |

```text
Socrat Alerts:
Alertmanager Webhook → One item per alert → Post Telegram Message

SPI Incident Triage:
Dispatch Webhook → Claim Triage Job → Select Claimed Job → Match Open SPI
             → Collect Evidence → Analyze Incident → Publish SPI
```

The native webhook performs the authenticated durable handoff before acknowledging
receipt. A handoff failure returns HTTP503 for sender retry but still lets Telegram
processing run. Do not put inference in the incoming webhook or make notification
delivery depend on a successful model response. Existing bot mute/resolved behavior
is separate from incident matching and must be preserved.

## Matching and event lifecycle

- Technical identity includes source, fingerprint (or labels), start time and
  firing/resolved status. Exact redelivery is not a new episode or a new model call.
- Fetch all open `[SPI]` issues, excluding PRs. Compare in batches through the model;
  closed issues are never semantic candidates. The current review cap is 120 open
  SPI: exceeding it fails visibly rather than silently dropping candidates.
- Evidence-based analysis revalidates the initial match. A changed open-issue
  snapshot before publication restarts matching instead of writing from stale state.
- A new episode can comment on the same open SPI. `resolved` updates the known open
  issue without closing it. An orphan resolution must not create an issue or reopen
  a closed one. Human-authored historical titles are not automatically translated.
- Store write intent before POST. Reconcile a lost response using the event marker;
  closed issues may be read ONLY for technical reconciliation of a prior write.
  `WRITE_NEEDS_REVIEW` requires inspection, not a blind retry or deletion of state.

## Runtime budgets and first-response checks

- Dedicated model: `qwen3.8-27b`; 3 RPM, 30k TPM, one parallel request. Client calls
  are paced at least 21 seconds apart. Do not reuse the blog/reviewer key to bypass limits.
- Inference timeout: up to 600 seconds per call, within a 780-second stage budget.
  Stage HTTP nodes allow 900 seconds; the workflow timeout is 3600 seconds.
- Model schema/output validation retries once; job failures back off, with eight
  claims exhausting the retry budget. Shared inference can still cause a backlog.
- Metric prompts use observed extrema, first/last values and counts, preserving
  queries/windows. Absent series and zero errors do not prove a healthy service.
- Queue state lives in the worker PVC `/data/spi.sqlite`, not n8n SQLite. Single
  replica/Recreate and transactional claims are required. Startup releases interrupted
  claims and resumes saved stages. Never scale this design as an uncoordinated swarm.

Grafana folder **Automation**, group **SPI triage**, receiver **SPI triage via Socrat Alerts**:

| UID | Signal |
| --- | --- |
| `spi-triage-failures` | Final stage or authenticated handoff failures |
| `spi-triage-heartbeat` | No worker queue-health heartbeat for ten minutes |
| `spi-triage-dead` | Jobs require operator review |
| `spi-triage-stale` | Pending work older than 45 minutes |

On trouble, distinguish an unavailable worker, dispatch reservation/lease delays, model latency,
read-only evidence gaps and GitHub authorization/write ambiguity. Inspect sanitized
codes and saved stage before intervening. Check current App-token refresh separately
from inference health. Do not suppress alerts automatically or erase pending jobs
to obtain a green dashboard. Telegram delivery is independent of the model but still
depends on n8n; a full n8n outage can delay delivery while Grafana displays the alert.

## Historical deployment and acceptance status (before event-driven migration)

SPI publication is **enabled after live dry-run** (SPI writeEnabled=true).
Blog WRITE_ENABLED remains false. Do not transfer one worker's rollout policy to
another. Historical dry-run reports are not replayed or posted as test issues.

98 local tests pass: 65 SPI Python + five ingress + nine Yandex + six calendar +
thirteen blog. Live authenticated ingress/Telegram execution 1927, full real-alert
dry-run execution 1976, HTTP401 rejection, scheduled App-token refresh, duplicate
suppression and worker restart recovery verified. Both workflows are active and
rendered parameters/connections match live. Four Grafana SPI rules evaluated healthy.
Known secrets were absent from ingress execution data; consistent SPI off-node
backup integrity checked. First real issue: [SPI #9](https://github.com/alchemmist/homelab/issues/9),
authored by socrat-steward[bot], English title/body and marker verified. Post-publication
queue state has a verified off-node copy. A natural subsequent incident was matched
to #9 by the model and appended as English comment `6608101252`, verifying both
publication paths live. See the runbook for exact IDs.

Do not bypass the ingress auth rollout. Legacy migration mode permits Telegram
only; unauthenticated requests must never enqueue SPI. Queue failure returns 503
for sender retry while still allowing Telegram. Headers never enter execution data.

## Evidence v2 (3 November 2026)

The former raw-log/discovery/provenance gaps are now covered by bounded collectors.
Full operational contract: `docs/n8n/spi/setup.md`, Evidence v2 section.

- Text artifacts live directly in issue comments: MANIFEST, alert/rules, preserved
  metric samples, scoped error/stack/context logs, discovered traces and deployment
  metadata. No binary upload, extra GitHub permission or evidence branch.
- Grafana Explore links have exact absolute times, datasource and query. Stored
  samples survive datasource retention; empty reads and clipping are explicit.
- Tempo IDs come from logs or service/time search. Bounded spans include exception
  events, parent IDs and resource service/version context when available.
- Kubernetes read-only projection includes owner chain, current/prior termination,
  image IDs and retained events, never env or Secrets. Job pods are verified before
  treating them as log targets. Exporter labels are not affected workload identity.
- Digest-addressed OCI metadata and supported immutable GitOps release mappings
  provide source/version references. Socrat bot mapping was verified live. Matching
  stack paths can yield numbered code excerpts pinned to that exact revision.
  Collection-time deployment is not proof of incident-time version or binary/source
  reproducibility. Unsupported repositories and host versions remain explicit gaps.
- Artifacts: 90k characters each / 360k total plus manifest, 40k/comment part;
  redaction and SHA-256 are recorded. Model excerpts are bounded to 24k characters;
  all verified facts must cite existing evidence IDs. No claim that every byte was read.
- Saved pending markers protect each publication step across restarts. Match bot
  identity by immutable App ID 5569869, not a renameable login. Never blindly retry
  an ambiguous POST or discard intent merely to make the job succeed.

Real evidence supplement and roundtrip verification:
[issue #9 artifact index](https://github.com/alchemmist/homelab/issues/9#issuecomment-6610936449).
Nine artifact parts reconstructed into eight verified files. A fresh-state replay
performed no additional writes. Downloader: `scripts/n8n/download_spi_evidence.py`.
The source mapping and pod/event read probes were separate read-only validations,
not invented incidents. Raw log/trace searches for this episode were empty, not health.

No automatic remediation, suppression, issue closure, historic dry-run replay or
credential publication. Retain/keep and one-off snapshots are not recurring backups.

### Startup hardening checkpoint

Larger queue recovery exposed SQLITE_IOERR_GETTEMPPATH (6410), not corruption:
read-only root prevented a SQLite statement spill temporary file. Exact recovery
was reproduced, then fixed by per-connection temp_store=MEMORY plus bounded /tmp
memory emptyDir. Keep root read-only; do not reset the queue. Worker healthy,
native write/integrity verified and at least 50 jobs preserved in final off-node
backup. Emergency Argo skip and storage probe removed; scheduler active. Failure
lookback/backlog alerts can remain active after recovery. Bot user ID351189559 is
the immutable fallback for issue responses that omit App metadata.

### Grafana deep-link correction

Anonymous dashboard access is not Explore access. Without `forceLogin=true`,
Grafana 13.2.4 redirects `/explore` to its default home dashboard (Last 3 hours).
SPI links now use the native login return flow, preserve absolute pane ranges and
queries, and require an existing identity with Explore permission (Editor/Admin).
Anonymous and existing user permissions are unchanged. Cached rendered indexes
are repaired without mutating checksummed artifacts. All eight real issue9 links
were checked in a browser against their actual time picker and query editor.
See the runbook for the read-only Playwright regression and its private state.

The operator rejected multi-comment artifact storage as noisy. S3 product choice,
deployment and migration are the next separate step; do not claim S3 is deployed
or delete the retained comments before a verified migration.

## Historical event-driven staging checklist (superseded by current acceptance)

No n8n Schedule Trigger or every-minute execution is used. Authenticated `/enqueue`
and `/enqueue-group` commit jobs to the existing SQLite queue before signaling a
background dispatcher. Native ingress already owns durable handoff, so an
execute-subworkflow node is not required. No Redis/Postgres queue migration.

`SPI_DISPATCH_ENABLED` defaults false. When enabled, the worker coalesces wakes and
POSTs `{}` only to the fixed internal endpoint
`http://n8n.automation.svc.cluster.local/webhook/spi-incident-triage-dispatch`, with
`X-Worker-Token` from existing `WORKER_TOKEN`. The native Webhook uses `headerAuth`
with the same `SPI_WORKER_CREDENTIAL_ID` / `httpHeaderAuth` mapping as `/claim`,
and immediate `onReceived`. No alert-supplied callback URL is allowed.

One execution claims one job; match/collect/analyze/publish stay unchanged. Enqueue,
stage completion and failure signal dispatch. Only due work with no active processing
lease starts. Durable reservation/backoff handles ambiguous responses, slow/missing
n8n and claim callback races; `/claim` acknowledges the reservation. Startup recovery
and an internal worker timer for retry/lease/reservation deadlines recover lost wakes.
Empty queues generate no n8n executions. Never hold a SQLite transaction or dispatcher
lock during network/model calls. This does not promise exactly-once or model success.

- [ ] Parent deploys disabled, preserves original workflow IDs, credentials, n8n
  encryption key/PVC, worker SQLite and Telegram path, then activates event workflow.
- [ ] Parent enables dispatcher only after activation and verifies empty-queue
  silence, coalescing, due retries, lost-wake recovery and exclusive job leases.
- [ ] Parent verifies unavailable/slow n8n and callback races without publishing test
  incidents or sending Telegram tests. Migration deployment/acceptance remain pending.

For backlog, inspect due time, saved stage, active processing lease, reservation
expiry and worker health before intervening. An accepted webhook is not completed
analysis. Do not clear queue state or bypass leases; reconcile ambiguous GitHub
writes rather than blindly retrying. Disabling dispatch does not cancel in-flight
executions. Keep the independent blog dry-run and existing artifact limitations:
text artifacts are in issue comments; S3 is not deployed and is separate work.

Security integration: dispatch uses CUSTOM.socratSpiDispatchWebhook with the
existing httpHeaderAuth credential, not the built-in Webhook (which emits incoming
authentication headers). Only `{dispatch:true}` enters execution data. Credential
comparison occurs in the trigger; POST acknowledgement is immediate. Worker egress
is restricted to automation/app=n8n pod TCP5678 for the fixed callback.

### Telegram link implementation contract

Human API contract: `wiki/content/platform/socrat-bot.md`. Primary GitHub receipt
and desired target commit atomically. New issue -> its root URL; match -> exact
new narrative comment URL, never artifact/index or last comment guessed by order.
Independent persistent link outbox uses native `/v1/cards/links`, labelSPI,
expected copy IDs and monotonic revision. Acknowledgements cover all copies;
partialHTTP200 and ambiguous transport retry without model/GitHub publication.
Native desired revision is committed before network editing, separately from
applied copy revision. Immutable episode keys preserve flaps/history; resolved
status cannot regress on delayed duplicate firing. Lost receipt callbacks recover
through native episode lookup; pre-migration primary URLs recover by trusted
marker only. Discovery has independent thread/backoff and cannot stall delivery.
Six-hour desired-state reassertion addresses eventual ambiguous-write convergence.

Activation is now verified above. Preserve native one-process/Recreate assumption,
Bot schema0009 and existing n8n IDs/credentials/PVC. Legacy unaddressable messages
or deleted Telegram copies are not fabricated successes. See runbook for explicit
limits and pending-link monitoring. S3 remains a separate unimplemented step.


### Historical pre-activation checkpoint — 2026-11-04 09:52 UTC

This status supersedes the historical staging checklists above; unchecked
acceptance scenarios must not be inferred complete from deployment alone.
Event-driven SPI dispatch is deployed and enabled. Original SPI workflow
`J9akzlydrf9XZiID` remains active without a Schedule Trigger; original Socrat Alerts
`b2TlucyOTiZP9CzN` remains active. Preserve original credentials, owner/project,
encryption key, PVC and durable queue. Blog remains `WRITE_ENABLED=false`.

Telegram link implementation is complete in source, but production acceptance is
NOT complete. Latest verified deployed homelab revision is
`cac95988ee3b757d7fdc526e67e2dc1b5e2233e8`; n8n, SPI triage and native bot Argo
applications were Synced/Healthy. Runtime `SPI_TELEGRAM_LINKS_ENABLED=false`.
Activation-only commit `49ad7451956a49c5056840f0950ee19cab776512` exists locally;
GitHub rejected its pushes with Internal Server Error / fatal error in commit_refs.
REST ref verification confirmed it was not published. Do not assume the local
chart value means the running feature is enabled. No imperative activation bypass
was applied; recheck remote main and runtime before continuing.

Resolved review findings: no fabricated closed-issue root target; delayed firing
cannot regress resolved native cards; discovery failures do not block delivery;
native desired revision/URL commit before Telegram edits (schema0009), separate
from applied revisions. Historical backfill compares deterministic candidate
revision against desired revision, so a transient resolved-reference failure can
recover firing first and later supersede it with the exact resolved comment.
A resolved job without a publication never manufactures a target.

Actual n8n HTTP expression evaluation failed despite earlier static tests. Fixed
by `Prepare Telegram Receipt` Code using linked `itemMatching(index)`, followed by
simple HTTP JSON serialization. Callback-only acceptance replayed four retained
REAL bot responses: each recorded two observed copies, with native episode equality
verified and four immutable receipts persisted. Temporary acceptance workflows
were removed. This sent no Telegram messages, ran no model and published no
GitHub content. It is NOT proof of the final SPI link edit.

Parent-executed suites: 114 SPI Python, nine ingress JS and 29 native bot tests
passed. Source review is not independent test execution. Consistent pre-enable
snapshot: `~/.config/n8n/diagnostics/spi-telegram/pre-enable.sqlite`, 5,918,720 bytes,
83 jobs; SQLite header, integrity and foreign keys checked. An earlier empty
capture during rollout was invalid and was replaced; never accept integrity_check
alone on an empty newly created database as backup proof.

Remaining acceptance:
1. After GitHub write recovery, fetch/rebase/push activation; verify deployed
   revision and actual runtime flag, not only successful Git push.
2. Confirm exact primary target in all original copies of a real immutable card,
   native updated/pending acknowledgement, and durable independent retry state.
3. Provision prepared `spi-triage-telegram-links` pending-backlog Grafana rule.
4. Record final queue snapshot and update acceptance docs with actual evidence.

Scope excludes historical replaced legacy messages without trustworthy episode
proof. Deleted/inaccessible copies and unavailable external dependencies require
visible pending/error state and operator attention, not unconditional success or
exactly-once claims. Native API service port8080 targets hostNetwork port8082;
worker NetworkPolicy must allow the actual target. S3 remains unimplemented.

## Patient LLM retries — 4 November 2026

SPI source now separates durable LLM deferrals from bounded failure handling.
Explicit typed `LLM_*` transient429/timeouts/network/selected5xx and budget/JSON
failures do not become dead after8 claims. Worker releases lease and records due
time with jitter/backoff (normal cap1h), bounded Retry-After hints up to24h. Total
claims remain diagnostic; independent `job_failure_budget` counts ONLY capped
failures. After20 busy-LLM deferrals, a first ambiguous GitHub timeout still gets
its reconciliation allowance. WRITE_NEEDS_REVIEW remains immediately terminal;
no namespace-wide or blind GitHub POST exemption. Existing dead jobs are NOT
silently reopened; readback before rollout found none.

Matching checkpoints each completed batch in job.result, resumes only identical
full snapshot digest, and revalidates cached schema/membership. Changed snapshots
invalidate cache. Busy work logs stage_deferred warning. Repeated snapshot churn
or permanent failures can still require intervention: never promise unconditional
completion, never relax evidence validation or repeat ambiguous publication.
Read runbook “Patient LLM client retries” for limits and legacy-counter semantics.
This is SPI-only, not completion of an all-client retry audit.

Retry rollout verification: commit2e363e6 deployed Synced/Healthy; runtime explicit
LLM classification and independent failure-budget table verified. Links remained
enabled; real dispatch202 resumed retained work.122 Python +9JS tests passed,
including20 deferred LLM failures then ambiguous publication and successful
reconciliation with ONLY ONE GitHub POST, plus independent8-failure cap and
checkpoint/snapshot invalidation. These failures were simulated OFFLINE, not
injected into production. Consistent before/after SQLite snapshots checked;
all119 pre-rollout job IDs and original creation times retained. No pre-existing
dead jobs required rescue; no terminal state was silently reopened.

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

## SPI S3 activation — 6 November 2026 (natural publication pending)

Supersedes earlier OFF/not-deployed statements for SPI only. Approved source
`7e1cd0a9ccccdb8322815a1d8b20bdd9060f502b` passed rereview; OFF/live readiness
at `e7a23613ce3e5c62ed1635f27068109991724f2e` passed. Authorized minimal ON
activation is `af9cbcdac8bd03a2ce2b0155b23193e8bad33938`, changing only
`charts/spi-triage/values-off-live.yaml` enabled=true and explanatory comments.
Both SPI and RustFS were Synced/Healthy there; actual worker loaded backend=s3,
S3Evidence, with client SHA256
`97604f85646d55ba1f36c384be4034becc786608a3ee39663a42d8e6b2d72c5c`.
No image rebuild; ConfigMap source is unchanged from accepted OFF deployment.
Fresh SQLite backup API checkpoint before activation: 23,404,544 bytes, SHA256
`fa338ee2369fd5b021f8cc5de0d2f40c2109ed743f69a5862e236c97e0a65acb`;
independent integrity/FK checks passed. A subsequent consistent snapshot passed
those checks too (SHA256
`81a4741781b58c38d81e5a51e505c20d85d35daf7cdc0b15c2fbabd398608a27`).
Private checkpoints remain under ~/.config/homelab/spi-final-acceptance/.

Bounded natural observation 12:39:14–12:42:15Z found **no S3-selected job**.
Queue remained 100 queued, 11 retry, 1 processing, 170 complete, 5 dead,
2 dry_run. No real S3 GitHub narrative/manifest/artifact link can yet be cited;
Reader byte/hash/truncation/missing proof for a real publication is **pending**.
Do not interpret ON/Healthy or prior benign storage fixtures as end-to-end proof.
No forced claim/reselection, lease/budget reset, dead revival, synthetic alert,
model call, GitHub test write or Telegram replay was used.

289/289 original IDs/creation timestamps survive. All 177 original terminal
states/results/intents are unchanged; one complete row naturally gained a
redelivery timestamp/count. All 145 original effective legacy locks retain their
results/intents (144 rows wholly unchanged). Legacy-only original continuation
markers must remain as-is; they are not migrated by ON. Independent Telegram
outbox remains 73 rows: 66 applied, 7 pending; URL/event/revision/state and
acknowledgement unchanged, two pending rows advanced ordinary retry timing/count.
393 Telegram receipts and 212 receipt events are byte-for-byte row-equivalent;
no replay or outage injection. Exact-primary semantics are independent of S3.

Tests: prior source rereview 151 SPI + 5 chart/helper + 29 RustFS passed;
activation reran 5 chart/helper tests and both chart lints successfully. Prior
OFF actual conditional 412/race/ambiguity/IAM denial gates remain accepted.
Existing nativeOIDC human/download45B hash evidence remains accepted, not
re-enacted; console GetOnly unchanged. No new human logout/outsider claim.
A real-publication anonymous/forged-auth read and scoped Reader verification
must still be recorded when a natural eligible job actually publishes.

Backend-preserving rollback: set only enabled=false in the same live overlay;
retain retainCredentials=true, dedicated writer Secret/mount and exact network
grants while any S3-locked continuation exists. Fetch/rebase before scoped HTTPS
push; never erase historical comments/files or reset job state. Standalone Retain
storage is not HA, enforced quota or independent backup. Four Ready nodes were
observed in the existing context, not seven; no topology change or seven-node
verification is claimed. No n8n identities/workflows/credentials/PVC/encryption,
calendar/Yandex/blog WRITE_ENABLED, NetBird/Mac/VPN/DNS/shared edge, human IAM or
RBAC changes were made by activation. Final acceptance report:
`/tmp/spi-s3-final-live-acceptance.md` (PENDING until real publication proof).


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

## SPI token admission — 6 November 2026

See [bounded accounting, checkpoint migration and rollout gates](../docs/n8n/spi/token-admission.md).
The implementation replaces instance-local RPM sleeps with shared durable
3 RPM / 30000 TPM / parallel1 reservations, adaptive <=12 batches, labeled
matching excerpts and restart-safe reviews/final comparisons. The corrected
qwen-byte-bound-v1 method counts NFC actual message bytes (not HTTP escaping),
schema bytes, validated 256-byte template bound and completion reserve. Deployed
Qwen revision 91bd022d5b49442a868bc35008f6c21e1860edfa has NFC/ByteLevel BPE;
its text-only thinking-disabled template adds 99 bytes. Authenticated LiteLLM
1.105.1 token_counter reports openai_tokenizer for this alias and is deliberately
NOT treated as exact Qwen usage. No runtime dependency or count cache is added.
Analysis prefers full context, then preliminary report excerpts, then explicit
1200/600/300-byte scalar excerpts preserving identities/references/missing data.
Seven read-only historic captured analyze requests all fit: reserved 20075–29228,
actual offline Qwen prompt+completion 7866–11780. No inference or queue transitions
were used. This is source-only feasibility, not model-quality/deployed acceptance
or a global client audit. Existing full Store/RustFS evidence remains unchanged.
Rollback retains the same ledger/checkpoints; v2 must never be reinterpreted as
fixed-12 progress. Revalidate model/template mapping before alias changes.

Authorized live rollout: reviewed commits rebased to bd41901 + **48b8161**,
normal SPI-only Argo Recreate at15:52:51Z, Synced/Healthy. Runtime methods,
shared Store injection and hashes verified against actual ConfigMap/normalized
source. Pinned Python base, replica/container spec and original PVC unchanged.
Fresh pre-push backup passed header/integrity/FK; all315 original IDs/created
and119cancelled whole rows preserved. No queue/lease/budget mutation.

**Live acceptance PENDING.** Bounded natural observation15:53:58–16:38:59Z:
33 adaptive batch reviews/346 candidate reviews, seven v2 jobs, four stage2
(match+collect) advances, zero new reports/primary publications/completions.
207 same-signature prefix comparisons passed.35 fresh typed admission waits,
zero fresh429/oversize/length/checkpoint errors. Historical retained jobs.error
is not a fresh429. Actual usage is not separately persisted; sampled integer
ledger charges9739–29972 obeyed3RPM/30000TPM/parallel1, not exact usage claims.
Stage2 requests fit28332–28931 but older due matching jobs won created,id claim
order with near-full ledger holds; observed head-of-line delay, not demonstrated
infinite small-request starvation. No unreviewed accounting/fairness fix deployed.

Exact requested episodes83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700
(uptake-kuma resolved17:21MSK; firing305b227cdc96…/resolved8c6af704b3fd…),
b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c
(SocratContainerRestartsFrequent17:28;08ba1f0938dd…), and
b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31
(stale17:45;998bcead1720…) remain queued0/attempt0, no primary/outbox yet.
Native two-copy/event receipts exist, but exact GitHub narrative, canonical file
URLs/ReaderSHA and appliedTelegram2/2 are pending. #38 is not a substitute.
Stale alert remains unmodified; observation has stopped, not ongoing.
169SPI+5chart/helper+9JS tests and Helm lint/template passed. See runbook for
remaining natural admission→analysis→publication→exact acknowledgement gate.

### Completion-aware scheduling correction — source-only

The scoped correction prefers eligible stage3 writes, stage2 analysis, stage1
collection, then stage0 matching; ties retain natural created/id ordering.
Claim and dispatcher share effective eligibility/next-wake calculation. Only a
live stage2 retry with `LLM_ADMISSION_DEFERRED` and a matching known ledger
expiry may hold stage0 until its existing jittered due time (expiry to due at
most4s; failure to due at most664s). Expired ledger data cannot extend this
bound. Active requests are not preempted; safe writes/collection and independent
Telegram deliveries are not held. Unknown429/hour backoff, terminal jobs and
out-of-bound/stale deadlines do not freeze healthy new matching. Pending-age
alerts retain original semantics; no durable job deadlines/checkpoints change.

Normal admission remains 3 RPM/30000 TPM/parallel1 with qwen-byte-bound-v1,
256 framing and conservative61s completion retention. Abandoned active ledger
entries use normal expiry, including after restart. This is completion
preference, not a global starvation guarantee under infinite later-stage work.
Stable snapshots, valid analysis and successful publication remain prerequisites;
synthetic tests do not accept the user's three live cards. No paid calls, queue
changes, deployment or endpoint probes are part of this correction. See
`docs/n8n/spi/token-admission.md` for bounds and runbook. Rollback only this
scheduler delta on the v2-capable runtime; never reinterpret v2 checkpoints with
a fixed-12 matcher. Later rollout requires review, fresh backup and fetch/rebase.


## Completion-aware live rollout — 2026-11-06 (bounded, blocked acceptance)

Reviewed scheduler `3309f505` deployed through ordinary SPI autoSync/Recreate;
normalized ConfigMap matches source, pinned image/PVC/container specification
unchanged, GitOps Healthy. Shared priority is write > analyze > collect > match;
only proven local stage2 admission retry holds stage0, bounded664s, expiry
proximity4s. Independent Telegram delivery and 3RPM/30000TPM/parallel1 remain.
The pre-rollout active reservation expired naturally at17:05:18Z; restart quiet
period was conservative crash recovery, not provider429 or scheduler starvation.

Finished natural observation16:54:48–17:39:48Z. One genuine end-to-end report:
https://github.com/alchemmist/homelab/issues/72#issuecomment-6690743660
(job20e7; **not** any requested card). All13 permanent canonical manifest/artifact
links checked in actual GitHub body; scoped Reader matched exact original bytes,
sizes and SHA against stored verified receipts. Telegram revision1 applied the
exact primary with verified expected2/observed2. This is publication proof,
not merely batch counts. Reservations are not exact provider token usage.

All four prepared jobs a16a/c93b/fa45/a92e naturally obtained analysis and reached
stage3 with reports, then publication's mandatory global open-snapshot fence
returned OPEN_SPI_CHANGED, resetting to stage0 and deleting all6 cached reviews
of61 candidates each. First successful publication changed the open snapshot;
this is a real throughput/cache-invalidation limitation, not generic queue wait.
The four exact requested event jobs305b/8c6a/08ba/998b remained queued stage0,
attempt0, with no primary; requested three cards remain unaccepted. One publish
INVALID_UPSTREAM_JSON was a finite upstream JSON parse failure, not invalid model
output; endpoint/status/content-type are not retained, so exact source unknown.

No live fix or weakened fence. Source follow-up should retain validated progress
at reset, reuse only exact candidate-ID/content + event/prompt-contract-bound
unchanged batch proofs on a refreshed snapshot, invalidate changed/new/closed
batches and final selection, and check signature cheaply before expensive analysis.
Preserve primary-intent/S3 reconciliation and post-upload publication fences.
This is a proposal requiring independent review, not deployed behavior.

Fresh SQLite API backup before push passed header/integrity/FK/SHA checks.
All316 original IDs/creation times and terminal results/intents preserved;
119 cancelled whole rows identical. One old completed job received a natural
duplicate delivery (only updated/deliveries changed). Outbox68->69 applied,
7 pending unchanged. No forced claims/reset/revival/probe or unrelated changes.
Observation ended; no ongoing monitoring promised. Rollback remains v2-capable.

## Local implementation: snapshot review reuse (not deployed)

Safe open-snapshot churn now retains the publication backend and matching proofs.
New proofs are explicitly v3 and bind the immutable event digest, actual matching
payload (including model/system/schema), excerpt policy, original full snapshot
and exact batch identities/content digests. The original snapshot/proofs are
validated before transferring only unchanged whole batches. Inserts/deletes/order
changes do not regroup proven batches; uncovered current candidates are reviewed
in adaptive batches of at most 12, with the existing 120-candidate ceiling.
Pairwise selection is invalidated on any full-signature change; same-signature
selection resumes from validated nominee-bound comparison history.

`match_progress_v3` is separate from old progress. Its checkpoint is also stored
transactionally in additive SQLite `match_review_v3`, so an older worker resetting
`jobs.result` cannot erase or reinterpret v3 proofs. Old v1/v2 caches have no
explicit event/prompt/model provenance; this implementation conservatively
re-reviews them rather than manufacturing a binding, even on an equal signature.
No backup caches are restored to jobs. Unknown contract changes re-review.

Before analysis, `GitHub.open_signature()` uses exactly `issues()` (the full
snapshot's universe/filter/order), without fetching comments. A stale snapshot
consumes no analysis call and invalidates safely. Existing pre-primary and
post-upload full fences and intent-first reconciliation remain mandatory.
Legacy artifact checkpoints or ambiguous primary intents are never cleared.
After an S3 upload, safe invalidation moves original evidence and exact storage
binding/verified receipts into `snapshot_audit`; new collection gets a fresh
active binding, never the previous bundle's receipts. Immutable objects are not
rewritten or adopted as new evidence. Public Reader URLs remain `/` + object key.

Only `OPEN_SPI_CHANGED` after a safe stage-zero reset with no intent receives
15–20 second jittered patient retries. Attempts and existing finite failure
budgets are not reset. Unsafe intents, unknown HTTP/JSON/auth/evidence errors and
`WRITE_NEEDS_REVIEW` retain finite/visible handling; LLM admission, claims,
callback scheduling, exclusive leases and token/parallel limits are unchanged.

This is source-only readiness, not live acceptance. The observed 24 reviews/244
candidate checks lost across four jobs are proven; which live candidate contents
changed is unknown (the prior probe timed out). Fake tests cover four prepared
61-issue/six-batch jobs, exact batch reuse, mutations/closures, early fencing,
20 safe deferrals, rollback retention, selection restart, post-upload audit,
and eventual exact-primary publication with two-recipient applied outbox.
The three requested live cards remain unaccepted; no new deployment, inference,
queue mutation, backup restoration or observation window accompanies this change.

### Durable late-snapshot replacement bound

A job has exactly three expensive snapshot generations: the initial generation
and at most two replacements. A stale post-analysis/pre-upload or post-upload
snapshot spends one replacement in the same SQLite transaction as the safe
stage-zero reset and audit retention. The third late invalidation does not reset:
it terminates as `dead` / `WRITE_NEEDS_REVIEW`, preserving the current report,
evidence, backend, active storage binding, verified receipts and previous audit.
There is no fourth generation. At most two historical full bundles plus the
current bundle exist in this job's logical trace; existing overbound/unknown
traces are retained and fail closed, never truncated. Candidate inputs remain
bounded by 120 candidates and twelve per matching batch, unchanged.

The additive `snapshot_budget` ledger is authoritative across restarts/reclaims
and jobs.result replacement. It keeps a bounded independent retained copy of the
current result (including the same at-most-two historical bundles), not another
append-only history. Replacing result with an old marker-less reset causes
operator review before any model/upload; operators must inspect both the job and
ledger retained JSON, not discard the ledger or reset counters to resume work.
Do not manually select replacement jobs, cancel queue entries, or clear receipts.
Stage-zero repeated invalidation does not spend twice. Transaction rollback
cannot commit the budget without the reset or vice versa.

Cheap pre-analysis signature fences may remain patient with zero analysis calls;
this is not permission for infinite new analysis or S3 generations. Primary intent
reconciliation remains ahead of freshness fences; ambiguous/unsafe writes remain
finite and are not reclassified as patient. Both full publication freshness fences
remain. Existing failure counts, 3 RPM / 30000 TPM / parallel-one admission,
Root-plus-key Reader URLs and Telegram delivery semantics are unchanged. This is
source assurance only, not acceptance of the three real user cards or rollout
authorization.


## Snapshot-review reuse rollout — 6 November 2026

Reviewed source `f6f8f101` + `0d27df3`, rebased release `ac6efc01`, deployed through ordinary SPI autoSync/Recreate. Live normalized ConfigMap matched all source files; pinned Python image, container/volume/PVC spec, provider/accounting and 3 RPM / 30000 TPM / one parallel unchanged. Additive `match_review_v3` and `snapshot_budget` tables exist. Legacy reviews deliberately require one fresh v3 review; never restore caches from backups. Late generations remain initial plus two replacements; retain independent proofs/budget on rollback.

Live acceptance is **BLOCKED, not complete**. Bounded observer sampled 18:08:38–18:36:23Z (28 consistent snapshots), then stopped when fresh matching `INVALID_MATCH_PROGRESS` occurred at 18:35:22Z on `a16a0dfcf743…`. One durable v3 batch (12 IDs, original snapshot61) had been saved. Its snapshot/content digests validate; a separate read-only native matcher replay with a fresh62-unique-candidate snapshot reached the deliberately disabled model-call boundary without error. The original failing current snapshot is not persisted: exact cause and cross-snapshot live reuse remain unproved, not established cache corruption. No automatic source repair, cache reset, rollback or queue mutation was performed. Finite failure count for that job was3 (baseline2). Natural worker activity continues independently; this acceptance observer has ended.

Another natural job `45b8168e0cf2…` completed stage4 after a publication-stage `UPSTREAM_NETWORK_ERROR` at18:23:25Z (finite count1, sampled retry had no primary intent), with normal `publication_ok` at18:33:13Z. This is not model-output failure or proof for the requested cards. No endpoint diagnosis or infrastructure repair was attempted. Reserved tokens are not exact provider usage.

Exact requested episodes remain unaccepted, all original jobs queued/stage0/attempt0 at final consistent capture: resolved KubeDeploymentReplicasMismatch episode `83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700` (firing `305b227cdc96…`, resolved `8c6af704b3fd…`); firing SocratContainerRestartsFrequent episode `b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c` (`08ba1f0938dd…`); stale SPI episode `b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31` (`998bcead1720…`). None has an accepted primary/Reader/applied two-copy Telegram proof. Older #72 evidence must not substitute for them. All318 baseline IDs/creation times,119 cancelled whole rows and original terminal results/intents were preserved. No ongoing observation or eventual completion is promised.


## Source-only snapshot consistency correction (2026-11-06)

Live acceptance remains BLOCKED: the three requested cards are unaccepted. The
18:35:22 INVALID_MATCH_PROGRESS historical current input was not retained. The
saved a16a v3 proof and later 62-unique replay were valid; durable corruption is
not established. The unrelated 18:33 publication is not acceptance evidence.

A fake transport reproduces a precise *possible* cause against clean 72ebc5e:
61 created-desc issues, append a new issue after page1/per_page20, then continue
offset pagination: 62 rows but only61 unique identities. The actual baseline
matcher raises INVALID_MATCH_PROGRESS before checking the valid old proof and
before inference. This proves a source defect, **not** the historical cause.

The local correction requests created-ascending pages, canonicalizes by issue
number, rejects duplicates (never dedupes), and reads the same filtered open SPI
universe again around comment collection. Any full metadata change or duplicate
is GITHUB_SNAPSHOT_UNSTABLE: one acquisition attempt, patient15–18s deferral,
zero model calls, no finite failure charge, retained v3 proof/budget. Cheap
open_signature uses the same issues/filter/order and two metadata reads, no
comments. Each issues pass retains the existing100-page bound; candidate ceiling
remains120. Unsupported identities/schema, malformed HTTP/JSON/network errors
and genuine bad durable proofs remain finite. No loop or conditional GitHub PATCH
was added. Consecutive equal reads are an observational consistency fence, not a
transactional GitHub snapshot; changes after the last read remain guarded by the
existing pre-analysis/pre-primary/post-upload fences.

Matcher rejections now emit sanitized diagnostic JSON with fixed reason enums,
count/uniqueCount/identity digest only. CURRENT_INVALID_ID and CURRENT_DUPLICATE
are separate from ORIGINAL_SIGNATURE, BATCH_DIGEST, OVERLAP, DECISION, SELECTION.
No event/issue/comment body, raw identity, credential, URL or exception text is
logged. A duplicate supplied directly to matching is also patient instability;
invalid IDs remain finite. Preserve proofs for diagnosis; do not reset jobs,
leases, budget, counters or restore caches to work around these errors.

Local fake regressions cover insert/close/reopen/reorder for61/62 rows, exact
baseline reproduction, current duplicate versus valid retained proof, metadata
change around comments, malformed response, zero-model engine deferral and
15–18s due-delay without failure consumption. Existing v3 content/ownership,
same-signature selection, changed-signature unchanged-batch reuse, v1/v2
rereview, independent replacement cap/audit and publication tests remain green.
No live probes, inference, queue writes, deployment or push were performed.


## Snapshot consistency live receipt — 2026-11-06

Approved source **598f9fa6b1fb73490e0440aaabbaee255952a4c5** deployed through ordinary
SPI autoSync/Recreate; worker started18:54:20Z, all13 normalized runtime files
match source, unchanged pinned container/PVC spec. 198 SPI+5 helper+9 JS tests,
Helm lint/template and diff checks passed. No source follow-up or synthetic calls.

**Acceptance PENDING.** Original bounded natural window18:54:32–20:09:33Z,
74 private consistent samples; observer ended, no continuing monitoring promised.
16 new batch proofs/158 candidate reviews (12.8 batches/hour), two unrelated
publications19:26:04Z/19:47:52Z (1.6 completions/hour), complete175→177.
All four original target jobs still queued/stage0/attempt0; no target publication,
Reader file proof or independent Telegram2/2 publication acknowledgement exists.
Do not substitute unrelated publications or rerun accepted fixtures as proof.

Exact pending episodes: resolved KubeDeploymentReplicasMismatch uptake-kuma
`83bb101278aba11036f0ce7841eabaeb9ebc00339cd667da626c9beee8e41700`
(firing305b227c…/resolved8c6af704…), firing SocratContainerRestartsFrequent
`b5a10f46b0a2ce6ebb6429d78cc9cb13e42f0a562f6b39abc181c2d51a7cae0c`
(job08ba1f09…), stale SPI
`b201c71c8b2bce1305233bfa7e47cacae545f2435fe6d644fd1df9bdf74cfb31`
(job998bcead…). All still require natural match/collect/analyze/publish, exact
primary+public-origin artifact links, original Reader bytes/SHA and applied TG2/2.

Actual stored v3 same-signature prefix reuse and changed-signature unchanged
partitions were verified by IDs and content digests against current snapshots:
a16a retained3 partitions/35 IDs and c93 retained2/24 across changed signatures;
later same-signature extensions retained exact prefixes. a16a finished6 batch
reviews/63 candidates,4 positive nominees and3 final pairwise comparisons;
c93 finished6/62,0 nominees/0 comparisons. fa453 currently5 reviews/53 of63,
0 nominees/0 comparisons; a92 currently3/29 of63,0/0. N positive nominees may
require N−1 pairwise calls even when a combined payload might fit. Throughput is
not a target ETA:23 queued and3 retry remain, signatures and network vary.

19 admission deferrals, one finite match UPSTREAM_TIMEOUT19:09:12Z and one
patient GITHUB_SNAPSHOT_UNSTABLE19:27:49Z occurred, with subsequent progress.
No new INVALID_MATCH_PROGRESS or live cap exhaustion observed. Snapshot HTTP
count/duration and instability subtype not available in existing telemetry.
Historical18:35 cause remains UNKNOWN; local pagination reproduction is not
proof of that historic cause. Equal double observations are not transactional.

Fresh private SQLite backup API snapshots passed header/integrity/FK checks.
All323 baseline IDs/creation preserved; all119 cancelled whole rows identical.
Terminal state/stage/result/intent preserved; one complete row naturally got a
duplicate delivery14→15 and updated time. Outbox applied70→72/pending7 unchanged;
v3 rows2→4, snapshot_budget0→0. No manual claims/requeue/restore/reset, receipt
reassociation, quota/identity/network changes or model probes. Reservations are
not exact usage. 3RPM/30000TPM/parallel1, durable three-generation bound and
664-second scheduling guard retained. Further natural observation is a parent
scheduling decision, not an ongoing observer from this completed window.

### Source-only tokenizer lifecycle correction (not activated)

The experimental local accounting loader now retains one process-global native
Tokenizer across Models, validates every requested asset/library contract before
reuse, serializes initialization/encode, and rejects alternate contracts until
restart. Read-only assets and installed library are required. Byte-bound default,
384Mi/1 CPU, existing budget charges and v3 proofs are unchanged. Combined local
regression with 24 live Models completed without OOM at 276436 KiB peak, but is
**not accepted**: three missing-tool test errors and one byte-bound-specific test
expectation remain; seven installed-reference historic oracles and legal packaging
are unfinished. See services/spi-tokenizer/README.md. No live activation or
throughput improvement is claimed; rollback retains database/cache/budget and
selects the prior image with byte-bound-v1, never refunds.

## Source-only local counter validation completed — 2026-11-06

CODE_READY for source only; **not activation or live acceptance**. This supersedes
the earlier unfinished lifecycle validation, not the blocked three-card live gate.
No current cards were queried or forced. Default remains byte-bound-v1.

### Installed-reference actual-payload oracles

Read-only SQLite historical prefixes were reconstructed through actual
Model.analyze; Model.call was intercepted before admission/transport. Payloads
were passed in pipes only, not persisted or printed. Installed CPU-only
AutoTokenizer.from_pretrained(local_files_only=True) in the existing vLLM
container applied add_generation_prompt=True, enable_thinking=False to the
actual messages. No generation/inference endpoint was used. Local native IDs
(add_special_tokens=False) matched reference IDs by SHA256 of canonical JSON
integer lists; rendered UTF-8 hashes and counts also matched in every row.

| Prefix | Input JSON bytes | Local reservation | Reference prompt | Prompt + 2500 | Headroom | IDs/render/count match |
|---|---:|---:|---:|---:|---:|---|
| e712 | 18421 | 9315 | 5366 | 7866 | 1449 | true |
| de23 | 22703 | 10999 | 7050 | 9550 | 1449 | true |
| 1cbe | 27564 | 12023 | 8074 | 10574 | 1449 | true |
| 0900 | 27203 | 12433 | 8484 | 10984 | 1449 | true |
| 613a | 28594 | 13229 | 9280 | 11780 | 1449 | true |
| 1482 | 21683 | 10826 | 6877 | 9377 | 1449 | true |
| 9b7 | 20980 | 10335 | 6386 | 8886 | 1449 | true |

Public ASCII contractions, NFC café, four-byte emoji, combining e+acute,
escaping and literal template/special-token injection fixtures also matched.
Empty-system rendering is separately exercised by the maximum-size fixture.
The manual render was confirmed for these supported inputs, not replaced by
rounding or a chars-per-token guess. Unsupported models/roles/tools/thinking
remain fail-closed. No private body/encoding cache exists.

Pinned public source base:
https://huggingface.co/RedHatAI/Qwen3.8-27B-INT4/resolve/91bd022d5b49442a868bc35008f6c21e1860edfa/

- tokenizer.json SHA256 06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523
- chat_template.jinja SHA256 c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041
- tokenizer_config.json SHA256 5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f
- tokenizers 0.22.2 musllinux wheel SHA256 38337540fbbddff8e999d59970f3c6f35a82de10053206a7562f1ea02d046fa5; immutable public wheel URL in services/spi-tokenizer/wheel-url.txt.

Reservation is exact supported rendered prompt count + full response-format
UTF-8 bytes + 256 allowance + explicit completion cap (2500 or 768), not exact
provider usage. Historic headroom is 1193 schema bytes + 256; public {} fixtures
have 258 headroom. Reservations are materially below the validated byte bound;
no provider-alias equivalence beyond this pinned contract is asserted.

### Regression, memory and effective scheduling

Separate ephemeral validation image added only Node v24.22.1 and git 2.54.0 to
the existing candidate, Python 3.13.18 unchanged. Production Dockerfile has no
Node/git. Absolute real paths were used for Docker mounts; the existing common
Git directory was mounted read-only at /Users/antonmoss/code/homelab/.git.
Final validation image 9b64190ce002ebfb12132816baa06129dd33d2c890bf67ce02e3af4538a84af3
is the tool-extended candidate with the same legal files overlaid, not a runtime
artifact. Source-only packaged production image:
5b9b9c6da929f902902d7b415d923000004e3ddcb6560bbb568c9d86fd4841d1.

All **206** SPI tests pass in local mode, 384MiB/1CPU/network none, zero skips,
errors or OOM; 41.337s, 277800 KiB peak process RSS, 24 retained Models share
one native counter (8.538s initialization/validation). Peak is not steady RSS.
All original correctness fixtures remain; no runtime feature edits. Native
asset/template/library/manifest failures reject Model construction before any
recovery/admission/HTTP calls; request model/roles/tools/thinking failures reject
accounting before admission/HTTP. Local 60k compressible JSON succeeds with a
valid fake response; deterministic incompressible 60k rejects before HTTP.
Legacy assertion explicitly selects byte-bound mode instead of hiding failures.

Byte-bound compatibility in the asset-equipped validation image: 206 tests pass,
zero skips (29.585s). Native host: 206 tests pass, three optional native class
cases skipped because the host lacks /opt/spi-tokenizer (4.095s); this is not
substituted for the zero-skip local image result. Helper suites: 4 chart + 1
writer-secret tests pass. Ingress JS: 9 pass, zero skips. Helm lint/template and
git diff --check pass.

New typed integer-cost fake-clock durable-ledger regression uses actual native
costs [3586,3586,3586], sum 10758 vs byte-bound [18299,18299,18299], sum 54897.
Three serial calls fit 30k TPM/3RPM; parallel reservation rejects; fourth rejects
until first completion+61 (161.999 rejects, 162 accepts). Reopening Store after
each completion retains charges; actual=1 never refunds. Upward actual=30000
persists across restart, blocks until completion+61 (223.999 rejects,224 accepts).
This proves synthetic effective admission, not live throughput or a card ETA.

### Packaging and operations

Build is deliberately a strict verified preloaded asset context, not a universal
fetch script: sh services/spi-tokenizer/build-local.sh /path/to/verified/assets.
No repeat 20MB download is required. Build/runtime pins and wheel are unchanged.
Matching immutable upstream tokenizers LICENSE and Rust LICENSE pointer are
preserved in services/spi-tokenizer/legal and copied into the internal image.
Commit f383101a26663708484cac0727792aad74f78234 (v0.22.2) recursive upstream tree
contains no NOTICE; none invented. See legal/PROVENANCE.md for exact public URLs,
hashes, model Apache-2.0 declaration/attribution and canonical Apache license.
No model weights, third-party shipping or certification of all transitives.

No push/deploy/queue/provider/resource changes; runtime network remains disabled
for validation. No source-phase claim about current three cards, no new probes,
nominee grouping or lifecycle redesign. Credentials, IDs, PVC, calendar/Yandex,
blog-off, Root network, Mac/DNS/edge unchanged. Rollback selects original image
and byte-bound-v1, preserving database/cache/v3 proofs and integer ledger charges.
