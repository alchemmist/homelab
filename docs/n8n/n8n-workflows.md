## CURRENT 27Nov — Source Control to GitHub + log streaming to otel-loki LIVE

Two enterprise features activated on the fork (license gates removed earlier):

**Git sync (Source Control).** Settings → Source Control connects to the private
`alchemmist/n8n-workflows` repo (branch `main`) over SSH. The key pair lives only
in the n8n database; the public half is the read-write deploy key
`n8n-deploy-key`. Initial push commit `6f7b95c0` carries all workflows, tags,
variables and credential stubs without secret material. Public key reference:
`~/.config/homelab/n8n/git-source-control.json` (no private key on disk).

**Log streaming to otel-loki.** n8n UI Log Streaming destination (Webhook →
`http://127.0.0.1:9123/event`, workflow started/success/failed + node
executions + audit events) feeds the in-pod `otel-log-bridge` sidecar added in
chart `charts/n8n` (`f27c7fe04`; probe widened `f8b76f9d8`). The stdlib-only
bridge converts each event to one Loki entry (labels `job=n8n`,
`source=n8n-log-streaming`, `event`, `workflow_id`) and pushes over the
homelab otel PKI: dedicated client leaf `otel-app-tls-n8n` mirrored into the
automation namespace by the existing `otel-application-credentials` CronJob.
The target Secret had to be bootstrapped once manually (resourceNames-scoped
GET 403s on a missing Secret); the mirror keeps it in sync afterwards and the
bridge reloads its SSL context after leaf rotation, so no deployment reload is
wired. End-to-end verified inside the cluster with real events
(`n8n.workflow.started`, executionId 90718, workflow "Socrat Alerts").

## CURRENT: 17Nov — SSH-egress replaced by VPN-as-service

The owner rejected separate SSH tunnels as the application egress architecture.
The current n8n uses its own dedicated native 3x-ui client **svc-n8n-google, ID40**,
its subscription and the official Xray-core sidecar. Path: Russian node → standard
Moscow VPN-as-service entry → NL. `wg-socrat` stays infrastructure and
does not replace service-identity. [Standard runbook](../network/vpn-egress/service-vpn-egress.md).

Source5b722c5c, fresh global nativepending[] + SPIowner/processing/paid0,
48 Node tests; Pod n8n-7bc974f784-cbbfn Ready2/2, ArgoHealthy. The subscription
is fetched at startup via an init through the native JSON endpoint, not hot-refresh.
Group `services`; by owner decision quota0/expiry0 — no quota and
no automatic expiry. limitIp1 retained; accumulated traffic not reset.
All7 graphs/settings/credentialrefs/static/pin/activities/PVC/Secret retained.
Google-only scope and end-to-end TLS kept, GitHub/other services direct.
The old n8n SSH-sidecar was removed, the separate SSH-key revoked, its2Secret removed;
the shared registryrobot was not revoked. Venice was not changed; its SSH variant is a
deviation, NOT a template for new services. The lower SSH-acceptance records are history, superseded.

## CURRENT17Nov owner-approved follow-up: Google NL egress + SPI compaction LIVE

Supersedes the earlier PARTIAL/no-egress status BELOW; keep it as incident history.
[Authoritative follow-up](google-only-nl-egress-20261117.md).

Owner authorizedGoogle-onlyNLegress and askedreuseVenicepattern. N8Nnowusesown
pinnedSSHidentityandTWOstaticloopbackforwards onlywww/oauth2Google443, NOTVenice
privatekey/profileoragenericexit. Originalend-to-endTLS/SNI/CA/nativecredentials
retained, noHTTP/OAuthPOSTreplay. Otherworkflowsnative. NoVPN/route/MTU/DNSchange.
InitialmissingHarborpullcredentialcausedshort1/2Readydowntime/49624error; corrected
viaGit2f26a12fafterNEWfreshglobaldrain. Noalertmute/historycleanup. Node5Pod
n8n-8679f69fc9-x8j9rReady2/2,restart0,45Nodetests,realstrictTLS/negativeSSHtests,
all7nativegraphs/settings/static/pin/activities/PVC/Googlecredentials unchanged.
VeniceUID/specunchanged. FiniteCalendar14naturalsuccesses08:37–08:50; laterfinal
sampleinprivatehandoff. Noovernight/voice/refreshPOSTacceptanceclaim.

