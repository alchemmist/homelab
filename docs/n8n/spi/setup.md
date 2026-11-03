# SPI incident triage

## Contract and rollout

All generated issue titles, descriptions and comments MUST be **English**.
Titles start with `[SPI]`. Match only open SPI issues, using the model for semantic
identity rather than just alert-name equality. Closed issues do not prevent a new
incident issue. Distinguish service impact from monitoring quality; a brief or
self-resolved incident is not automatically a false positive.

Initial deployment is **dry-run** (`charts/spi-triage/values.yaml: writeEnabled: false`).
No production issue/comment is posted until a deliberate write-enabled rollout.
Deployment and live validation evidence are added after verification, not assumed.
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

Before enabling writes verify: real model dry-run, semantic same/different issue
fixtures, English output, duplicate and resolved handling, webhook auth rejection,
Telegram delivery, worker restart recovery, token renewal, live/source equality,
and observability. Dry-run historical jobs are not automatically replayed on rollout.
