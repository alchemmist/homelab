# Calendar → Yandex Station: dynamic speech with automatic sessions

## Current architecture and exception

The user explicitly allowed the **internal API for calendar voice notifications**
with automatic session renewal. This is a narrow exception, not permission to use
internal APIs elsewhere. Lamps and other supported operations still use public
IoT OAuth. No voice proxy service or local Glagol client is deployed.

`Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Announce via Yandex Station → Mark Announced`

`Announce via Yandex Station` is the native **CUSTOM.yandexStation** extension,
not an HTTP wrapper service or a Code node containing tokens. It receives the
matcher's event-specific text, e.g. «Через 10 минут начинается “Название встречи”».
It updates the dedicated **Calendar reminders** cloud scenario, sets volume 5/10
(50%), and executes it. The previous volume is not restored.

- Source: `charts/n8n/extensions/` (client, node, credential definition).
- Files mounted read-only using a ConfigMap; checksum rolls the pinned n8n image.
- Deployment uses **Recreate**, never two SQLite writers sharing the PVC.
- Original account, workflow ID, project, Google credential and PVC are preserved.

## Automatic authorization

Native encrypted credential **Yandex Station Auto Session**, type
`yandexStationApi`, contains `xToken`, cloud `deviceId`, dedicated `scenarioId`.
No cookies/CSRF are stored in workflow items or ordinary HTTP node fields.

On cold start, cache expiry (maximum six hours) or HTTP 401/403 while preparing:

1. Exchange x-token for a browser authentication track.
2. Complete the approved Passport session endpoint, collecting domain-scoped cookies.
3. Verify authenticated IoT storage, then obtain the matching CSRF token.
4. Validate action authorization by updating the dedicated scenario.

Cookies/CSRF remain in process memory only. Restarting the pod needs no manual
login: the encrypted x-token regenerates a session. Preparation retries once after
401/403 with a fresh session. A failed update never runs the scenario. Execution
is **not retried** after a lost response: speech may already have played.

The same credential serializes session checks and announcements, preventing one
operation from overwriting the other's text. An in-process acknowledged-dedup
cache also suppresses overlapping polls; persistent workflow static data remains
the main dedup record. This is still best-effort, not transactional exactly-once.
Secrets/upstream response bodies are not included in errors or logs. Only fixed
codes and sanitized success/failure JSON events are logged.

## Silent maintenance and alerts

**Yandex Session Maintenance** is active every 15 minutes. Its native node uses
operation `check`: reuse a healthy session, renew when needed, and PUT the test
scenario without executing it. No speech or physical volume change occurs.
It tests actual action authorization, not merely a readable device list.
Do not force a new browser login every 15 minutes; normal cache lifetime is six
hours, with immediate renewal on an authorization failure. Force Fresh Session is
available for explicit checks/diagnostics.

Grafana rules in folder **Automation**, group **Yandex calendar**:

- `yandex-session-failure`: final session/announcement failure in the last
  20 minutes, pending 1 minute.
- `yandex-session-missing`: no successful session check for 40 minutes, pending
  2 minutes; covers disabled/broken maintenance and missing logs too.

Both query sanitized Loki events and use an explicit **Yandex calendar via Socrat
Alerts** contact point. Existing Socrat Alerts → Socrat bot delivers Telegram;
the default Grafana receiver/policy was not changed. This path is independent of
Yandex credentials, but **does depend on n8n itself**. A complete n8n outage can
block Telegram delivery until recovery, even while Grafana shows the alert.
That infrastructure-wide delivery limitation is not fixed by session renewal.

Sources: `docs/n8n/yandex-session-alerts.json`,
`scripts/n8n/provision_yandex_alerts.py`. Provisioning uses existing Grafana admin
Secret on the host; credentials never leave the host or enter git. Do not add
admin credentials to n8n for ordinary renewal.

## If an alert fires

1. Inspect failed **Yandex Session Maintenance** / calendar executions and the
   sanitized code. Never paste cookies, x-token or screenshots of secrets in chat.