SPI8c89246LIVE viaexplicitrelease44050085445/freshglobaldrain: ALWAYS rawmetrics→
observedextrema/trend→lossless100/100rowtablecompaction→boundedprose→tokenfit→
finalmodel. Actualoriginalcontext25618vs39595reservation underSAME30000budget,
same10artifactIDs/candidate174,model/networkcalls0forproof.469nativeCItests0skips;
image185bd5cd…aec71e6d,exactruntimehashes/health200/ArgoHealthy. NoextraLLMcall,
paidbudget/attempt/backoff/deadlinereset/state-schema/workflowgraphchange. Full
snapshotsunaltered; unknownformatsfailclosed; sensitivekeyredactionandtable
identitiesprotected. Finalfallbackprefixstilldisclosesomissions. Newlossless
naturalreportacceptancePENDING. Botholdmorningcontextjobsnaturallycompletedwith
reporttrue/attempt8BEFOREthisnewrelease(2cfc5ccbprefix16),soNOTitsacceptance.

## CURRENT17Nov: morning failures, Calendar PARTIAL / SPI context fix LIVE

Calendar initial16Nov acceptance was finite, notall-nightstability. Morning
four-candidate exhaustion exposedmultipleflakyGoogleaddresses.0ab81dac fixes
candidatecoverage(max8/two pre-HTTP sockets/same9.5sbudget), BUT subsequent
5naturalruns stillfailedall8; do NOT callCalendarfullyfixed. Source/path-dependent
TLSfailures reproducedoutsidePod, while same8IPs allverifyfromNL. Headers-only
capture confirmsClientHelloretransmission/nopeerTLSdata onbadflows; precise
provider/Google/DPIcauseunproven. Network/MTU/VPN/DNSunchanged; noSNI/TLSbypass.
A narrowlyprivateGoogle-onlyNLegress wouldbeaseparateroutingdecision, NOT deployed.

SeparateSPI2cfc5ccb nowlive imagec25911c5…e2b2cabe4: explicitmodel-onlymetricseries
projection fixes100seriescontext(39595→16810reservation) WITHOUT extra modelcalls/
quota/deadlineresets or changingfullstoredoriginals/IDs.464nativeCItests0skips,
freshglobaldrain, SPIactivityrestored. Twojobs retainoriginalfuturebackoff; new
naturalreportacceptancePENDING. OneLLMnetworkerroralreadyrecovered naturally.
[Full current evidence/status](google-calendar-transport-20261117.md).

## CURRENT16Nov23:22MSK: Calendar TLS address failover LIVE

Follow-up research isolated a CURRENT DNS-provided GoogleIPv4 whoseTCP connects
butTLS stalls, while7other addresses work; reproduced outsidePod and acrossTLS
versions too. Not proof of provider/MTU/CNI fault; forcingIPv4/DNS-only insufficient.
Read publicwiki VPN and the network intent in docs before selecting no-network-change
correction. Scoped native HTTPS connection failover now enabled byGit9a014aa2:
fresh existing-resolverDNS, originalSNI/CA, max4pre-HTTP TLS candidates under9.5s;
HTTP receives socket only AFTER verifiedTLS. No HTTP/OAuthPOST replay, TLS bypass,
IP pin, VPN/routing/MTU change, nodeRetryOnFail or timeout increase. IDs/credentials/
graph/settings/pin/static/history preserved; googleDnsEnabled remainsfalse.

Fresh global natural drain+SPIowner/processing/paid0 beforepush; related activities
restored. ArgoSyncedHealthy, exactruntimehashes. Firstnatural48686 succeeded with
Google4827ms and TWO observedpre-HTTP failovers; not a voice-delivery test or
long-term reliability promise. Historical15Nov/12Nov failures below retained.
[Diagnosis, design, tests and acceptance](google-calendar-transport-20261116.md).

# n8n: development, operation and workflow authorization rules

## CURRENT15Nov: Google Calendar OAuth recovered; latency caveat

The user reconnected the existing **Google Calendar account** at 19:22 MSK.
After that, 8 scheduled Calendar executions succeeded 19:24–19:33; no new errors.
A new backup was independently verified on3 (hash/SQLite/key/source5/7workflows/10creds).
But two runs were cancelled by the existing 110s timeout; do not claim full stability.
The DNS probe passed, and certain authorization-free Google HEAD probes
sometimes hit the 6.5s deadline at TLS after a successful TCP, on both IPv6 and IPv4.
The root cause / relation to the 110s cancellations is unproven; googleDnsEnabled:false,
network and timeouts preserved.
No manual speech runs, reset/SQL, alert disabling or timeout increase.
[Evidence and boundaries](google-calendar-auth-20261115.md).

