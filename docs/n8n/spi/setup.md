# SPI incident triage

## Contract and rollout

All generated issue titles, descriptions and comments MUST be **English**.
Titles start with `[SPI]`. The current managed catalog has **20 open workstreams**
and **zero automatic issue creation**. Stable service/workload routing replaces
catalog-wide LLM matching; this is organizational grouping, not proof of a shared
root cause. Unknown/high-impact findings enter review #17; availability-check
subcases use #50 unless promoted by severity. Distinguish service impact from
monitoring quality; a brief or self-resolved incident is not automatically a false
positive. Canonical implementation and maintenance contract:
[`alchemmist/spi-triage/docs/managed-catalog.md`](https://github.com/alchemmist/spi-triage/blob/main/docs/managed-catalog.md).

On 2026-11-10,152 open source reports were consolidated into20 open topics and132
standalone closures, explicitly **not marked fixed**. Source bodies/comments,
graphs, immutable evidence and historical queue rows were retained. Targets index
sources; closed sources link back. Every production GitHub client rejects new
issue creation. Humans must free a slot before introducing a new tracking issue.

Managed Match makes no paid call and reads neither a full catalog nor comment
history. Evidence collection, analysis/citation validation, S3 verification,
publication intents, ownership fences, finite budgets and original n8n identities
remain in place. Comment churn no longer forces a paid snapshot re-review.
Legacy matching/snapshot descriptions below apply only to compatibility and
historical execution reconciliation, not new managed work.

The rollout used naturally completed16842 and verified zero logical owners,
processing jobs, paid reservations and native pending SPI executions. Queued
admissions were retained. Only SPI intake was paused; its original activity was
restored after the immutable release reached Synced/Healthy and all20 targets
passed native-authorized read-only validation. Other workflow activity flags and
SPI graph/settings/credential bindings were unchanged.

Deployment was first verified in **dry-run**, then SPI publication was enabled
(`charts/spi-triage/values.yaml: writeEnabled: true`) within the operator-authorized
implementation. The independent blog worker remains write-disabled. Historical
dry-run jobs are not replayed. Set SPI writeEnabled=false to pause publication
without changing Telegram delivery or the blog policy.
Operator progress checklist: `/tmp/socrat-spi-implementation-plan.md` on the agent host.

## Architecture

Original Socrat Alerts retains its workflow identity and Telegram path. Its native
`CUSTOM.socratAlertWebhook` validates an encrypted ingress credential, strips all
request headers and known secret fields, and durably enqueues the group before
acknowledgment. If queue handoff fails it returns retryable 503 **and still emits
sanitized workflow data for Telegram**. Sender retries are deduplicated. Legacy
migration mode accepts unauthenticated Telegram-only delivery, never SPI jobs;
it must be disabled after migrating both Grafana and Alertmanager authorization.

`SPI Incident Triage` uses an authenticated native Webhook, not an n8n Schedule Trigger:

`Dispatch Webhook → Claim Triage Job → Select Claimed Job → Match Open SPI → Collect Evidence → Analyze Incident → Publish SPI`

Authenticated `/enqueue` and `/enqueue-group` commit to the existing durable SQLite
queue before signaling the background dispatcher. The queue remains authoritative;
there is no Redis/Postgres migration. Execute-subworkflow is not required: native
ingress commits the queue and the worker coalesces and sends event wakes.

With `SPI_DISPATCH_ENABLED` (default **false**) enabled, the dispatcher POSTs `{}`
to the fixed internal URL
`http://n8n.automation.svc.cluster.local/webhook/spi-incident-triage-dispatch`.
`X-Worker-Token` uses the existing `WORKER_TOKEN`; the native Webhook uses
`headerAuth` and the same `SPI_WORKER_CREDENTIAL_ID` / `httpHeaderAuth` mapping
already used by `/claim`. Response mode is immediate `onReceived`. Alert payloads
cannot supply a callback target. One execution claims one job; subsequent stages
remain unchanged. Empty queues must not generate n8n executions.

Enqueue and stage completion/failure (including unexpected errors where appropriate)
signal the dispatcher. It starts the next job only when due and no active processing
lease exists. Durable dispatch reservation/backoff covers ambiguous wake responses,
slow or unavailable n8n and the claim callback race; `/claim` acknowledges the
reservation. Duplicate wakes are coalesced. Startup recovers interrupted jobs and
dispatches due work. The worker's internal timer waits for the next retry, lease or
reservation deadline, recovering lost wakes without an every-minute n8n execution.
No SQLite transaction or dispatcher lock is held across network or model calls.
This is not an exactly-once delivery or guaranteed model-success contract.

Only opaque job IDs/status travel between stages. Evidence, drafts and progress
live in a dedicated private SQLite PVC owned by the worker, **not n8n's database**.
Single replica + Recreate, atomic claim and expiring leases prevent concurrent
publication. A single-worker cold start releases interrupted claims and resumes saved stages. Stages have bounded request budgets;
transient failures back off, eight claims exhaust the retry budget. Dead jobs
require review. A resolved event comments on its known open SPI; it never opens an
orphan issue, reopens a closed one or automatically closes the incident issue.

## Credentials and scope

- Existing GitHub App: `socrat-steward`. App key remains in namespace `pr-agent`.
- Broker CronJob every 20 minutes issues a one-hour installation token limited to
  repository `homelab`, Issues:write, Contents:read and Metadata:read; no PR write.
- Its service account can only patch the precreated `automation/spi-github-installation`
  Secret. Worker reads refreshed token from a projected file, not cached env.
- Dedicated LiteLLM virtual key: `qwen3.8-27b`, 3 RPM, 30k TPM, one parallel request.
- Grafana token: existing Viewer identity; no admin key in the worker or model.
- Worker API token and ingress bearer token are independent. Native credentials
  and private mapping `~/.config/n8n/spi-credentials.json`; no values in git.
- `scripts/n8n/provision_spi_secrets.py --secrets-only` bootstraps runtime Secrets;
  full invocation creates native credentials after the extension is installed.
- Source: `charts/spi-triage/`, `charts/n8n/extensions/SocratAlert*`, workflow JSON
  here and in `docs/n8n/socrat-bot/workflow.json`; `scripts/n8n/sync_spi.py` only
  updates inactive workflows. Preserve original workflow and Telegram credential.

## Correlation, limits and publication

Pagination examines all open `[SPI]` issues and excludes pull requests. Existing
issue bodies/latest comments are bounded excerpts. Each candidate batch is reviewed
by the model; over 120 open SPI fails visibly instead of silently skipping issues.
The analysis revalidates initial matching with evidence. Before writing, an open-
issue snapshot change restarts matching. Identical webhook deliveries do not cause
new model calls/comments; new episode start time creates a distinct event.

Publication stores intent before POST and includes an opaque HTML event marker.
A lost response is reconciled through that marker, including closed issues only
for technical reconciliation, never semantic matching. If ambiguous and unproven,
job becomes `WRITE_NEEDS_REVIEW`; do not blindly repost. There is no distributed
exactly-once guarantee. Recommendations never execute repairs or mutate alert rules.

Reports separate verified facts, hypotheses, impact, confidence, alert quality,
service prevention, monitoring improvements and missing evidence. Non-English
scripts/schema violations trigger at most one model-output retry; transport
failures remain failures. Alerts/issues/tool results are untrusted prompt data.

## Evidence v2: reproducible incident artifacts

Text evidence is published directly to the issue/comments, not an evidence branch,
GitHub release or binary attachment. No extra GitHub Contents permission is needed;
the triage token remains Issues:write + Contents:read, scoped to homelab.

Collection freezes a sanitized bundle in durable job state before analysis. Reports
link absolute-time Grafana Explore queries; subsequent comments contain the actual
text artifacts and a final clickable index. Each artifact has an evidence ID,
source/query/window, stored-character count, truncation/redaction flags and SHA-256.
The manifest records gaps and limits. Parts concatenate in order without code fences;
checksums refer to stored ASCII JSON, not the pre-redaction source.

Included when available:
- The authenticated alert event, matching rule definition, range-query samples,
  compact observations, exact parameters and collection timestamps.
- Scoped Loki error/stack lines and nearby context around up to three error anchors.
  Job targets use Kubernetes-verified job pods, not kube-state-metrics exporter pods.
  Systemd alerts use resolved host/unit scope, not exporter namespace logs.
- Tempo discovery from log trace IDs and validated service/time searches, followed by
  bounded spans, parent links, status, exception events and service-version attributes.
- Read-only pod/workload owner chain, image/imageID, rollout revision, current and
  previous termination, retained Kubernetes event timeline. No env/Secret contents.
- OCI source/version claims for accessible digest-addressed Harbor images. If OCI
  access is unavailable, Socrat bot can use an immutable GitOps release manifest whose
  image digest matches the observed pod image, resolve the full source commit and
  link that exact revision. Stack-referenced Socrat bot Python files can contribute
  up to two numbered excerpts from that revision, never arbitrary URLs or `main`.

Version evidence describes observed deployment at collection time, not automatically
at incident onset. OCI labels and GitOps release mappings are not reproducible-build
attestations. Unsupported source repositories, host installed versions, inaccessible
registries and expired telemetry remain explicit gaps, never guessed versions.

### Bounds and publication recovery

Metrics retain their original query windows. Raw telemetry has a six-hour lookback,
a one-hour maximum window with five-minute padding, at most ten new telemetry reads,
40 error + 40 stack lines per scope, 20 context lines per query, five trace search
hits and two fetched traces (20 stored spans each). Artifact-local windows/limits
are authoritative; long incidents can be clipped. No hits do not establish health.

Artifacts are capped at 90,000 ASCII characters each / 360,000 in aggregate (plus
manifest). Comment payload parts are at most 40,000 characters. The model gets the
full index, compact metric observations and up to 24,000 characters of prioritized
new diagnostic excerpts. Every verified fact must cite a valid evidence ID; the
model must not claim to have reviewed every stored byte.

Progress and the pending marker are saved before each comment POST. Repeated delivery
or restart reconciles published parts rather than duplicating them. Unobservable
ambiguous writes require operator review; do not erase the intent or blindly retry.
Comment authors are checked by immutable GitHub App ID **5569869**, not its renameable
slug. Issue API responses may omit App metadata; their immutable Bot user ID
351189559 is the verified fallback. Human marker text must never count as a confirmed App write.

### Download and verify a stored episode

Use the event key shown in the evidence index, not just the alert fingerprint:

```sh
python3 scripts/n8n/download_spi_evidence.py \
  --issue 9 \
  --event a0d1f3574290e2c681f95266b695db62b9afc08b9401b471bfdb8fe0ce3a29f3 \
  --output /private/path/spi-9-evidence
```

The helper uses existing `gh` authentication, paginates comments, checks App identity,
reassembles parts, verifies all checksums against the manifest and writes private
files. It refuses missing/conflicting/tampered parts and unsafe output overwrites.
No tokens, cookies, private keys or credential databases are valid attachments.
Internal IPs, hostnames, stack traces and deployment metadata are approved diagnostic
content; credential values and emails are redacted before persistence/publication.

### Historical live v2 acceptance

- [Real SPI #9 evidence index](https://github.com/alchemmist/homelab/issues/9#issuecomment-6610936449):
  nine artifact parts / eight reconstructed files, including MANIFEST, with eight
  absolute-time Explore links. This is a supplement to a real episode, not a fabricated alert.
- Downloaded all files from GitHub and verified their SHA-256 locally. Repeating
  publication from fresh local progress reconciled all parts without any POST.
- Pod/owner/event reads worked using the worker identity; Secrets, exec subresource
  and deployment patches were denied. The role cannot read credential stores.
- Socrat bot's running pinned image was matched to immutable release manifest
  `701da1e70d0ab817b0a6db82b3f440b1e29883b8`, resolving source revision
  `a90a8915f620f594a01cd1668aab60509e6f4f0f`. Harbor anonymous OCI reads returned
  HTTP401; no registry/admin credential was added to the worker. GitOps fallback
  supplied the verified release association instead.
- Live log/trace searches for the supplemented systemd episode returned no matching
  lines/traces. This is recorded as missing evidence, not successful root-cause proof.

## Operations

Worker `/healthz` is process readiness; authenticated stage calls and real model
responses are separate acceptance checks. `/metrics` exposes job-state counts and
pending age for future scrape integration. Do not assume a ServiceMonitor is
scraped: this cluster has retired legacy Prometheus selectors.

Worker queue health emits sanitized `queue_health`; final failures emit `stage_failed`.
Grafana/Loki definitions in `alerts.json` monitor failures (including ingress handoff), missing worker heartbeat, stale work and dead
jobs through a dedicated Socrat Alerts contact point. Provision via
`python3 scripts/n8n/provision_yandex_alerts.py docs/n8n/spi/alerts.json` after activation.
No global notification policy changes. Delivery depends on n8n, not on the model;
a complete n8n outage can delay Telegram even while Grafana displays the alert.

Keep consistent off-node copies of `/data/spi.sqlite` using SQLite's backup API,
not a raw live file copy. PVC keep/Prune=false is not a backup schedule. Completed
job/evidence retention is not automated yet; monitor disk usage before expanding
traffic. Never erase pending/ambiguous-publication state to clear an alert.

## Historical acceptance before event-driven migration

- 98 local tests: 65 SPI Python, five native ingress, nine Yandex client, six calendar,
  thirteen blog. Helm templates render with the pinned images.
- Authenticated ingress execution **1927** persisted its group and the bot returned
  a message record. No ingress/worker/GitHub token appeared in its execution data.
- Unauthorized webhook returned **401**. Both Grafana receivers and live Alertmanager
  use the dedicated ingress credential; migration mode is disabled.
- Synthetic report and real KubeJobFailed report completed in dry-run. Execution
  **1976** completed all seven triage nodes; reports rendered English `[SPI]` titles.
- Identical delivery increased the existing terminal job's delivery counter without
  creating a new analysis. SQLite online backup copied off-node and integrity checked.
- Real worker rollout preserved queued/done jobs and recovered one interrupted job.
- Scheduled GitHub broker refresh succeeded; installation token repository inventory
  contained only `alchemmist/homelab`. Current 20-minute schedule allows renewal margin.
- Original Socrat Alerts **b2TlucyOTiZP9CzN** and SPI Incident Triage
  **J9akzlydrf9XZiID** are active and rendered parameters/connections match live.
- All four Grafana SPI rules evaluated inactive/health=ok after provisioning.

Shared local inference can take minutes. Triage is asynchronous, not a promise of
instant diagnosis; 3 RPM pacing, deadlines and pending-age alert make contention
visible. Review early report quality: a plausible hypothesis is not established
root cause. Publication create/comment and ambiguous-write recovery are covered
by tests. Real publication verified: [SPI #9](https://github.com/alchemmist/homelab/issues/9),
authored by `socrat-steward[bot]`, English title/body, matching event marker, no
known worker/model/Grafana/GitHub token values. The post-publication off-node
state backup includes its completed job. Historical synthetic reports were not posted.

## Shared inference latency

Observed six-minute inference timeouts during the initial rollout. Calls now allow
up to 600 seconds within the 780-second stage budget, with explicit timeout error
codes and paced requests. Matrix/vector samples are reduced to verified extrema,
first/last values and counts before inference; original queries/windows remain
attached. Existing saved evidence is compacted on retry too. Raw sample arrays and
unrelated active-alert catalogues are not needed in the prompt.

This does not add GPU capacity or preempt PR review. The durable queue may lag
under shared-model contention; backlog/failure alerts are meaningful operational
signals. A subsequent natural incident was semantically matched to open SPI #9 by the
model and [appended as an English bot comment](https://github.com/alchemmist/homelab/issues/9#issuecomment-6608101252).
Both create-new and append-existing paths are therefore verified live, not only
mocked. Other queued incidents may still be waiting; do not claim the queue is drained.

## Read-only root filesystem and SQLite temporary storage

The final large-queue startup probe exposed `SQLITE_IOERR_GETTEMPPATH` (6410):
SQLite needed a statement temporary file while updating an interrupted job, but
root filesystem `/tmp` was read-only. The database itself passed integrity checks;
node disk and inodes were available. A no-content-change update did NOT reproduce
this failure; the exact startup recovery statement did.

Every Store connection now sets `PRAGMA temp_store=MEMORY`. A bounded 64Mi memory
emptyDir is mounted at `/tmp` with SQLITE_TMPDIR set, retaining readOnlyRootFilesystem.
A regression test checks per-connection temp mode and interrupted-job recovery.
Do not solve this by resetting SQLite, deleting dedup state or enabling a writable
container root. During repair, the worker was stopped and a private physical copy
was retained; the supported recovery update succeeded with memory temp storage.
No n8n database changes or old-snapshot rollback were involved.

Recovery acceptance: worker returned Synced/Healthy; Store integrity check and a
native duplicate-delivery write passed with memory temp-store. At least 50 jobs
were retained in the final verified consistent off-node snapshot. The temporary
storage probe was removed and Argo reconciliation and SPI scheduling restored.
Monitoring can remain firing for recent failures and pending for backlog after
recovery; healthy rule evaluation is not the same as all alerts being Normal.

### Explore links and anonymous dashboard access

Grafana 13.2.4 with anonymous Viewer redirects unqualified `/explore` links to
`/d/default-home-dashboard/home`, losing the visible query/time context. Set
`forceLogin=true` as the last query parameter. Native Grafana redirects a missing
session to `/login?redirectTo=...`, preserving the encoded panes and absolute
milliseconds; authenticated users go directly to Explore. Do not enable anonymous
Explore or promote existing users to solve this. Explore requires Editor/Admin in
this installation; sign in with the existing appropriate Authentik identity.

The generator, rendered cached-bundle index, and outgoing narrative Markdown
normalize these links. Retained JSON/manifest checksums must not be rewritten.
Historical bot-authored rendered links can be patched in place, without adding
comments or deleting diagnostic history.

Read-only browser regression: install/use Playwright outside the worker; set
`SPI_GRAFANA_CHECK_DIR` to a private directory with `links.json` (array of
`[title,url]`) and `browser-state.json` (existing native Editor/Admin session), then
run `node scripts/n8n/check_spi_grafana_links.cjs`. Optional
`SPI_GRAFANA_TEST_UPSTREAM=http://127.0.0.1:PORT` routes only the fixed Grafana origin
through a trusted SSH tunnel for environments without the private route. No TLS
verification is disabled and no users/permissions are created by the checker.
Keep session state private and remove it after testing. The checker verifies actual
Explore navigation, datasource, time-picker UTC boundaries, exact query in the
editor or executed request, and query parsing errors. JSON browser results are
written privately to `browser-all.json`.

Acceptance: all eight real index links from SPI #9 passed browser checks. A native
temporary Editor session verified login return and authenticated navigation; it
was removed afterwards. This does not claim a full human Authentik login was
performed. Anonymous redirect behavior was reproduced before and after the fix.

## Historical event-driven staging checklist (see current acceptance)

Historical evidence above does not verify the event-driven rollout. Parent/operator
owns deployment and must verify each item; this documentation makes no claim that
this migration has been deployed or tested.

- [ ] Preserve n8n identity, both workflow IDs, existing credentials, encryption key,
  n8n PVC, worker SQLite PVC and the original Telegram path.
- [ ] Deploy with `SPI_DISPATCH_ENABLED=false`; retain queue and saved stages.
- [ ] Activate the authenticated event workflow, with no Schedule Trigger, before
  enabling the dispatcher. Verify the existing header credential mapping privately.
- [ ] Enable dispatch only after activation; verify commit-before-wake, one job per
  execution, empty-queue silence, duplicate-wake coalescing and lease exclusivity.
- [ ] Verify unavailable/slow n8n, ambiguous responses, claim callback races, retry
  deadlines and restart/lost-wake recovery without publishing test incidents or
  sending Telegram tests. Do not assume model success from webhook acceptance.
- [ ] Review backlog age, due/retrying jobs, active lease and dispatch reservation
  deadlines alongside n8n executions and sanitized worker errors. Allow backoff to
  recover missing wakes; never bypass leases or delete queue state to force progress.
- [ ] For `WRITE_NEEDS_REVIEW`, reconcile existing GitHub intent/markers manually;
  no blind GitHub retries. Preserve consistent SQLite backups before intervention.

Disabling dispatch pauses new wakes, not already-running executions or publication.
SPI publication policy and the separate blog dry-run policy remain independent.
Current text artifacts remain in issue comments; multi-comment storage is noisy.
S3 storage is not deployed, and artifact-storage migration is separate work.

Security integration: dispatch uses CUSTOM.socratSpiDispatchWebhook with the
existing httpHeaderAuth credential, not the built-in Webhook (which emits incoming
authentication headers). Only `{dispatch:true}` enters execution data. Credential
comparison occurs in the trigger; POST acknowledgement is immediate. Worker egress
is restricted to automation/app=n8n pod TCP5678 for the fixed callback.

## SPI links on original Telegram cards

Implementation uses the native bot API documented in the human wiki
`wiki/content/platform/socrat-bot.md`, not text patching or replacement messages.
A primary GitHub receipt (issue root for a newly created issue, exact primary
narrative comment permalink for a match) is committed atomically with a desired
link outbox row. Artifact/index comments are never the Telegram target.

The ingress carries the authoritative SPI episode into `alert.spi_episode`.
On a queue503 it computes the identical bounded canonical digest so an upstream
retry does not orphan the Telegram card. Native bot keys retain `/spi/<episode>`;
firing/resolved share a card, a later episode has another key, and a delayed firing
cannot regress a resolved episode. Raw headers never enter n8n output. The bot
response supplies immutable key and acknowledged copy IDs; n8n posts a bounded
receipt callback. If that callback is lost, an independent discovery loop finds
retained cards via `/v1/cards?status=all&episode=<digest>`. Completed pre-migration
SPI jobs are associated only through trusted GitHub markers, without reposting.

Bot `/v1/cards/links` receives `key,url,label=SPI,expected_copies,revision`.
The bot commits highest accepted desired revision/URL BEFORE editing, separately
from per-copy applied revision. PartialHTTP200 remains pending. Retries re-edit
failed copies; native 'message is not modified' is an acknowledgement, cached
spi_url/GET metadata is not. The shared native per-key lock protects alert/link/
note/mute operations; deployment remains one serving bot process with Recreate.
No SQLite transaction spans network/model calls. Independent delivery and
per-episode-backoff discovery loops do not block the model queue or each other.
Applied desired links are reasserted every6h to converge after ambiguous remote
completion. All retry rows survive restart; no retry republishes GitHub.

A resolved event without a prior SPI now receives semantic analysis rather than
being silently dropped when link tracking is active. It is analyzed as a recovery
observation, not an invented firing. A closed associated issue is NOT reopened,
and no fake new primary receipt/root target replaces its previous exact link.

Provisioning copies only native `INTERNAL_TOKEN` into existing worker Secret as
`BOT_INTERNAL_TOKEN`, never Telegram token/DB credentials. `telegramLinksEnabled`
remains false during staging, then enabled only after bot migration0009, callback
workflow and review are verified. Egress is limited to the native bot service8080 (hostNetwork target8082).
Worker emits internal queue health every60s for existing monitoring, not an n8n
Schedule execution. `spi-triage-telegram-links` alerts on pending link backlog.

Guarantee scope: durably accepted alerts and explicitly acknowledged native card
copies are retried until linked while dependencies remain available. Ambiguous
initial Telegram sendMessage cannot be claimed exactly-once. Historical replaced
legacy messages have no trustworthy episode identity and are not guessed. Missing
associations and permanently failing external services remain visible, not false
success. Native deleted/inaccessible messages require operator intervention.

Production original-card acceptance is recorded below; offline tests alone do not establish Telegram receipt.


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

## Patient LLM client retries

Busy inference is deferred work, not an exhausted task. SPI model transport
failures are namespaced at the Model adapter boundary; the explicit allowlist
covers429/408/425, selected transient5xx, network/timeouts, attempt-budget expiry,
and malformed JSON/schema responses. These jobs remain `retry` regardless of
number of claims. No arbitrary HTTP error or GitHub publication automatically
receives this exemption. Auth/configuration errors and unsafe/invalid semantic
output still have an independent finite failure budget; `WRITE_NEEDS_REVIEW`
remains immediately terminal and visible.

Total `jobs.attempts` counts claims for diagnostics, NOT the terminal budget.
The separate durable `job_failure_budget.failures` increments only for capped
failures. Thus20 busy-LLM deferrals cannot consume the allowance for the FIRST
later ambiguous GitHub timeout. Intent persists and reconciliation runs before
any repeat POST. Existing terminal jobs are not automatically reopened; audit
cause/stage/intent first. On initial rollout no existing `dead` jobs were found.
New budget rows start at zero; historical claim counts cannot reconstruct a
trustworthy capped-failure history, and existing terminal states stay unchanged.

Each attempt retains bounded request/stage budgets; failure clears its lease and
schedules persisted `available` with exponential backoff, jitter, and an ordinary
cap of1h. Valid numeric/HTTP-date Retry-After supplies a minimum delay (accepted
hints bounded to24h). Long waits do not sleep inside an n8n execution or hold the
Engine lock: independent dispatcher resumes due jobs after restart. The existing
short intra-stage pacing and up to2 malformed-output attempts remain bounded.
The global HTTP transport uses socket timeouts, not a general proven absolute
wall-clock bound against trickling upstream responses; no subprocess transport
redesign is claimed here.

Each successful issue-comparison batch checkpoints validated decisions into
`result.match_progress`. Identical full snapshot digest resumes remaining batches
or final arbitration after retries/restarts. Snapshot changes invalidate cached
decisions. Repeated changes or permanently unavailable upstreams can prevent
completion: the promise is retained visible work and safe retries, NOT unconditional
success. Model deferrals log safe `stage_deferred` warning codes, not request
headers/body or ordinary `stage_failed`; queue age/backlog monitoring remains.

Scope is SPI only. Calendar, blog and other inference clients still require a
separate retry-contract audit; blog stays write-disabled. Telegram link retries
remain independent of model/GitHub publication. No synthetic production incident
or intentional inference outage is required to test these paths.

Rollout verification (4 November2026):2e363e6 Synced/Healthy, new durable failure
budget table present, Telegram links still enabled, real dispatch202.122 Python
and9JS tests passed.20 busy-model errors followed by ambiguous GitHub publication
and single-POST reconciliation were tested OFFLINE. Live inference outages were
not injected. Verified private before/after snapshots preserve all119 prior job
IDs and creation times; existing exact resolved Telegram target remains applied2.


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

### Completion-aware scheduling (source-only correction)

See [token admission](token-admission.md#completion-aware-scheduler-correction-source-only-pending-independent-review)
for descending stage priority, bounded local-admission jitter hold, unknown429
non-hold policy and v2-safe rollback. Claim and dispatcher use the same effective
eligibility, without changing stored deadlines or pending-age alerts. Source
regressions are not live acceptance; later reviewed rollout requires a fresh
SQLite backup and fetch/rebase. Do not force claims or promote selected jobs.

## Execution 13873 / 13897 correction (deployed 8 November 2026)

Typed `GITHUB_READ_TIMEOUT` now uses the v1 durable deferred response and the
workflow's existing Wait/Resume route. The same stage, absolute deadline and
checkpoint survive; unsafe publication timeouts and legacy API semantics do not
change. Deploy the workflow validator allowlist BEFORE the worker change: old
validators reject the new deferred code. Use explicit inactive update by original
ID, preserving settings/credentials/static data and restoring original activation;
coordinate existing waiting executions rather than blindly replacing live state.

Only `INVALID_EVIDENCE_REFERENCE` in report generation gets one repair request.
The strict existing-ID validator remains mandatory. The additive
`analysis_output_budget` table binds job plus exact original request digest,
including model/prompt/schema/input. It stores counters only, not model text.
The first rejection is durable before admission waiting; the repair is consumed
before transport. A crash or lost repair response fails closed rather than issuing
another regeneration. Normal transport/admission handling is unchanged, but a
consumed repair is not replenished after transport failure. A changed original
request has a separate budget; no historical failed calls are retroactively counted.
Malformed JSON/schema and unsafe output do not get this citation-specific repair.
Rollback retains the additive ledger; no queue/budget/lease resets or job revival.

Source regressions are offline, not production acceptance. Before any push (SPI
is auto-synced), take and verify a fresh consistent SQLite backup, review the
workflow/worker rollout order and coordinate with the concurrent spi-evidence
repository extraction. No Reader/API/UI or evidence storage migration is included.

### Rollout receipt — 2026-11-08

Source `48d158ffa8076e8a6b3f2e42aeb6899461635986` pushed to main and
applied by ordinary Argo auto-sync. Updated only the deferred-code validator in
original workflow `J9akzlydrf9XZiID`, preserving the graph/credentials/settings.
Drained active publication execution14000 naturally with dispatch ingress
inactive, took a fresh SQLite backup, then pushed. Re-enabled the same workflow
after worker readiness. No forced claim, job replay or terminal revival.

Argo Synced/Healthy at this revision; pod `spi-triage-7db656545d-247rx` Ready1/1,
restart0. All four changed runtime files match normalized source; additive ledger
exists. Pre-push backup204828672B SHA256
`a3a17361c2e40cd5aa79d09b64036141ae7f5c59e31facfca1de32ea14804f50`;
post backup204828672B SHA256
`2d43d40a4dc94d6a25ce60d0fb7710f08d3b9445c0c79a640d8c87c32b5dcf93`.
Both passed integrity/FK. All565 original IDs/creation times retained, as were
terminal state/stage/result/intent for119cancelled,334complete,7dead,2dry_run.
Temporary inactive dispatch produced normal unconfirmed/backoff, then natural
`dispatch_sent`21:13:25Z and `publication_ok`21:13:29Z after reactivation.
This proves resumed ordinary processing, not a live injected timeout/citation
repair test. Those paths have offline regressions only; historic executions
13873/13897 were not rerun. Python285 tests:282pass/3optional-tokenizer skips;
ingressJS9/9; Helm lint/render and diff checks passed. spi-evidence extraction and
unrelated worktree edits untouched. Observation ended; no ongoing monitoring claim.

### Execution navigation for stage-failure alerts

`spi-triage-failures` retains its A/C condition,20-minute failure window,2-minute
hold and existing routing. Metadata-only scalar query B reads the greatest
validated numeric `n8n_execution_id` from owned v1 `stage_failed` logs in the
same window. It supplies `annotations.n8n_url`, not an alert-instance label.
For the single logical SPI slot this identifies the newest failed execution
represented in that aggregate, not every failure in a multi-failure window.
Handoff errors/old logs without execution context safely retain workflow
navigation. Zero does not create a fictitious execution. No historical logs,
notifications or terminal jobs are replayed. All n8n link labels render as `n8n`.

The native `Select Claimed Job` consumer also accepts
`GITHUB_READ_NETWORK_ERROR` and `MATCH_PROGRESS_DEFERRED`. These are typed safe
waits, not a generic error bypass. Source tests execute the SPI repository's
exported JavaScript against the backend allowlist. Operational workflow updates
must publish only the intended node change under the existing workflow identity;
never recreate the workflow, mutate saved executions or restart a busy worker.
Ordinary source pushes no longer deploy stateful SPI automatically; deployment
requires explicit dispatch and actual natural drain, independently of whether
GitHub environment reviewer rules happen to be configured.
