# Socrat bot

> Current infrastructure context (7 November): [NetBird](network-access.md),
> [native identities](identity-current-state.md), [release/Argo](cluster-deploy.md).
> The latest SPI target receipt is [actual deployment / partial acceptance](spi-incident-triage.md#actual-activation-and-partial-acceptance--7-november-2026):
> two of three original cards verified, one blocked; no new retry authorization.
> Older OFF/pending/push-blocked checkpoints below do not supersede that receipt.
> This wiki refresh sends no messages, retries no jobs and changes no workflow.

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


### Historical SPI link pre-activation checkpoint — 2026-11-04 09:52 UTC

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


### Current SPI original-card acceptance — 2026-11-04 10:49 UTC

Links now ENABLED in production; this supersedes the historical disabled/push
blocker above. Full evidence: `llm-wiki/spi-incident-triage.md`, current acceptance.
Real SPI26 firing root link revision1 and its exact primary resolved comment
https://github.com/alchemmist/homelab/issues/26#issuecomment-6628732862 revision2
were acknowledged on BOTH original copies. Same copy IDs, generation1, resolved
status, desired/applied2, exactly one SPI anchor. Stale revision1 rejected409;
idempotent revision2 reassertion acknowledged both copies. No test messages sent.
Native schema0009 and Argo Synced/Healthy verified. Original workflows preserved.

Also repaired missing SPI trigger webhookId: n8n showed active but returned404;
stable ID added in source and original stored graph, callback202 and real queue
progress verified.114 Python+9JS+29bot tests passed. Pending-link Grafana rule
provisioned. Queue is NOT drained; legacy unprovable cards and inference429 remain
visible pending/error, not false success. Private consistent snapshots retained.
RustFS SELECTED for a later S3 phase, not deployed; issue evidence comments remain.

### Follow-up: unsubscribe and one-time approval (pending release)

The pending bot implementation now includes `/unsubscribe` and an **Unsubscribe**
button in `/start` and alert settings. This supersedes the earlier statement that
an opted-out non-owner must request approval again. `alerts_approved` permanently
records owner approval; `alerts_enabled` controls current delivery. `/start` alone
never re-enables delivery. **Subscribe to alerts** or `/alerts on` re-enables an
already-approved subscriber without messaging the owner or replaying active alerts.
Unapproved users still need the original owner approval. A repeated old Approve
button cannot undo a later unsubscribe. Settings remain private-chat-only; VPN
opt-in, admin tier and receive tier are unchanged. New cards and escalation notices
are suppressed after opt-out (including prepared work rechecked before HTTP);
already-delivered cards continue to receive state/resolution edits. An HTTP send
already in flight cannot be recalled.

Migration `0012_alerts_approval` follows `0011_delivery_ownership`. Backfill retains
current subscribers and owners, and recovers historical approvals from
`audit.event='alerts.approve'` whose actor is the target Telegram ID. VPN membership
alone does not grant approval. Owner approval remains required only the first time.
Final combined verification: PostgreSQL17 **128 passed, 15 conditional skips**;
scoped Ruff, compileall, diff checks and deterministic wiki rendering passed.
This is local implementation/test evidence, not a production rollout claim.

## Sent mailing edits — released and verified (2026-11-05)

Bot commit `cacc304a9cd521c7aaf8514db3465e688d001d33` is deployed through the
normal GitHub Actions → Harbor → GitOps path. Release run:
https://github.com/alchemmist/socrat-bot/actions/runs/42078994256 . CI reported
**149 passed, 15 conditional skips**. Live image digest:
`sha256:8fcea4bc31d582c9f55f1ee2578d6ee099ae883261671ef81fc61fa449d431ff`.
All three component rollouts completed, Argo was Synced/Healthy, healthz returned
`{"ok":true}`, and production migration head is `0013_broadcast_copies`.
This also confirms the earlier escalation/unsubscribe migrations are deployed;
it does not by itself prove every live escalation scenario.

### Usage

Owner-only, private chat:

- Reply to the bot's delivery summary with `/mailing_edit NEW_TEXT`.
- Alternatively `/mailing_edit UUID NEW_TEXT`.
- `/mailing_edit` alone lists owned sent mailings and marks entries with no saved
  receipts unavailable. Delivery summaries include the mailing UUID.

New text remains plain text; multiline/Unicode is preserved, with Telegram's
4096 UTF-16-unit limit. The canonical command registry updates owner autocomplete;
`/mailing_edit` was verified with Telegram `getMyCommands` for fallback/en/ru.
No BotFather command-list maintenance is required.

Immediate, scheduled, and legacy API/action delivery now persist each confirmed
original `chat_id`/`message_id` in `broadcast_copies`. Edits address those copies,
not the current VPN audience, and never send replacement messages. Per-copy
applied text/error allows partial retry; Telegram "message is not modified" is
success. Results distinguish updated/failed/skipped. Accepted sends whose receipt
could not be persisted are reported as untracked with recovery details and an
explicit **Do not resend** warning, not falsely counted as rejected sends.

A durable five-minute edit lease serializes ordinary edits and fences persistence;
no DB transaction is held through edit HTTP. Finite leases do not provide an
exactly-once guarantee under arbitrary process suspension. Immediate/scheduler
claims use compare-and-swap to avoid simultaneous sends. The normal legacy callback
releases its transaction before HTTP; the direct `apply_action` legacy fallback
explicitly commits before its network call.

### Historical limitation and actual acceptance

**Old mailings cannot be reconstructed from Bot API chat history.** This rollout
found three historical sent mailings and zero saved original copies; no IDs were
invented, scanned, or guessed. `messages.getHistory` is a user-only MTProto method,
not available to a bot token. A recipient's reply can expose the original message
ID, but a `/fix` recovery workflow was only discussed and is **not implemented**.
The requested old VPN notice was not edited, and no correction broadcast was sent.
New-send permission must not be inferred from permission to edit existing copies.

Released-image live smoke used a fresh temporary SQLite DB (production DB read-only
only to obtain the owner identity), with outgoing Telegram restricted to the owner:
one explicitly marked test send, one in-place edit confirmed by Telegram with the
same message ID, reply-to-summary command parsing, explicit-UUID retry without
resend, and group/non-owner rejection. The single test message was then deleted.
No other VPN subscriber received a test, no real mailing was edited, and no
production mailing rows were written by the smoke. Production counts remained
three old mailings / zero saved copies afterward.

Local Kubernetes config still targeted an unreachable LAN API192.168.0.23 during
this check. The existing NetBird endpoint worked with an explicit invocation:
`kubectl --server=https://10.250.0.3:6443 ...`. No kubeconfig, credentials, or cluster
network configuration was changed to perform verification.

### Editable mailing history UI — released (2026-11-05)

Bot `2fe538df2d64298142a8ef323a48ae69c458d0b5`, release CI
https://github.com/alchemmist/socrat-bot/actions/runs/42082500968 : **155 passed,
15 conditional skips**. All three deployments use
`sha256:4c3c04356e83c38c78ffde4e2e413488b27326b656659fb9e8e715c81e7d9edf`;
Argo Synced/Healthy at observed homelab revision `9bef759`. Live migration head
`0014_broadcast_copy_time`.

`/mailing_edit` now lists only the owner's sent mailings that have saved original
copies. Historical uneditable entries are hidden. The default view shows at most
three newest, with UUIDs in inline code and escaped message previews in `<pre>`
code blocks. **Show all** expands the available history; large histories use
bounded Previous/Next pages, and **Latest 3** restores the compact view. Empty
history shows a short message without unavailable IDs or a verbose usage dump.
Long previews are visibly truncated; HTML entities and Unicode stay valid and
panels remain below Telegram's message limit. Every list callback rechecks owner
identity/private chat and always queries that owner's mailings.

`BroadcastCopy.sent_at` records original receipt time; edits do not change it or
move old mailings to the front. Migration0014 preserves copy identity/text and
backfills preexisting tracked copies with migration time, since older releases
had no receipt timestamps. Newly recorded copies have actual receipt timestamps.
The PostgreSQL suite and populated SQLite upgrade/downgrade preserve existing
IDs/text; multiple recipient copies produce one history entry.

Actual released-image UI smoke used isolated SQLite and one owner-only test panel.
Telegram confirmed three `pre` entities in the compact view, five after Show all,
and three again after Latest 3. Both changes edited the same test-panel message;
HTML/emoji rendering and private/owner restrictions passed. The single test panel
was deleted afterward. No real mailing was edited or sent by this smoke. A later
read-only production check observed four mailings and six saved copies; these are
production records, not smoke rows (the test used a separate temporary DB).

Direct local NetBird API endpoints began refusing connections during acceptance;
verification used the existing `ssh socrat-0 'kubectl ...'` path instead. The API
was healthy from that node; no network/credential/kubeconfig changes were made.

## Optional alert images — released and accepted (2026-11-07)

Bot release `bf50ab282fd8e5a2dd68e2471384a81a7c771fdc` includes implementation
`e3df297`, concurrency hardening `5dc5bc0`, and heartbeat-cleanup fix `bf50ab2`.
CI https://github.com/alchemmist/socrat-bot/actions/runs/42389584627 reported
**181 passed, 17 conditional skips**; the final local PostgreSQL17 suite matched.
Independent release review approved the concurrency fixes before push.
Image digest: `sha256:78fcc5631fd7b2d63a933a72412ad92c98bb3765f77429fea3f1360c56497b54`.
All three deployments rolled out, migration head is `0015_alert_images`, healthz
returned `{"ok":true}`, and Argo was Synced/Healthy at revision `d44bced`.
A protected pre-migration database dump was saved outside Git.

### API and semantics

`POST /v1/messages` accepts optional top-level `images` (up to three), each with
`mime_type` (`image/png` or `image/jpeg`), canonical strict `data_base64`, and an
optional bounded ASCII `filename`. Maximum decoded size is 4 MiB/image (12 MiB
combined). File signatures must match MIME; unknown image fields/URLs are rejected.
Image-bearing validation errors omit request values. Existing token authorization
and ingress isolation remain unchanged. Supported alert forms are `card`, `alert`,
and a singleton `alerts`; images with only ordinary `text` receive actionable400.

Example (replace placeholders; token remains private):

```json
{
  "chat_id": 123456789,
  "card": {
    "key": "cpu-high/server-1",
    "title": "High CPU usage",
    "summary": "CPU usage exceeds 90%"
  },
  "images": [{"mime_type": "image/png", "data_base64": "BASE64_PNG_BYTES"}]
}
```

Bot uploads actual multipart bytes via `sendPhoto` as replies to each recipient's
original text card, with `allow_sending_without_reply=false`. It never converts the
card to a photo caption, preserving full text, stable card IDs, Mute/Escalate,
SPI/notes, and resolution behavior. Same-slot identical bytes deduplicate; changed
bytes use `editMessageMedia` against the saved photo ID. Edit rejection NEVER falls
back to a replacement send. Omitted/null/empty `images` makes no image mutation and
does not synchronously drain or report unrelated retained attachments. A shorter
nonempty list changes only supplied slots; no delete endpoint exists. A new
incident generation starts with no retained images.

Desired bytes/revisions and generation/recipient/slot receipts persist separately.
Recipients derive only from admitted current-generation delivery intents with a
successful parent card. Escalation admits new recipients to the retained images;
subscription/tier changes alone do not add an audience. New photo attempts recheck
opt-in/generation/ownership before HTTP. The claim refreshes bytes, revision,
metadata, receipt and eligibility coherently after acquiring the shared per-card
lease, preventing stale metadata or already-recorded successes from creating
incorrect receipts/duplicate sends. Owner-fenced heartbeat and a20-second total
HTTP deadline keep ordinary live operations serialized; no network transaction.
API image submissions attempt at most one synchronous operation within2 seconds;
remaining work is retried by the independent durable media worker. Text-only
updates never wait for that media drain. Attachment statuses (`pending`, `sent`,
`superseded`) refer to the submission's immutable generation/revision snapshot,
not whichever episode happens to be current when the response is produced.

### Live acceptance and boundaries

Released-image smoke used a temporary SQLite database; production DB was read-only
only to discover the owner identity. Real Telegram traffic was guarded to the
owner and to IDs created by that test: one clearly marked text card and one PNG
chart reply. Confirmed pending→sent reporting, preserved parent reply ID, identical
image retry without duplicate, changed PNG content on the same photo message ID,
and resolved text-card ID preservation. Both test messages were deleted. No real
incident was mutated and no other subscriber received a test.

No exactly-once transport guarantee: Telegram acceptance followed by response loss
can still duplicate a new photo after lease recovery. Authorization changes after
HTTP starts cannot retract it. Validation is signature-only, not full image decode;
permanent rejection remains pending with retries. Database/backups retain image
bytes (including old generations), with no automatic GC yet; treat these as
sensitive. Global candidate enumeration is not yet paginated. Generating/selecting
Grafana graphs, browser rendering and Grafana credentials remain out of scope: the
caller supplies bytes, and the bot does not fetch screenshot URLs.

README/OpenAPI and deterministic repository docs are updated. The existing wiki
automation opened public-wiki review PR99:
https://github.com/alchemmist/homelab/pull/99 . It was not auto-merged. Homelab's
original checkout had unrelated monitoring/Traefik edits during documentation;
this handoff was committed from an isolated worktree without altering those files.

## Native Telegram mailing formatting — released (2026-11-08)

User requested that native Telegram formatting, particularly hidden clickable text
links, survive `/mailing`. Implemented in bot `5f23b76`; released head is
`ffd52ec362def31586b15c93ef3904af4687213a` (additional media-test timing stabilization).
CI https://github.com/alchemmist/socrat-bot/actions/runs/42474318589 : **186 passed,
17 skipped** on PostgreSQL17. First publication attempt had a transient Harbor TLS
handshake timeout; reran only failed publication, with no manual deployment.
Image digest `sha256:52848db3f838128371e29004bac7490cde23b3b5fd3f65e69afff5982a38c912`.
All three deployments rolled out; schema head `0016_mailing_entities`, healthz OK,
Argo Synced/Healthy at `552e803`. Protected pre-migration backup outside Git.
Independent exact-diff review approved. Original homelab monitoring/Traefik edits
were preserved; this record uses an isolated documentation worktree.

### Behavior

Owner composes `/mailing BODY` in one Telegram message and uses Telegram's native
editor to apply links/bold/italic/etc before sending. The bot reads original
message entities, not reconstructed command arguments. Formatting persists through
native-formatted owner body preview, immediate/scheduled/legacy-approved delivery,
and receipt-only `/mailing_edit UUID BODY` or reply edits. No HTML/Markdown parse
mode; literal markup stays literal. Unicode/emoji offsets use UTF-16 boundaries.
Semantic entities crossing the removed command/UUID prefix are dropped rather than
retargeted; style entities crossing the prefix are clipped. Internal/trailing body
whitespace and newlines survive; leading command-separating whitespace is stripped.

Migration0016 adds `Broadcast.entities` / `BroadcastCopy.applied_entities` JSON with
non-null empty-list defaults/backfill; populated SQLite and PostgreSQL upgrade,
downgrade and re-upgrade tests preserve old receipt IDs/text/timestamps. Formatting
metadata (hidden URLs, language, text-mention User, custom-emoji ID) round-trips.
Formatting-only edits are detected even when text is unchanged; explicit empty
entities remove old formatting. Partial failures retain previous applied state;
retry skips reconciled copies. Existing finite edit ownership, original saved
receipt audience, no replacement send, and no unsolicited old-mailing edits remain.

Owner preview is now TWO messages: the fully native-formatted body, then the
existing scheduling controls. History intentionally remains a bounded/escaped
plaintext preview; it does not reproduce hidden clickable links. Internal HTTP
broadcast API remains plaintext (no entities field added). Telegram is the final
validator for entity combinations/features. See bot `docs/telegram-mailing-formatting.md`.

### Acceptance and test limits

Released-image smoke `/tmp/socrat-mailing-formatting-live-smoke.py` used temporary
SQLite; production DB was read-only solely for owner lookup. Only owner's chat was
allowed by transport guards. Telegram confirmed exact hidden text-link and bold
entities in the body preview and one delivered test copy, including emoji before
the link; formatting-only edit changed URL/bold to italic on the same original
copy ID; identical retry made no request; reply edit with empty entities removed
formatting. Two test messages were deleted. Scheduling controls were intercepted
instead of leaving live buttons referring to isolated DB records. No real mailing
record/copy was changed, no production DB writes, no other recipient sends.
Scheduled/legacy approval paths were covered by mocked automated tests, not real
mass mailings.

Worker's native host PostgreSQL test run had10 existing media failures reproduced
on pristine pre-formatting `bf50ab2`; do not attribute these to mailing formatting
or claim non-UTC host-PG compatibility. Parent's independent Docker PostgreSQL17
suite passed186/17, matching CI; production `SHOW TIMEZONE` is `Etc/UTC`.
Initial CI also exposed the known overly tight media heartbeat test deadline
(120ms for two real DB renewals). `ffd52ec` extends its TEST-only deadline to1s,
retaining deadline, concurrent exclusion, finite lease, heartbeat and cleanup
assertions. Production media behavior did not change in this follow-up.

## SPI edits preserve alert keyboards — production fix (2026-11-11)

User reported `SocratControlPlaneOnBattery` / socrat-1 at10:17:50 Europe/Moscow:
photo, Level20, SPI link, missing Mute/Escalate. Root source defect was a special
SPI branch in `escalation.prepare_work` that built an edit body WITHOUT
`reply_markup`, bypassing shared desired keyboard logic. Native-photo adaptation
then emitted `editMessageCaption` without buttons. Source regression tests fail
on the original baseline; a real owner-only isolated Telegram negative control
proved that omitting markup removes the server-side keyboard.

Fix `449d5de` removes that bypass: SPI updates/retries use shared authoritative
`CardDelivery.buttons`, current pending silence actions, and escalation policy.
Current-generation active eligible cards keep buttons across text/caption/media
edits, graph upgrades and overflow replacement. Resolved/muted/old-generation
cards explicitly have no actions. SPI equal-text/revision retries still edit and
can repair missing keyboards; old generation/identity/ownership fences remain.
Parent review found a diagnostic-failure cleanup issue; follow-up `0c95540` makes
logging best-effort so a failed handler cannot override success or leak heartbeat.
New regression checks both accepted result and no remaining tasks inside the loop.

Released head `0c95540b71c9d28da0bc250324f3a146639c82af` via normal CI/GitOps:
https://github.com/alchemmist/socrat-bot/actions/runs/42984357610 . **303 passed,
17 skipped** in CI, matching parent's final Docker PostgreSQL17 suite. All three
deployments rolled out; healthz OK, Argo Synced/Healthy at `e449702`.
Image `sha256:021be4ee3c6165e79ca90c21362dee6794f1586ad2b3de84e7db5ccbd09ee2e8`.
No migration: existing schema stays `0018_graph_jobs`. Protected pre-release dump
outside Git. Original homelab checkout has concurrent n8n migration edits; this
handoff used an isolated worktree and did not alter them.

### Actual incident evidence / repair boundary

Read-only production query located the immutable SPI-episode key (card reference
`8d9abee4626d6dff8e22`) and five saved photo copies. At08:02Z the incident was
firing/generation1/Level20, users enabled, no mute marker, desired buttons15m/30m/1h,
three pending silence actions created around07:17:46Z, applied=desired content
revision4 and link revision1. SPI outbox entries were done. This supports the
reported missing-display problem rather than missing action intent. Existing HTTP
logs do NOT contain historic payload/markup, so exact historical Telegram request
attribution is not claimed from logs alone. Outbox `available_at` is not a delivery
timestamp and must not be used as one.

A targeted repair script was prepared to reapply the same SPI URL/revision through
the fixed endpoint to ONLY these five saved copies, requiring identical caption,
graph, identities, active generation and expected markup. Preflight found that the
incident had meanwhile naturally become RESOLVED, all five copies already at
revision6. It aborted BEFORE enqueue/DB mutation/Telegram HTTP. Do NOT claim these
five active keyboards were manually repaired: restoring Mute/Escalate on their
now-closed cards would be wrong. No replacement/rebroadcast was performed.

### Live acceptance / OTel logs

`/tmp/socrat-alert-keyboard-live-smoke.py` ran the released image with temporary
SQLite and strict transport guards allowing only marked owner-only test photos and
their returned IDs. Observed real Bot API keyboard counts4 →0 (deliberate omitted
markup negative control) →4 (same-revision fixed SPI retry) →4 (newer SPI URL),
always same photo ID; all test messages deleted. A first harness attempt used an
unchanged URL for the newer revision and treated Telegram's legitimate not-modified
response as failure; cleaned that photo and corrected the harness to vary the URL.
No production incident mutations or other-recipient test sends.

Existing OTel ingestion was already working: mTLS query from provisioned Grafana
Loki datasource found171 bot records in07:16–07:23Z under
`{service_name="socrat-bot"}`. No infrastructure reconfiguration/exporter was needed.
Old records only had HTTP status/duration, insufficient for button attribution.
Added static `card delivery` JSON events with allowlisted kind/method/outcome,
generation/content/link revisions, button_count, and20-hex SHA256 card_ref. No raw
key, chat IDs, callbacks, URLs, message text, secrets, exception strings or payloads.
`accepted` means durable dispatcher completion, not independent client rendering.

A separate owner-only OTel producer probe (`/tmp/socrat-keyboard-otel-probe.py`)
routed its actual delivery logger to PID1 stdout: kubectl-exec stdout by itself is
not a container log stream. The ordinary agent→OTLP→Loki pipeline retained two
probe events (`fc144ef931adbdb72859`), sendPhoto and SPI editMessageCaption, both
accepted/button_count4. Its single photo was deleted; isolated SQLite only. Loki
also contained unrelated concurrent real dispatcher events with button_count4;
those are not smoke DB records or parent-generated real alert writes.

Grafana Explore / Loki query:

```logql
{service_name="socrat-bot"} |= "card delivery" | json
```

Local evidence: `/tmp/socrat-keyboard-production-evidence*.json` (0600),
`/tmp/socrat-loki-evidence.jsonl`, `/tmp/socrat-loki-keyboard-probe-confirmation.jsonl`.
No secrets were printed; Grafana-provisioned mTLS leaf credentials stayed inside
that container in anonymous in-memory file descriptors for read-only Loki queries.