Contract for agents and the operator. Updated: **3 November 2026**.
Related document: [smart-home automation architecture](../applications/smart-home/smart-home-automation.md).

## Automatic binding of new JSON templates — offline policy

Creating a workflow in code is accompanied by the check
`uv run python ci/check_failure_alerts.py`; if a binding is missing —
the same command with `--fix`, review/commit JSON and a normal native sync. No CronJob
or automatic change of live n8n. Detection of new files is recursive over
roots in `ci/quality/n8n-workflow-policy.json`; another explicitly given handler is not overwritten,
the canonical Error Trigger is excluded strictly by path/name/type without recursion.
CI does not see UI-only workflows until they are exported to sources.

The new CI is defined in **qg.yaml**, outputs were produced by `uv run qg generate`, freshness by
`uv run qg validate`. CLI/provider0.1.8 are pinned identically, runtime SHA from the official
quickstart. CI only verifies; the fix is invoked by the developer/agent. At the moment
qg.yaml was introduced it was absent in both repos; this is a bootstrap per the migration guide,
the old checks are kept until PR parity, the privileged release was not moved into the graph.
Do not treat a local generate/validate as acceptance of a trusted publisher or a change to
required branch checks. [Process and commands](workflow-policy.md).

## Notification about a failed execution — 9 November 2026

A shared **Workflow Failure Alerts** (`iZn7biFh6321a1w8`) was set up: native
Error Trigger → safe metadata projection → the existing Socrat bot
`/v1/messages` directly. All six current business workflows reference it
via `settings.errorWorkflow`, including Socrat Alerts. The handler itself does not
reference itself and does not go to Socrat Alerts/SPI — there is no delivery recursion.

The notification is in English: workflow, execution ID, failed node (if any),
a direct protected n8n link. Raw error/message/stack, headers and payload do not go
to Telegram; details are available inside n8n. Body storage is disabled for the handler;
native input data may temporarily exist until completion/pruning.
This is a single failure event, not a 20-minute error window and not an exactly-once promise.

6 bindings and the published settings of active workflows were checked, 9 offline tests.
Activity was preserved: 5 active, SPI **was already inactive**; it was not enabled by this task.
The native refresh of GitHub triggers replaced the Wiki/Blog webhook ID/signing secret:
the old ones removed, the new ones active, one per URL, events unchanged. Credential refs,
business data and graphs were verified at each write. A separate SPI Route JS change
during the window was not overwritten. Existing SPI/Grafana alerts were not changed.

New workflows do not inherit the binding automatically: add it via
`scripts/n8n/sync_failure_alerts.py` (without a flag — plan only). Already-running/Wait
executions may store old settings; manual tests, caught errors, cancellation and
a full n8n failure are not equal to a normal automatic failed execution. The handler itself
cannot report a break of its own transport over the same transport; independent
health monitoring is needed separately. The first natural Telegram end-to-end is not
claimed by this cut; no artificial runs/errors/messages were created.
[Runbook and enrollment receipt](workflow-failure-alerts.md).

## Current calendar: dynamic TTS and automatic session

The user **granted an exception to the internal API specifically for the calendar
read-aloud**, on the condition of automatic session renewal. Do not extend the old
public-only restriction to this specific native node; keep other integrations on the
public API wherever possible. Do not return a separate voice service.

Active calendar: `Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Announce via Yandex Station → Mark Announced`.
The last integration node is **CUSTOM.yandexStation**, which receives a dynamic
`$json.text`. Credential **Yandex Station Auto Session** (`yandexStationApi`):
encrypted xToken/deviceId/scenarioId. Intermediate cookies/CSRF live only in memory,
not in outputs, node HTTP headers, logs or git. Code: `charts/n8n/extensions/`.

The session is created from the x-token on the first call/restart. After the 6-hour
cache expires, the next call creates a new one; 401/403 during preparation also triggers
renewal. Scenario: 50% and a dynamic phrase, without returning the old volume.
Do not retry a run whose response was lost: the speech may have already played.
Tasks are serialized by credential; there is in-process protection against a parallel
repeat of an already-confirmed dedupKey. Do not promise exactly-once.