2. `NETWORK_OR_TIMEOUT` / `SCENARIO_UPDATE_FAILED`: check Yandex availability,
   Station/scenario IDs, DNS and the next maintenance check. Do not mark speech
   delivered after an error or blindly retry an ambiguous execution response.
3. `X_TOKEN_REJECTED`: x-token revoked/invalid, not merely stale Cookie/CSRF.
   Automatic renewal cannot bypass revoked account authorization. An interactive
   Yandex sign-in/consent may be needed. Have the agent acquire a new token through
   the approved login and update the encrypted native credential; not via chat.
4. If updating an existing credential is unsupported by the API, create a new
   credential and switch **both** workflows using controlled deactivate/update/
   reactivate operations. Preserve their IDs/static data; do not edit SQLite.
5. Run a **silent fresh-session check** first, then verify normal maintenance.
   Real speech tests require warning. Failure alert can remain up to its 20-minute
   lookback after repair; the missing-heartbeat alert clears after a fresh success.

## Workflow-as-code and local mappings

Source: `docs/n8n/calendar-voice-reminder.json` and
`docs/n8n/yandex-session-maintenance.json`.

- `scripts/n8n/sync.py`: update inactive calendar only.
- `scripts/n8n/sync_yandex_session.py`: update inactive maintenance only.
- Both use native credential references, reject ambiguous names/active changes,
  and preserve the existing records. Raw internal URLs in HTTP nodes remain
  forbidden; only the scoped custom node implements the approved exception.
- `N8N_API_RESOLVE_ADDRESS` optionally selects an existing public ingress if WG
  is down (e.g. 176.98.185.59). TLS hostname validation and API auth stay enabled;
  connect/request timeouts are bounded. Mutations are not blindly retried.

Private local files (0600, parent 0700), never commit:

- `~/.config/n8n/api-key`.
- `calendar-credentials.json`: `googleCalendarOAuth2Api`, `yandexStationApi`, each
  `{"id":"instance credential ID","name":"credential name"}`.
- `calendar-config.json`: `calendar_ids` (live primary and Y-team).
- Private bootstrap/recovery artifacts may retain x-token/source backup; they are
  not a deployment mechanism. Authoritative runtime secret is n8n's credential.
- Device/scenario IDs are inside the encrypted credential; no cloud ID injection
  into workflow JSON is needed. Older `yandex-cloud-config.json` is diagnostic.

## Reminder semantics and storage

Poll every minute over 48 hours. Only explicit popup overrides, not calendar default
reminders. Primary does not include Y-team. Due window −15/+75 seconds around
start-minus-offset; missed reminders are not replayed later. Dedup key
`event ID|start ISO|minutes`; prune older than 48 hours. Mark only after acknowledged
execution. Workflow timeout 110 seconds allows cold login; overlapping polls are
serialized/deduplicated in the node, not by a durable distributed queue.

Auth gate: Authentik is external UI authentication, not native n8n SSO. Use the
recovered account. Unexpected Setup means investigate PVC/PV; never initialize a
replacement owner. See `recovery-2026-11-02.md`. Keep consistent off-node SQLite
backups and encryption key; Retain/keep annotations are not recurring backups.

## Evidence

- Native fresh-session check **1804**: success, sessionRefreshed=true, no speech.
- Dynamic voice check **1809**: matcher → fresh auth → event-specific TTS → dedup,
  success. Temporary workflows deleted; original calendar active.
- Scheduled maintenance **1817**: success.
- Grafana rules evaluated Normal/health=ok; contact test returned HTTP 200/success.
  Socrat Alerts delivery execution **1819** succeeded and bot returned a message
  record. Human receipt is not independently confirmed.
- `node --test tests/yandex-session/client.test.js`: nine client tests, covering
  renewal/403/revocation/sanitization/lost response/serialization/dedup/cookies.
- Six calendar tests and thirteen blog tests remain green (28 total).
