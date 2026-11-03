# Socrat SPI incident triage

Implementation checkpoint: **3 November 2026**. Recorded acceptance evidence is
not a substitute for checking live queue state when investigating a new incident.

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
Every Minute → Claim Triage Job → Select Claimed Job → Match Open SPI
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
| `spi-triage-heartbeat` | No queue polling heartbeat for ten minutes |
| `spi-triage-dead` | Jobs require operator review |
| `spi-triage-stale` | Pending work older than 45 minutes |

On trouble, distinguish an unavailable worker, absent scheduling, model latency,
read-only evidence gaps and GitHub authorization/write ambiguity. Inspect sanitized
codes and saved stage before intervening. Check current App-token refresh separately
from inference health. Do not suppress alerts automatically or erase pending jobs
to obtain a green dashboard. Telegram delivery is independent of the model but still
depends on n8n; a full n8n outage can delay delivery while Grafana displays the alert.

## Deployment and acceptance status

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