The active **Yandex Session Maintenance** checks validity every 15 minutes, without
running speech. Do not force-create a new web session every 15 minutes: a healthy one
is reused. Grafana **Automation / Yandex calendar**: an error within 20 minutes
and the absence of a successful check for 40 minutes. The explicit receiver — Socrat Alerts → Telegram;
the global Grafana receiver was not changed. Delivery depends on n8n, but not on the Yandex
credential: a full n8n failure may delay the message, though Grafana will still show the alert.

The X-token can also be revoked. Then `X_TOKEN_REJECTED`, an alert and a controlled
re-authorization/replacement of the native credential in **both** workflows. Do not ask
for secrets in chat, do not edit SQLite. Runbook: `docs/n8n/setup.md`.

Verified live 1804 (a fresh session without sound), 1809 (dynamic speech and dedup),
1817 (scheduled maintenance), 1832 (a new session after the final restart without
browser login), Grafana contact test 200 and Socrat Alerts delivery 1819.
28 tests: 9 JS-client, 6 calendar, 13 blog. The JSON of both workflows and the alert rules
are stored in git; `sync.py` / `sync_yandex_session.py` change only inactive records.

## Operational guidelines for agents

- `docs/n8n/calendar-voice-reminder.json` — dynamic calendar notifications;
  `docs/n8n/yandex-session-maintenance.json` — a separate silent check.
- `charts/n8n/extensions/YandexStation.node.js` — native node;
  `YandexStationApi.credentials.js` — credential; `yandex-client.js` — protocol,
  session cache, serialization and confirmed in-process dedup.
- Mount/read-only ConfigMap and checksum are in `charts/n8n/templates/`.
  If the node is not recognized after the move, restore the extension and credential,
  rather than returning the retired voice service, raw Cookie/CSRF or a fixed phrase.
- The renderer `scripts/n8n/sync.py` and the maintenance helper
  `scripts/n8n/sync_yandex_session.py` require explicit deactivation before updating;
  after verification, return the original active state. Do not lose ID/static data.
- Alert UIDs: `yandex-session-failure`, `yandex-session-missing`.
  The contact and rules are reproduced from `docs/n8n/yandex-session-alerts.json`
  via `scripts/n8n/provision_yandex_alerts.py`, without changing the global policy.
- In the current Grafana, the old receivers/test API returns 410. To re-test,
  use discovery `/apis/notifications.alerting.grafana.app/v1beta1/namespaces/default/receivers`,
  then POST `…/receivers/{metadata.name}/test` with `{integration, alert}`.
  The test triggers a real message; warn the user. Do not substitute
  a proper delivery check with an artificial break of a working Yandex session.
- After credential changes, a new consistent off-node SQLite copy was saved
  with an integrity/foreign-keys check; the encryption key was saved separately and privately.
  This is a one-time backup, not an implemented backup schedule.

## SPI: automatic incident analysis

New contract and operation: [SPI incident triage](../applications/spi/spi-incident-triage.md).
**All generated `[SPI]` titles, descriptions and GitHub comments are in English.**
Do not rename old user issues. The model compares only open
SPIs; technical webhook duplicates are not new incidents.

Socrat Alerts is kept by ID, the native trigger authorizes and puts the group into a durable
queue without writing headers/tokens into execution data. Telegram remains a separate
fast path. The slow SPI Incident Triage: claim → match → evidence → analyze →
publish. SPI publishing was enabled after a verified dry-run; **the blog still has
WRITE_ENABLED=false**. Do not confuse these policies. Code: `charts/spi-triage/`, runbook:
`docs/n8n/spi/setup.md`. Live dry-run, Telegram, auth401, duplicates,
restart/queue and a refresh of the scoped App token were verified; after v2 — 98 tests. Evidence v2
stores text artifacts directly in the comments, adds absolute Grafana links,
Loki stack/context, Tempo trace search, pod/events and binding to the image/release revision.
Supported stack paths give source excerpts on an immutable commit. The manifest contains
SHA-256, truncations and whitespace. File restoration: `scripts/n8n/download_spi_evidence.py`.
Real SPI #9 artifacts and a roundtrip of all files were verified. The version observed now
does not prove the version at the time of an old incident; unknown host/source versions must not
be invented. The model does not replace proof of cause. Alerts
or infrastructure must not be changed automatically.

## Mandatory rules

1. **A workflow must always be reflected in the codebase.** JSON in git is the source
   of reproducible structure, not an optional UI backup. Changes to a live workflow
   must be moved into JSON; JSON changes must be synced to n8n and verified by execution.
