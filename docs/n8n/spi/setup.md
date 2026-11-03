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

- Existing GitHub App: `socrat-pr-agent`. App key remains in namespace `pr-agent`.
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

## Evidence v1 and explicit gaps

Read-only Grafana datasource proxy accesses rule definitions, historical metric
windows, scoped Kubernetes job/pod series, systemd unit state/restart series and
namespace or host Loki error frequency. Host identity comes from node_uname_info.
When a valid trace_id is supplied, Tempo contributes span/error counts only; raw
span attributes are never passed to the model. An allowlisted GitHub runbook on
main can be included with its SHA and an explicit deployed_version_verified=false.
Requests are bounded by time, response size and namespace selectors. Whole rule
catalogues and arbitrary raw log lines are not passed to the model or GitHub.
Raw log publication, automatic trace discovery and deployed-source correlation
are not implemented. Missing trace IDs and unverified deployment versions are
explicit gaps, not evidence of health. Do not claim a
confirmed root cause without supporting observations or invent thresholds/paths.

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

- 64 local tests: 31 SPI Python, five native ingress, nine Yandex client, six calendar,
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
authored by `socrat-pr-agent[bot]`, English title/body, matching event marker, no
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
signals. A first natural repeat was semantically matched to open SPI #9 by the
model; its subsequent analysis/comment may still be waiting for inference. Do not
claim that all pending incidents have been diagnosed or that a comment was posted
until the corresponding completed job and GitHub object are checked.
