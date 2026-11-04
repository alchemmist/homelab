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