2. **All user-facing text inside a workflow is in English:** the name,
   node names, embedded explanations and diagnostic messages we add.
   Russian is allowed in target content: for example, Station speech or a poem's title.
   Wiki documentation may be in Russian.
3. **No yellow cards / Sticky Note nodes.** Store explanations in the runbook/wiki,
   and convey a stage's meaning with a short English node name.
4. **Nodes reflect semantic stages, not every tiny operation.** Do not hide
   the whole scenario in one "do everything" block, but also do not bloat the canvas with dozens of
   helper blocks. Change an agreed structure only after agreement.
5. **No secrets in git, workflow JSON, prompts, images or logs.** Only
   n8n credentials, external Kubernetes Secrets and local private files.
6. Use API/MCP for operations available to the agent. Do not offload onto the
   user the clicks "Execute step", import or activation if the agent can do it itself. Interactive OAuth consent remains a user action.
7. Do not declare an integration ready based only on a successful import. Verify real
   executions, external effects, negative cases and a re-run.

## Semantic structure: the Blog Updates example

Exactly four blocks, with no extra IF/Code/Note nodes on the canvas:

**Blog push → Validate via LiteLLM → Generate via LiteLLM → Create Pull Request**

- **Blog push:** a signed GitHub event; the required repository and branch.
- **Validate via LiteLLM:** preparation of the actual context and a separate model
  call to decide whether the changes deserve an entry. A negative result
  yields zero items and stops the chain without a separate IF node.
- **Generate via LiteLLM:** a second, independent model call for text over
  only the selected changes. Do not merge it with the first model request.
- **Create Pull Request:** result check, deterministic Markdown,
  deduplication and GitHub write. Contains no third model call.

Helper logic is allowed inside a stage / its narrow backend endpoint.
In the current implementation the last three nodes are HTTP Requests to separate internal
worker endpoints: `/validate`, `/generate`, `/create-pr`. These are **not** direct
LiteLLM nodes: each of the first two endpoints calls LiteLLM itself. Do not return
to a single endpoint that does the whole scenario at once.

The "four blocks" constraint refers to this scenario, not to all future workflows.
For other scenarios, first agree on a brief semantic schema.

## Repositories and artifacts

In homelab:

- `docs/n8n/blog-updates/workflow.json` — the Blog Updates structure without secrets;
- `docs/n8n/blog-updates/prompt.md` — editorial instructions to the model;
- `docs/n8n/blog-updates/setup.md` — startup, checks and limitations;
- `scripts/blog_updates/` — the stage backends, GitHub client, deployment helper;
- `deploy/blog-updates/worker.yaml` — workload and internal Service;
- `tests/blog_updates/` — automatic tests;
- `docs/n8n/calendar-voice-reminder.json` and `docs/n8n/setup.md` — the calendar scenario;
- `scripts/n8n/sync.py` — synchronization of the **calendar** scenario. Do not treat it as
  a universal synchronizer: Blog Updates still requires separate provisioning.

In `~/code/blog`: `site/content/updates.md` is the single journal source;
`site/layouts/index.html` shows the five latest entries, the archive uses the
same Markdown. Do not edit the generated `site/public`.

Match instance credential IDs at import via local configuration;
leave placeholders in git. An ID does not replace a credential and does not carry OAuth.
Do not create workflow/credential duplicates on every deploy. Update by a
verified ID or unambiguous name; on ambiguity, stop.

## Access to n8n and authorization

- UI/API: `https://n8n.socrat.alchemmist.xyz`.
- Now n8n is **public over HTTPS**, reachable through the home and VPS ingress;
  the private gateway is also kept. Do not describe it as VPN-only.
  On the Mac the user uses **NetBird**, not the old WG profiles. `utun100`
  may be the working NetBird interface; "Disconnected" on WireGuard does not mean
  a NetBird failure. Check `netbird status`, do not offer to enable the old VPN.
- The UI is protected by an external Authentik login, after which a separate
  n8n account may still be required. This is a gate, **not native SSO**. The
  Community installation did not get single sign-on from a reverse proxy alone; do not disable
  the internal authorization. The presence of WG also does not replace a login.
