# Socrat SPI incident triage

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

GitHub App `socrat-pr-agent` already has Issues:write and an installation on homelab.
Do not put its private key in the triage worker. Namespace-local broker issues
one-hour repo-scoped tokens every 20 minutes without PR write and patches only a named Secret.
Worker uses Viewer Grafana access and a separate capped LiteLLM qwen3.8-27b key.
Dedicated SQLite PVC is NOT the n8n database; never modify n8n SQLite for this feature.

## Deployment and acceptance status

SPI publication is **enabled after live dry-run** (SPI writeEnabled=true).
Blog WRITE_ENABLED remains false. Do not transfer one worker's rollout policy to
another. Historical dry-run reports are not replayed or posted as test issues.

62 local tests pass: 29 SPI Python + five ingress + nine Yandex + six calendar +
thirteen blog. Live authenticated ingress/Telegram execution 1927, full real-alert
dry-run execution 1976, HTTP401 rejection, scheduled App-token refresh, duplicate
suppression and worker restart recovery verified. Both workflows are active and
rendered parameters/connections match live. Four Grafana SPI rules evaluated healthy.
Known secrets were absent from ingress execution data; consistent SPI off-node
backup integrity checked. First real issue: [SPI #9](https://github.com/alchemmist/homelab/issues/9),
authored by socrat-pr-agent[bot], English title/body and marker verified. Post-publication
queue state has a verified off-node copy. See the runbook for exact IDs.

Do not bypass the ingress auth rollout. Legacy migration mode permits Telegram
only; unauthenticated requests must never enqueue SPI. Queue failure returns 503
for sender retry while still allowing Telegram. Headers never enter execution data.

V1 evidence: rule definitions, historical metrics, pod/job and systemd profiles,
scoped Loki error frequency, safe Tempo span/error counts when trace_id is provided,
and allowlisted runbook excerpts from main (not proof of the deployed version).
Raw log publication, automatic trace discovery and deployed-source correlation
remain explicit gaps.
Never describe those future capabilities as implemented. No automatic remediation,
alert suppression, issue closure or dry-run replay. Ambiguous writes require marker
reconciliation, not blind POST retries. Retain/keep is not a recurring backup.
