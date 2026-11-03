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
one-hour repo-scoped tokens without PR write and patches only a named Secret.
Worker uses Viewer Grafana access and a separate capped LiteLLM qwen3.8-27b key.
Dedicated SQLite PVC is NOT the n8n database; never modify n8n SQLite for this feature.

## Initial acceptance status

Implementation is initially **dry-run**, GitHub writes disabled. Unit coverage:
24 Python tests and four authenticated webhook tests. Real deployment/model,
Telegram regression and token rotation require live verification before claiming
completion. Consult the runbook and current operator checklist for later evidence.

Do not bypass the ingress auth rollout. Legacy migration mode permits Telegram
only; unauthenticated requests must never enqueue SPI. Queue failure returns 503
for sender retry while still allowing Telegram. Headers never enter execution data.

V1 evidence: rule definitions, historical metrics and scoped Loki error frequency.
Raw log publication, traces and deployed-source correlation are explicit gaps.
Never describe those future capabilities as implemented. No automatic remediation,
alert suppression, issue closure or dry-run replay. Ambiguous writes require marker
reconciliation, not blind POST retries. Retain/keep is not a recurring backup.