- Public API: `/api/v1/`, header `X-N8N-API-KEY`.
- MCP: `/mcp-server/http`, `Authorization: Bearer <MCP token>`.
  The initial audit 2026-11-07 found a backend403 (instance MCP disabled), but a
  later check with an updated local token successfully passed `initialize`
  and `tools/list`: this blocker is closed. In the local project config the Mac client
  is enabled; `search_workflows` and `get_workflow_details` are available, the server-side
  `execute_workflow` is hidden from the agent. Workflows were not executed during the check.
  In the example `deploy/mcp/examples/pi-mcp.json` the entry is still disabled — do not carry the local
  enablement onto other checkouts/machines as already done.
  The exact ingress belongs to `charts/n8n/templates/access.yaml`; the UI gate is kept.
  [The MCP runbook in the wiki](../platform/agent-access/official-mcp.md) records the current state and access boundaries.
  The API key and the MCP token are different credentials, not interchangeable.
- Local files: `~/.config/n8n/api-key`, `~/.config/n8n/mcp-token`.
  The directory is mode 0700, the secret files 0600. Do not print their contents.
- MCP uses Streamable HTTP: first initialize, then discovery tools.
  Check the actually available tools and their schemas; do not assume that MCP
  can provision credentials or edit workflows. API and MCP complement
  each other; installing a third-party MCP service for a normal import is not required.
- Prefer the standard DNS. `curl --resolve ...:443:10.250.0.1` is a diagnostic
  DNS workaround for WG, not a universal condition for the API to work. Do not disable TLS verification.
- Do not reset the owner, create accounts or change the password for automation
  without the user's explicit permission.

### External services

**Google Calendar:** create an OAuth credential, verify the callback
`https://n8n.socrat.alchemmist.xyz/rest/oauth2-credential/callback` in Google Console.
The consent is performed by the user in the browser. Do not commit the client secret, refresh
or access tokens. If the credential API returns an incorrect schema, do not
substitute fake fields: use the standard OAuth UI and then bind the ID.

**GitHub:** a separate fine-grained token only for `alchemmist/blog`, or a
repository-scoped GitHub App. The current native GitHub Trigger needs:
Contents read/write, Pull requests read/write, Webhooks read/write, Metadata read.
Locally: `~/.config/n8n/blog-github-token`. Do not copy the broad operator
`gh` token into the worker. The native Trigger registers a webhook and verifies the signature before
passing the event further. URL secrecy alone is not enough.

**LiteLLM:** a separate virtual API key per workflow, not the master key and not a shared key
of other applications. For Blog Updates an alias `n8n-blog-updates` was created, limited
to `qwen3.8-27b`, with a limit of 6 requests/min. Locally:
`~/.config/n8n/blog-litellm-key`. The worker addresses the internal
`http://litellm.llm.svc.cluster.local:4000/v1`.

**Worker:** the Secret `automation/blog-updates-worker` contains `GITHUB_TOKEN`,
`LITELLM_KEY`, `WORKER_TOKEN`; HTTP requires `X-Worker-Token`. The Service is ClusterIP,
not a public ingress. In n8n — a separate Header Auth credential. Local mappings:
`blog-credentials.json`, `blog-workflow-id`; for the calendar —
`calendar-credentials.json`. Do not commit secret values and private mappings.

Do not repeat tokens sent in chat in your replies. Store them privately, do not include
them in reports/diffs; recommend rotation. Do not ask to send new secrets into chat.

## Calendar reminders: actual configuration

- `primary` means only the primary calendar, not all of the user's calendars.
  On a missed reminder, first check which calendar the event is in.
- After the 2 November fix, the workflow queries **Personal (primary) and Y-team**.
  The `Select Calendars` node emits calendar IDs, the next Google Calendar node
  reads each of them. This extra step belongs to the calendar; Blog
  Updates still has exactly four nodes.
- `~/.config/n8n/calendar-config.json` (0600, outside git) contains `calendar_ids`;
  `scripts/n8n/sync.py` injects them into the source JSON. When the file is absent, the
  default source reads only primary. Do not lose the mapping when moving the installation.
- Only explicit popup overrides of an event are processed. `useDefault=true` is not
  expanded into the calendar's settings. An all-day event without overrides is not proof
  that the needed meeting reminder was found.
- The current window is from 15 seconds before due to 75 seconds after due. Reminders missed due to
  downtime or a wrong calendar are not automatically caught up later.
