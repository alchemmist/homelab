# n8n: Calendar → Yandex Station reminders

> **Superseded later on 2026-11-03:** the user forbids internal Yandex APIs.
> Calendar is now inactive. The implementation below is historical, not approved
> for deployment; sync.py blocks it. See [public API assessment](yandex-public-api-assessment.md)
> for real request results and the supported fixed-scenario alternative.

## Current architecture (2026-11-03)

n8n calls Yandex directly. There is no voice microservice, local WebSocket client,
or Home Assistant in the production reminder path.

`Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders`

Due items enter `Each Reminder` (batch size 1):

`Prepare Yandex Announcement → Announce via Yandex Station → Mark Announced → Each Reminder`

The first HTTP request updates the dedicated **Calendar reminders** cloud scenario
with a volume action and the event text; the second runs it. Updating all items
before running the scenario would overwrite earlier texts, so retain the loop.
Scenario mutations and execution use the **internal** `iot.quasar.yandex.ru` API,
not the documented public `api.iot.yandex.net` device-action API. A direct TTS
POST to the internal device-actions endpoint returned INTERNAL_ERROR; the scenario
route was verified successfully. Do not claim this is one documented IoT request.

Volume is `devices.capabilities.quasar`, instance `volume`, value `{"value":5}`
(on the 0–10 scale, 50%). TTS uses instance `tts` and a text object. JSON.stringify
encodes the event text; never construct JSON by concatenating event titles.
There is no restoration of the previous volume.

## Access and credentials

- n8n: `https://n8n.socrat.alchemmist.xyz`; public HTTPS and WireGuard paths exist.
- Authentik is an outer UI gate, not native n8n SSO. Use the recovered existing
  n8n account. If Setup unexpectedly appears, investigate storage; do not create
  a replacement owner or import over an empty database.
- Google credential: native **Google Calendar OAuth2 API**. Enable Calendar API
  and configure OAuth callback
  `https://n8n.socrat.alchemmist.xyz/rest/oauth2-credential/callback`.
  Interactive consent may require the user; never request tokens in chat.
- Yandex credential: native **Custom Auth**, named **Yandex Smart Home Session**.
  Its encrypted JSON contains a headers object with `Cookie` and `x-csrf-token`.
  Attach it to both HTTP nodes. Do not add secret headers to node parameters.
- Session cookies are password-equivalent. Listing devices with old cookies can
  succeed while action requests fail 403. During migration, a fresh web session
  obtained through Yandex's x-token session exchange resolved that mismatch.
- These are session credentials, **not auto-refreshing OAuth credentials**.
  Expired/revoked sessions or an internal API change require controlled renewal.
  Generate a fresh matching cookie/CSRF pair and replace the native credential;
  validate authenticated access before switching references. Never report an
  HTTP 200 alone as successful TTS: inspect the JSON `status` too.

## Workflow as code

Source: `docs/n8n/calendar-voice-reminder.json`.
Use `python3 scripts/n8n/sync.py` for an **inactive** workflow only. The script
refuses active-workflow changes and duplicate names. Preserve the existing workflow
ID and static data when updating; don't replace the recovered workflow with a new
one. Check activity and dedup state after any change; deactivation is not a reason
to deliberately clear existing dedup records.

Local files, all outside git; files 0600 and containing directory 0700:

- `~/.config/n8n/api-key`: n8n public API key.
- `~/.config/n8n/calendar-credentials.json`: `googleCalendarOAuth2Api` and
  `httpCustomAuth`, each mapping to `{"id":"instance credential ID","name":"credential name"}`.
- `~/.config/n8n/calendar-config.json`: `calendar_ids` list. Production includes
  primary and Y-team. Missing file defaults to primary only, not all calendars.
- `~/.config/n8n/yandex-cloud-config.json`: `device_id`, `scenario_id` for the
  dedicated announcement scenario. Device IDs are not interchangeable with local
  Glagol hardware IDs. Git has placeholders, not personal account identifiers.

Importing the raw JSON without rendering these mappings is not a completed deploy.
Do not deploy a second cron implementation or recreate the retired voice workload.

## Reminder semantics and failure handling

- Poll every minute, read upcoming events over 48 hours in each selected calendar.
- Use **explicit event popup overrides only** (`useDefault=false`); calendar
  defaults are not expanded. Primary does not include shared/work calendars.
- Due window: 15 seconds before to 75 seconds after start-minus-reminder-offset.
  An already missed reminder is not replayed later.
- Dedup key: `event ID|start ISO|minutes`; prune older than 48 hours.
- Mark only after the scenario execution API returns `status=ok`. Update failure
  prevents execution; execution failure must fail the workflow, not look green.
- The 55-second workflow timeout bounds a poll below its one-minute interval.
  Both HTTP requests have 10-second timeouts. The loop serializes items in a poll,
  not a distributed queue or transactional lock across independent invocations.
- API acceptance is not proof of sound reaching a listener. Dedup remains
  best-effort, not exactly-once: late responses or persistence failures can cause
  repeats, and there is no durable outage replay.

## Verification

1. Check a scheduled execution actually reads the intended calendars; a green
   execution with zero due items does not test the speaker.
2. Read-only matcher tests may use the real event at its due instant, without speech.
3. A real voice test requires an announced, short phrase; don't speak repeatedly
   while the user is in a meeting. User confirmed both audible TTS and 50% volume
   on 2026-11-03 during migration.
4. Temporary authenticated check execution **1470** processed two items through
   the real HTTP nodes and loop, validating both dedup keys. Its cloud actions were
   **volume-only**, no TTS. The temporary workflow was deactivated and deleted.
5. `python3 -m unittest discover -s tests/n8n -v` checks mapping, safe JSON encoding,
   loop connections, failed-update gating, and missing configuration rejection.
   Blog's separate 13 tests must remain green.

For troubleshooting inspect the n8n execution and sanitized error, not retired
voice pod logs. Check Google OAuth, actual calendar selection, explicit overrides,
clock/timezone, Yandex session/CSRF, Station connectivity and Do Not Disturb.
Do not bypass TLS or dump credentials/HTTP auth headers into diagnostics.

## Historical incidents

- 2026-11-02: a 14:00 meeting with a 10-minute popup was in Y-team while only
  primary was polled. Selection was corrected to include both calendars.
- Storage recovery details: `docs/n8n/recovery-2026-11-02.md`. The recovered
  database is reconstructed state, not a complete historical point-in-time restore.
  Retain/keep annotations are not recurring off-node backups.
- The former voice service used Glagol WebSocket, not a one-request IoT proxy.
  It was retired after the direct cloud-scenario path was verified. Older recovery
  notes describe the architecture at the time; they are not deployment instructions.

### Retirement completed, 2026-11-03

- Homelab migration commit: `9954e3d`. Argo Application, Deployment, Service,
  legacy Fleet definitions and chart were removed. Old Kubernetes voice Secret
  and unused n8n Header Auth credential were deleted after a private backup.
- Scheduled execution 1478 succeeded after retirement. Both calendar selections
  and the original Google credential/workflow ID were preserved.
- Five calendar tests and thirteen blog tests pass. A fresh off-node SQLite
  backup includes the new encrypted credential; integrity/foreign-key checks pass.
- `alchemmist/yandex-voice` is **archived**, not deleted: GitHub DELETE returned
  403; the available CLI token lacks delete_repo scope despite account admin
  permission. Do not claim successful permanent deletion. Local original source
  and its uncommitted changes were preserved in a private archive.
