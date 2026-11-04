# Socrat bot

Release contract matches [cluster-deploy.md](cluster-deploy.md): the image lives in Harbor, the version lives in Git, and Argo CD syncs on its own. CI does not call `helm upgrade` and does not write Helm parameters.

## Layers

Three layers. Secrets do not go through Git.

1. **Bot repository** `alchemmist/socrat-bot` builds one image, `harbor.socrat.alchemmist.xyz/homelab/socrat-bot`. Three processes share it: `python -m socrat_bot`, `python -m socrat_bot.updater`, and `python -m socrat_bot.broker`. The Telegram token, Postgres password, and `INTERNAL_TOKEN` live only in the cluster Secret `socrat-bot-env`. The chart does not render that Secret.
2. **Homelab** holds the chart, values, and Application. `deploy-to-socrat` changes only root `image.tag` and `image.digest`. Postgres stays under `postgres.image` (`postgres:17`).
3. **n8n** receives the Alertmanager webhook and calls internal `POST /v1/messages`. The bot token is not stored in Grafana. `X-Internal-Token` is the n8n credential `Socrat bot internal`.

## Addresses

- Public Telegram webhook: `https://bot.socrat.alchemmist.xyz/telegram/webhook`. Ingress exposes only `/telegram`.
- Internal API: `http://socrat-bot.socrat-bot.svc:8080`.
- The bot and sudo-broker use the host network on `socrat-2` (host ports 8082 and 8081) because pod egress from `socrat-3` cannot reach `api.telegram.org`. Services still publish port 8080.
- xui-updater stays on the pod network and probes the 3X-UI Service on port 2053.

## Where it lives

| What | Path |
| --- | --- |
| Chart | `charts/socrat-bot` |
| Release values | `deploy/socrat-bot/values.yaml` |
| Application | `deploy/argocd/apps/socrat-bot.yaml` |
| Alertmanager receiver | `deploy/platform/kube-prometheus-stack/values.yaml` |
| Workflow | `docs/n8n/socrat-bot/workflow.json` |
| Import notes | `docs/n8n/socrat-bot/setup.md` |
| sudo client | `ansible/files/socrat-sudo`, `ansible/files/socrat_sudo`, `ansible/playbooks/socrat-sudo.yml` |

Application: project `default`, namespace `socrat-bot`, `parameters: []`, `prune: false`, `selfHeal: true`. Pull secret `socrat-bot-harbor-pull` is created by the operator.

## sudo-broker

The broker stores a request and does not run the command. `socrat-sudo` posts `user`, `node`, and `argv` with `X-Internal-Token`. After Allow, the client runs `sudo` with that argv once. Deny and timeout do not exec. `/etc/socrat-sudo.env` on `socrat-2` is mode `0640`. The playbook does not write the token and does not change sudoers.

`TELEGRAM_OWNER_ID` has to be set before buttons, broadcasts, and sudo approvals work.

## SPI incident triage alongside Telegram

The original **Socrat Alerts** workflow now uses an authenticated native trigger
that persists triage jobs before acknowledging the group and excludes request
headers from execution data. Telegram delivery remains the fast path. A worker
handoff failure requests retry with HTTP503 without preventing Telegram processing.
Unauthenticated requests return HTTP401; legacy migration mode must stay disabled.

Slow diagnosis and GitHub publication run in the separate **SPI Incident Triage**
workflow. The bot itself does not need the model key or GitHub App private key.
All generated `[SPI]` titles, descriptions and comments MUST be English. SPI writes
are enabled after acceptance; the unrelated blog remains write-disabled.

Architecture, limits, exact IDs, real issue/comment evidence and recovery:
[spi-incident-triage.md](spi-incident-triage.md). This GitHub-token broker is distinct
from the Telegram sudo-broker described above; do not conflate their credentials,
permissions or approval mechanisms.


### Event-driven SPI migration — PENDING

