# Yandex Smart Home: public API and the narrow voice-announcement exception

Updated **November 3, 2026**. The user allowed the internal API **only for
dynamic calendar notifications with automatic session refresh**. Do not extend
this exception to other integrations.

## Channels

- Lamps, sockets, ordinary scenarios — the public `api.iot.yandex.net`, IoT OAuth
  scopes iot:view/iot:control, native credentials.
- Calendar → Station Midi — native **CUSTOM.yandexStation** in n8n. Inside:
  x-token login → Cookie/CSRF in memory → update dedicated scenario → execute.
- Do not bring back the old yandex-voice/Glagol/HTTP proxy. The native node
  provides real authorization, refresh, serialization and error handling — not
  an additional pod.
- Node/credential/client code: `charts/n8n/extensions/`, read-only ConfigMap mount.
  The base image pin is preserved; the Recreate deployment prevents two SQLite
  writers.

## Active workflows

1. Calendar: `Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Announce via Yandex Station → Mark Announced`.
   Dynamic phrase “In … “Title” is starting”, 50% volume, no revert to the
   previous one. Token/personal IDs live in the `yandexStationApi` credential,
   not JSON.
2. **Yandex Session Maintenance**: every 15 minutes, a silent check performing a
   real PUT without execution. A healthy session is reused for up to 6 hours;
   a 401/403 on preparation triggers a single refresh. Cold start after a
   restart is also automatic.

Cookies/CSRF are not stored in outputs/logs. A revoked x-token cannot be
recovered without the user's authorization: an explicit X_TOKEN_REJECTED error
will occur. Update the credential in both workflows via the supported UI/API;
never edit SQLite directly. When the token changes, the cache key changes and
the next operation logs in again.

## Observability

Grafana **Automation / Yandex calendar**: a final session/announcement error
(20-minute window) and the absence of a successful maintenance for 40 minutes.
Sanitized events in Loki; no tokens, headers, upstream response bodies or
meeting titles. Receiver **Yandex calendar via Socrat Alerts** → the existing
Telegram bot. It does not depend on the Yandex session, but does depend on
n8n: a full n8n outage can delay delivery. Do not present this route as
independent of the whole platform.

Sources: `docs/n8n/yandex-session-alerts.json` and
`scripts/n8n/provision_yandex_alerts.py`. The global notification policy was
not changed. Live checks: 1804 auth, 1809 dynamic voice, 1817 maintenance,
1819 Socrat Alerts, 1832 re-authorization after the final restart without
manual login; Grafana contact test 200, both rule evaluations Normal/ok.
28 tests pass.

## Why not public-only for speech

The public token reads the Midi and launches a ready-made scenario. But a
direct volume request gave 400 invalid capability for the device; TTS/audio_player
— 400 unknown capability **type**; scenario PUT — 404. GET metadata audio_player
does not imply an available POST. The fixed scenario worked, but did not speak
the meeting title. Findings:
`docs/n8n/yandex-public-api-assessment.md`. This story must not bring back the
old prohibition of the exception agreed above, nor allow the internal API
everywhere.

## Boundaries

- n8n is for user-driven conditions; a CronJob is for infrastructure tasks, no
  duplication.
- Prefer direct APIs/nodes; do not multiply empty capability proxies. The blog
  worker stays because of the real diff/filesystem-logic check.
- Primary does not include Y-team. Only explicit popup overrides; defaults are
  not being rolled out yet. Dedup is best-effort: do not promise exactly-once
  or outage replay.
- Do not retry an ambiguous launch POST; do not treat HTTP 200 with a JSON
  error as success.
- Do not speak test phrases without warning. Separate silent auth checks from
  actual speech.
- Reflect workflow JSON, renderer, tests, alert rules and the wiki in git.
- The old yandex-voice repository is archived; workloads/chart/Secret removed.
  The private archive preserved the sources with uncommitted changes; there is
  no need to delete it.
- Full runbook and manual recovery: `docs/n8n/setup.md`.

## Migration and recovery

Secrets and instance mappings are not in git. A migration needs the previous
n8n DB, encryption key, credential, the custom extension and both workflows.
The JSON alone is not enough. The last agreed off-node copy made after the
auto-session setup was verified for SQLite integrity and foreign keys;
regular backups remain a separate task. Keep the existing PVC and pinned
image; do not replace Recreate with running two writers. Do not reset the
owner or deploy an empty database instead of recovering.
