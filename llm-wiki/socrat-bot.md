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

## Manual alert escalation — implementation ready, release BLOCKED (2026-11-04)

This section describes the implemented **pending release**, not the running bot.
Bot checkout `/Users/antonmoss/code/socrat-bot` has two local commits based on
upstream `fe67913`: `4d86ad5` (escalation/durable delivery) and `784b0a3`
(SPI integration and PostgreSQL CI). At the last verified publication attempt,
remote bot `main` was still `fe67913`; neither pending commit had been pushed.
No new image, production escalation migration, or live escalation acceptance is
claimed. Recheck GitHub/Argo/schema before continuing; another session may deploy.

### Approved behavior

- Explicit configured tiers `ALERT_LEVELS=10,20`; smaller numbers mean higher
  responsibility. Tiers are not inferred from the current user population.
- Assigned `admin_level` is independent of personal `receive_level`. The owner
  starts at admin 10 / receive 20; other existing users at 20 / 20. Existing
  `alerts_enabled` approval flags are preserved. Newly approved users normally
  start at the configured lowest-authority tier.
- A new incident starts at the maximum tier. An enabled approved subscriber gets
  it when `receive_level >= incident.level`. A receive setting may select only
  an existing tier numerically >= the assigned admin tier. Changing settings
  **does not replay active incidents**. Delivered copies continue updating through
  resolution; original pending delivery intents remain retryable. No eligible
  recipient means no send, never fallback to an arbitrary caller `chat_id`.
- Full-width **Escalate** sits below the Mute row. It advances exactly one tier,
  globally, and rejects an empty next assigned admin tier. Actor must own a
  delivered current-generation copy, be an enabled subscriber, and have assigned
  admin level <= the current stage. Expected stage/generation plus transactional
  compare-and-swap prevent concurrent taps from skipping a tier. Lower-authority
  copies lose Escalate after advancement; final-tier copies have no Escalate.
- New destination recipients get a full card. Existing destination-assigned
  admins get an extra short notification linking their existing card, except
  the actor. Editing alone would not create a fresh Telegram notification.
- Ordinary firing repeats retain escalation. Resolved updates all delivered
  copies and removes buttons; a new non-SPI incident generation resets to the
  initial tier. Old callbacks, including delayed Mute completion, cannot mutate
  new-generation cards. Terminal immutable SPI episodes never refire.
- Mute remains a global Alertmanager silence, independent of escalation; muted
  cards retain the existing no-buttons policy. Notes and desired SPI links survive
  escalation and ordinary updates. No timer-based escalation or severity routing.

### Commands and internal API

Private chat only:

- `/alerts`: current subscription, assigned tier, receive tier and allowed buttons.
- `/alerts level 10`: owner receives only final-tier escalations.
- `/alerts level 20`: owner receives the full initial stream again, without backlog.
- `/alerts off` / `/alerts on`: existing approval rules remain; disabled non-owner
  requests owner approval again through `/start`.
- Owner-only `/alertlevel TELEGRAM_ID N`: assign an existing user's admin tier;
  clamp an incompatible receive tier, without approving or replaying incidents.

`GET /v1/audience` adds `admin_level` and `receive_level`. Card metadata adds
`generation`, `level`, and `escalation_history`. Internal token and cluster-only
exposure remain unchanged. Runtime API remains handwritten; `openapi.yaml` and
`scripts/render_wiki.py` generate the ordinary public wiki through the existing
reviewable-PR automation, not this LLM wiki.

### Delivery, migrations, SPI compatibility

`incidents` stores common generation/stage/history. Initial original-recipient
intents and content commit atomically with incident creation; conflict-safe insert
and row locking support simultaneous first webhooks. Escalation audit and outbox
jobs commit in the same transition transaction. All card writers use the durable
`CardDelivery` dispatcher: per-card/recipient leases, ownership fencing and content
revisions serialize successful sends/persistence across processes and repair newer
content received during HTTP. Delivery transactions close before Telegram HTTP.
A background worker retries durable work after restart. Telegram acceptance followed
by timeout or crash before persistence can still duplicate a send: **at least once,
not exactly once**.

Pending migration chain, preserving upstream SPI migrations:

`0007_card_note → 0008_spi_link_revision → 0009_spi_desired_revision → 0010_escalation → 0011_delivery_ownership`.

0011 adopts existing cards and preserves accepted desired versus applied SPI link
revisions, including unfinished-link recovery. `expected_copies`, monotonic
`revision`, desired fences committed before HTTP, and accurate `updated`/`pending`
acks remain supported. Bot and sudo broker serialize schema startup with the same
PostgreSQL advisory lock; CLI Alembic uses that lock too. Old binaries must not
run concurrently with new lease-aware card writers. Current chart uses
`strategy: Recreate`, `replicaCount: 1` for each component.

### Verification and completion checklist

- Parent independently ran final PostgreSQL 17 suite: **118 passed, 15 conditional
  skips**. Coverage includes concurrent taps/first webhooks, recipient ownership,
  failed initial sends/restart, same-stage content races, immutable SPI episodes,
  revision fences, populated migrations, and concurrent schema startup.
- Scoped Ruff checks, runtime correctness lint, compileall and diff checks passed.
  Legacy whole-repository broad lint findings were not silently treated as clean.
- Independent final review: no remaining release blocker found in reviewed code.
- Pending CI change runs PostgreSQL 17 tests on every release before the existing
  Harbor → deploy-to-socrat → GitOps chain. No manual Argo sync or image patch.
- Protected pre-migration DB backups exist under
  `~/.local/state/socrat-backups/` outside Git. Never commit dumps or secrets.

Publication was blocked by intermittent GitHub SSH authorization failures, then
server `commit_refs`/HTTP500 failures during a GitHub-reported outage; subsequent
bounded SSH-over-443 attempts again failed `Permission denied (publickey)`.
Existing `gh` HTTPS OAuth credential lacks `workflow` scope needed to publish
`.github/workflows/ci.yaml`. Do not silently widen credentials or drop CI changes.

To finish: restore authorized push, verify upstream ancestry, push both commits,
require successful exact-SHA CI, inspect GitOps image digest and all three component
rollouts, verify live schema0011 and grouped user defaults without printing private
identities, then run safe release-image smoke. Prepared smoke script
`/tmp/socrat-escalation-live-smoke.py` uses a fresh isolated SQLite DB, a simulated
lower-line actor, real Telegram sends **only to the owner**, and deletes only its
own marked test messages. It must be reviewed/recreated if the temporary artifact
is absent. Never send a synthetic production `/v1/messages` assuming `chat_id`
isolates fanout; never create real silences for acceptance. No production data or
Telegram messages were changed during the pending release verification.