SPI triage is designed to wake through an authenticated native n8n Webhook, not an
every-minute Schedule Trigger. Native ingress commits `/enqueue-group` to the
existing durable worker SQLite queue before signaling; no execute-subworkflow or
Redis/Postgres migration is needed. This does not change the bot's own Postgres.
The worker coalesces wakes and POSTs `{}` to the fixed internal URL
`http://n8n.automation.svc.cluster.local/webhook/spi-incident-triage-dispatch` with
`X-Worker-Token` = existing `WORKER_TOKEN`. Webhook `headerAuth` reuses the
`SPI_WORKER_CREDENTIAL_ID` / `httpHeaderAuth` mapping used by `/claim`, with immediate
`onReceived`; no alert-supplied network target. Each execution claims one job.

Durable reservations/backoff, `/claim` acknowledgment and exclusive processing
leases handle lost/ambiguous wakes. Startup recovery and the worker's internal
retry/lease/reservation timer resume due work; an empty queue creates no n8n
executions. Completion/failure signals the next due job. This is not exactly-once
publication or guaranteed diagnosis; ambiguous GitHub writes require review, not
blind retries. See the triage runbook for backlog recovery.

- [ ] Parent deploys with `SPI_DISPATCH_ENABLED=false` during staging, preserving n8n
  identity, workflow IDs, credentials, encryption key/PVC, SQLite and Telegram path.
- [ ] Parent activates the event workflow before enabling dispatch, then verifies
  lease exclusivity, empty-queue silence, backoff and lost-wake recovery.

These are pending checks, not deployment/test claims. Do not publish test incidents
or send Telegram tests. The blog remains separately write-disabled. SPI text
artifacts currently remain in issue comments; S3 storage is not deployed.

Security integration: dispatch uses CUSTOM.socratSpiDispatchWebhook with the
existing httpHeaderAuth credential, not the built-in Webhook (which emits incoming
authentication headers). Only `{dispatch:true}` enters execution data. Credential
comparison occurs in the trigger; POST acknowledgement is immediate. Worker egress
is restricted to automation/app=n8n pod TCP5678 for the fixed callback.


### SPI original-card link integration status — 2026-11-04

Historical event-dispatch staging checklists above are superseded by deployed,
enabled event dispatch; their individual acceptance scenarios are not all claimed
verified. Telegram SPI-link delivery is a separate feature and remains OFF in the
last verified runtime. Full implementation and acceptance status:
`llm-wiki/spi-incident-triage.md`, “Verified status — 2026-11-04”.

Native bot implementation `fe67913` and live schema `0009_spi_desired_revision`
provide immutable `/spi/<episode>` keys, firing/resolved monotonicity, shared
per-key mutation locks, exact-copy guards, and accepted desired revision fences
persisted BEFORE network edits, separate from applied-copy revisions. API contract
is in the ordinary human wiki `wiki/content/platform/socrat-bot.md`.

Original Socrat Alerts `b2TlucyOTiZP9CzN` was updated/reactivated in place. Receipt
preparation now runs in Code via `itemMatching(index)`; cross-node HTTP JSON
expressions had failed at runtime. Four real retained receipts were replayed
without sending messages: each callback observed two copies; episode identity was
verified. Do not confuse this with proof that SPI links have appeared in Telegram.
Bot suite:29 tests passed; parent SPI suites:114 Python +9 JS passed.

Homelab deployed revision was `cac9598`, all three applications Synced/Healthy,
with links disabled. Local activation commit `49ad745` was rejected by GitHub
server-side write failures and was confirmed absent remotely. Pending: activation,
real exact-target/all-copy edit acceptance, pending-link Grafana rule, final backup
and acceptance documentation. No new approval is implied or required merely to
retry the already-authorized rollout after resolving the external blocker.

Never infer associations for historical legacy messages lacking immutable proof;
never republish GitHub/model reports to retry a Telegram link. Service8080 targets
native hostNetwork API8082. Preserve the isolated bot checkout and unrelated dirty
operator checkout. Blog stays write-disabled; S3 migration remains separate.
