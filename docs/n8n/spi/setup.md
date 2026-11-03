# SPI incident triage

## Contract and rollout

All generated issue titles, descriptions and comments MUST be **English**.
Titles start with `[SPI]`. Match only open SPI issues, using the model for semantic
identity rather than just alert-name equality. Closed issues do not prevent a new
incident issue. Distinguish service impact from monitoring quality; a brief or
self-resolved incident is not automatically a false positive.

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

`SPI Incident Triage` runs each minute:

`Every Minute → Claim Triage Job → Select Claimed Job → Match Open SPI → Collect Evidence → Analyze Incident → Publish SPI`

Only opaque job IDs/status travel between stages. Evidence, drafts and progress
live in a dedicated private SQLite PVC owned by the worker, **not n8n's database**.
Single replica + Recreate, atomic claim and expiring leases prevent concurrent
publication. A single-worker cold start releases interrupted claims and resumes saved stages. Stages have bounded request budgets;
transient failures back off, eight claims exhaust the retry budget. Dead jobs
require review. A resolved event comments on its known open SPI; it never opens an
orphan issue, reopens a closed one or automatically closes the incident issue.

## Credentials and scope

- Existing GitHub App: `socrat-bot`. App key remains in namespace `pr-agent`.
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

### Live v2 acceptance

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

Queue polling emits sanitized `queue_health`; final failures emit `stage_failed`.
Grafana/Loki definitions in `alerts.json` monitor failures (including ingress handoff), missing polling, stale work and dead
jobs through a dedicated Socrat Alerts contact point. Provision via
`python3 scripts/n8n/provision_yandex_alerts.py docs/n8n/spi/alerts.json` after activation.
No global notification policy changes. Delivery depends on n8n, not on the model;
a complete n8n outage can delay Telegram even while Grafana displays the alert.

Keep consistent off-node copies of `/data/spi.sqlite` using SQLite's backup API,
not a raw live file copy. PVC keep/Prune=false is not a backup schedule. Completed
job/evidence retention is not automated yet; monitor disk usage before expanding
traffic. Never erase pending/ambiguous-publication state to clear an alert.

## Verified acceptance

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
authored by `socrat-bot[bot]`, English title/body, matching event marker, no
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