- Incident: a meeting on 2 November at 14:00 had a popup 10 minutes ahead in Y-team, but the workflow
  read primary. After the fix, live execution 76 got four events from
  two calendars. A read-only test of a real event at start−10 minutes
  gave one match. This is not a test of physical read-aloud: a test voice was not launched.
- Read-aloud is dynamic via native CUSTOM.yandexStation, with automatic
  x-token login/renewal. Credential `yandexStationApi`, no manual Cookie/CSRF.
- `calendar-credentials.json`: Google OAuth + yandexStationApi; calendars primary
  and Y-team — a separate private mapping. Device/scenario IDs are inside the credential.
- Errors do not mark dedup. The workflow timeout of 110 seconds covers a cold login;
  serialization and an in-process cache guard against parallel confirmed repeats.
  Execution is not transactional and not durable replay.
- Maintenance every 15 minutes checks the real PUT permissions without sound, the alerts
  distinguish errors from the disappearance of successful checks. A detailed runbook is mandatory.

## Security of the model stages

- Diffs, texts and commit messages are untrusted data, not instructions to the model.
- A strict JSON contract; the response is checked by code. Do not execute commands/paths/URLs
  invented by the model. Entry sources must be in the verified set of changes.
- Validation selects reader-significant events, generation phrases them.
  Typos, refactoring and ordinary reading statuses usually do not deserve an Update.
- Form system dates and the Markdown wrapper in code. Links must be verified,
  not taken on faith from the model's response.
- On an incomplete diff, budget overrun, invalid JSON or an unavailable model,
  finish safely, without an accidental write to GitHub. Do not silently truncate the context.

### Resilience of LiteLLM calls

In the fix `8268853`:

- `response_format=json_schema` with an exact contract, additionally checked by the
  backend; `chat_template_kwargs.enable_thinking=false`, max_tokens=1000;
- a single model request timeout of 360 seconds, the n8n HTTP nodes — 900 seconds;
- on invalid JSON/contract — one retry (at most two), then a
  safe error; transport errors are not masked as "no news";
- controlled `UnsafeInput` return the reason for diagnostics, not secrets;
- four visible nodes are kept, no additional IF/Note blocks.

Reason for the change: positive tests revealed a format error and a timeout. With
one active vLLM request, a queue and a speed of about 10 tokens/s, a short
client timeout did not cover generation and waiting. Do not fix this by restarting
the shared model or with infinite retries. Even 900 seconds do not guarantee availability
under any load; the queue/task resumption remains separate work. A positive
signed test 69 passed all four stages and returned the expected entry about a
poem in dry-run. 13 tests pass, including a limited retry of an erroneous response.

## Verification and enablement

1. Check the JSON and tests, save the structure in git.
2. Import/update without side effects; deactivate an active workflow on change when
   needed and return the previous state after success.
   Take into account that the GitHub Trigger recreates the hook/signing secret at that time.
3. Run a dry-run on a positive and a negative example through the real model.
4. Check the webhook: without a signature — 401, a correctly signed event passes.
5. Check the number and names of the executed stages, not only HTTP 200 on receipt.
6. For the write stage, create an explicit test draft PR: only the expected file/diff;
   a repeat does not create a duplicate; a closed PR is not reopened.
   Do not merge the test into main, close it and remove the branch after the check.
7. Separately enable production writes only after readiness and permission.
   Report the exact state: active/inactive and dry-run/write are different things.

**Current Blog Updates state:** the webhook/workflow is active, but
`WRITE_ENABLED=false`: real pushes are analyzed, PRs are not created automatically.
Signed historical simulations, model selection/generation, a test PR
#71 (closed without merge) and repeats were verified. Automatic
publication/draft checks, link formation and durable retry still need work. Do not call this a
fully ready production scenario. Reconcile the current state with the deployment
and runbook, do not rely on this historical cut alone.

## Reliability and operation

- A webhook repeat must not give a repeat PR/notification. A human closing a PR is an
  editorial decision; do not reopen it automatically.
- Do not overwrite an advanced main and manual changes. What is needed is a re-analysis or
  an explicit safe conflict, not a force push.
- Consider timeouts and retries separately from idempotency. An accepted webhook does not yet
  mean a completed task; a log/queue must allow recovering from a failure.
- A slow LLM request must not block health checks and remove the Service from
  endpoints. In the worker, health is served separately, operations are serialized by a lock.
- The current serialization is not a durable queue. An interrupted write after branch creation
  requires recovery, do not promise exactly-once.
