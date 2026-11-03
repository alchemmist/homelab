# Calendar reminders → Yandex Station: public API only

## Current behavior

The calendar workflow is active and runs the **existing, fixed Yandex scenario**.
It does not send event titles or dynamically change speech/volume. The user agreed
to the public-only replacement after the API assessment.

`Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Run Fixed Yandex Scenario → Mark Announced`

The single HTTP node calls:

`POST https://api.iot.yandex.net/v1.0/scenarios/{scenario_id}/actions`

Authorization is `Bearer <IoT OAuth token>` stored in native **Header Auth**
credentials, named **Yandex IoT Bearer Token**, header name `Authorization`.
No body, Cookie, CSRF, internal API, local Glagol, extra loop or voice service is
required. The old Custom Auth session credential was deleted.

The scenario currently says **«Напоминания из календаря настроены»**, and contains
the previously configured 50% volume action. To use **«Скоро встреча, проверь
календарь»**, change its phrase once in the official **Дом с Алисой** app, scenario
**Calendar reminders**. Public API cannot edit the phrase. No internal API calls
were made to change it for this migration. Public launch executes stored actions;
it does not directly expose Station volume control.

## Native credentials and local mappings

- Google Calendar OAuth2 API: existing recovered credential. Google Calendar API
  enabled; OAuth redirect URI:
  `https://n8n.socrat.alchemmist.xyz/rest/oauth2-credential/callback`.
- Yandex: existing IoT token with `iot:view` / `iot:control`, not music/x-token.
  Bearer Header Auth is encrypted at rest by n8n. It is not an automatically
  refreshing OAuth2 credential; rotate expired/revoked tokens explicitly.
- Never place tokens in node parameters, code, git, reports or execution output.

Files outside git (0600, directory 0700):

- `~/.config/n8n/api-key`: n8n public API key.
- `~/.config/n8n/calendar-credentials.json`: keys `googleCalendarOAuth2Api` and
  `httpHeaderAuth`, each mapping to `{"id":"instance credential ID","name":"credential name"}`.
- `~/.config/n8n/calendar-config.json`: `calendar_ids`, live primary and Y-team.
- `~/.config/n8n/yandex-cloud-config.json`: `scenario_id` for **Calendar reminders**.
  Historical `device_id` may remain for diagnostics but is not required by renderer.

Source: `docs/n8n/calendar-voice-reminder.json`. `python3 scripts/n8n/sync.py`
renders local mappings and updates only an **inactive** workflow. It rejects
ambiguous names, missing mappings, unsafe scenario IDs and non-public HTTP routes.
Preserve existing workflow ID, Google credential, project and static data; do not
create a replacement owner/workflow. JSON placeholders alone are not a deployment.

## Reminder and failure semantics

- Poll every minute over the next 48 hours in both selected calendars.
- Only explicit popup overrides (`useDefault=false`); calendar default reminders
  are not expanded. Primary is not an aggregate of all calendars.
- Due window: 15 seconds before to 75 seconds after event-start minus offset.
- An already missed reminder is not replayed later.
- Dedup key `event ID|start ISO|minutes`, records pruned after 48 hours.
- HTTP failure stops execution. HTTP 200 with JSON `status!=ok` must throw in
  `Mark Announced`; record a dedup key only after successful public API acceptance.
- One scenario launch per matched reminder. Two events can yield two identical
  fixed announcements; no text is overwritten because there is no scenario PUT.
- Workflow timeout 55 seconds, HTTP timeout 10 seconds. Dedup remains best-effort,
  not transactional exactly-once or durable replay. Failed final persistence can
  cause a repeat after audible success. API acceptance alone is not proof of sound.

## Verification and operation

- Real public API checks: [assessment](yandex-public-api-assessment.md).
- User confirmed the fixed phrase from the public scenario-launch request.
- Native n8n check execution **1587** successfully ran the actual public HTTP node
  with encrypted bearer credentials and `Mark Announced`. Temporary scheduled
  workflow was deactivated/deleted. Original workflow then activated.
- `python3 -m unittest discover -s tests/n8n -v`: six tests, covering public-only
  route enforcement, mappings, input validation, due matching/dedup and rejection
  of unsuccessful JSON responses. Blog's thirteen tests remain green.
- Don't repeatedly speak test phrases or change volume without warning.
- Diagnose n8n executions: intended calendar, explicit popup, clock/timezone,
  OAuth/token validity, scenario availability, Station connectivity and DND.
- Retired yandex-voice Deployment/Service/Argo/Fleet/chart must not be restored.
  Repository archived after GitHub denied DELETE scope; private source archive
  preserved uncommitted work. No new capability proxy is needed.

## Access and storage safety

n8n has public HTTPS and private WireGuard routes. Authentik is an outer UI gate,
not native SSO. Use the recovered account. Unexpected Setup means investigate
PVC/PV identity and data; never initialize a new owner over lost storage.

Recovery: `docs/n8n/recovery-2026-11-02.md`. Retain/keep annotations are not backups.
Keep a consistent off-node SQLite backup with the encryption key; recurring verified
backups still require separate implementation. Historical internal-API experiments
are not permission to bypass the public-only policy.