- Prefer direct HTTP nodes and native credentials if a separate backend has
  nothing to do besides proxy. Do not return a mandatory capability-service:
  the user cancelled this rule on 3 November. The substantive Blog Updates worker
  remains. Do not spawn parallel cron implementations of the same task.

## Storage, migrations and recovery

**Incident 2 November:** after Fleet → Argo CD, the application ended up on a new empty
PVC and requested initial setup. The exact data-deleting operation is unproven.
Do not create a new account and do not pass a JSON import off as a database restoration.
Check PVC/PV identity, volume age, mount path, the number of configured accounts,
workflows and credentials. `/healthz=200` and a successful HTTPS do not prove integrity.

The state was restored from surviving SQLite rollback-journal records on disk:
the former owner with a password hash, both workflows with their original IDs, four credentials with
Google OAuth, API/MCP keys, available static state and personal-project links.
This is a **reconstructed database, not the whole original file and not an exact point-in-time
snapshot**. The full execution history and all versions were not restored. The password was not
reset; a real browser login with someone else's password was not verified by the agent.

Checked: SQLite integrity/foreign keys, the former API key, the absence of Setup,
successful scheduled Calendar executions with the restored Google credential.
After recovery, an incorrect calendar selection and model request errors were
additionally fixed: restoring the database by itself did not guarantee correct
business logic. Details: `docs/n8n/recovery-2026-11-02.md`.

- A consistent copy of the restored database and the encryption Secret were saved privately
  outside the node, not in git. The initial attempt at a full disk image ended in timeout;
  a partial image is **not a backup**.
- The PV has reclaim policy Retain; the PVC template — Helm keep and Argo
  `Prune=false,Delete=false`. This is lifecycle protection, not backup.
- Before moving between Helm and Argo, save the existing PVC/PV and a verified
  off-node backup of SQLite **together with the encryption key**. Regular verifiable
  off-node backups still require separate implementation. Returning n8n to the Fleet GitRepo is not allowed: `deploy/fleet/n8n.yaml` and `deploy/n8n/fleet.yaml` are removed, the owner is the Application `n8n`.
- When replacing the database, stop the single writer, save the previous files,
  check integrity and links, and only then start and activate the scenarios.
- Do not disable self-heal without a subsequent recovery. Live patches may be
  immediately reverted by Argo: fix the source of truth, do not fight the controller.
- The public Authentik ingress now has its own `n8n-authentik-tls`.
  The private n8n vhost must stay in `charts/private-gateway/values.yaml` and
  go through Traefik HTTPS, to keep the Authentik and machine endpoint policies.
  On an HTTPS error, check the public IPs **and** the browser's real WG/DNS path.

## Git and agent work

- First check status: homelab and blog often have parallel someone-else's changes.
  Add files addressably, not `git add .`; do not include Python cache, build output,
  private files or another task's changes.
- Before a commit: tests, staged diff and a secrets check. Commit/push — by the user's
  permission; the report contains the commit SHA, the push result and the actual live mode.
- On a shared Helm release, keep the current live values and reconcile competing
  changes. Do not break Harbor/other routes for n8n.
- Do not bypass TLS/SSH checks, do not publish a backend/secrets for debugging convenience.
- Documentation must honestly separate what is implemented, what is verified, and what remains.

### Mac: n8n through the public entry, without a NetBird dependency

2026-11-04: NetBird Connected, 4/4 peers, but the legacy exact resolver
`/etc/resolver/n8n.socrat.alchemmist.xyz` pointed at private DNS
10.250.0.2/.3/.1, which returned 10.250.0.1. The public ingress worked meanwhile;
the private HTTPS timeout was not an n8n outage or proof of a NetBird failure.

With the owner's consent, the exact n8n resolver was switched to public DNS 1.1.1.1 and
9.9.9.9. No pinning of a single ingress IP: public DNS keeps failover.
The other private resolvers, routes and NetBird were not changed. The Authentik gate and
the internal n8n authorization are kept. The helper `scripts/n8n/public_editor_dns.py`
shows a plan by default; `--apply` requires the standard macOS root consent,
saves a root-only backup and resets the DNS cache. Do not remove the general resolver
`socrat.alchemmist.xyz`: that would affect other private applications.

Verified with ordinary DNS/TLS from the Mac: public A-records, HTTPS302 to Authentik,
the chain up to HTTP200 of the login page. This is not proof of passing the user's
personal login. Do not restart n8n or change PVC/credentials for DNS.
