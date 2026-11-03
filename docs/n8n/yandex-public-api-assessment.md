# Yandex Station Midi: public API assessment (2026-11-03)

## Decision and current state

User requires **only `https://api.iot.yandex.net` with OAuth**. Internal Quasar
HTTP APIs, Cookie/CSRF, Glagol and voice proxy fallbacks are not permitted.
The assessment initially paused the calendar. The user subsequently agreed to
the fixed-scenario replacement: the workflow is now **active**, with a single
public scenario-launch POST and native bearer credentials. Old internal nodes and
Cookie/CSRF credentials were removed. `sync.py` enforces the public-only route.
See `setup.md`; do not restore the superseded internal implementation.

## Evidence

Used the existing IoT token with `iot:view` / `iot:control`, not the previous
Station music/x-token. Secrets and full responses are private, not in git.
GET `/v1.0/user/info` and `/v1.0/devices/{id}` returned 200 / status=ok.
No unrelated settings, alarm, Wi-Fi, equalizer or child settings were changed.

| Request to public host | Result |
| --- | --- |
| POST `/v1.0/devices/actions`, `devices.capabilities.range`, instance `volume` (value 5, bounded low-volume test) | 400: `action devices.capabilities.range:volume is not valid for device …` |
| Same endpoint, `devices.capabilities.quasar`, volume value object | 400: `unknown capability type: devices.capabilities.quasar` |
| Same endpoint, `devices.capabilities.quasar`, TTS text | 400: `unknown capability type: devices.capabilities.quasar` |
| Same endpoint, `devices.capabilities.quasar.server_action`, text_action | 400: `unknown capability type: devices.capabilities.quasar.server_action` |
| Same endpoint, `devices.capabilities.audio_player`, play action + URL | 400: `unknown capability type: devices.capabilities.audio_player` |
| Same endpoint, `devices.capabilities.audio_player`, stream_id URL + playing state | Same 400, rejected by capability type, not audio codec or URL availability |
| PUT `/v1.0/scenarios/{id}`, owned dedicated scenario definition | 404: `404 page not found` |
| POST `/v1.0/scenarios/{id}/actions`, existing dedicated scenario | 200 / status=ok; user heard **«Напоминания из календаря настроены»** |

Audio URL used for the two rejected player tests was a short public HTTPS Ogg
beep, whose availability was checked. Because validation rejected the capability
**type**, changing Ogg to MP3 or adding an audio hosting service cannot resolve
this failure. No audio URL reached the player in these tests.

The device-info response includes `audio_player`, alarm, equalizer and other
metadata, but that is **not evidence that the public actions endpoint accepts
commands for each returned type**. This specific mismatch is now tested.
The Station does not advertise standard `range:volume`. Successful earlier 50%
control used the internal API; do not cite it as direct public volume control.

## What can be implemented

The verified public route is **launching an already configured scenario**. Its
stored TTS and volume actions can execute on the Station; public launch itself
was audible. A fixed calendar alert, with desired volume configured beforehand
in the official app, is therefore viable without a voice service or Cookie/CSRF.

The public protocol does not document scenario creation/editing, a text argument
for scenario execution, or TTS/arbitrary audio playback. Its real actions endpoint
rejects the tested TTS/player types. Thus the original combination — dynamic
calendar title spoken aloud and volume set for each event, using this Station
and public API alone — is **not supported by the documented/tested interface**.
This is a scoped conclusion about the current API, not proof about all possible
future undocumented endpoints. Don't keep guessing methods or claim metadata is
an available playback command.

Do not activate a fixed phrase as a silent substitute for event-specific speech.
Agree on that behavior first. A fixed scenario's phrase/volume must be configured
in the official app; do not secretly edit it through internal API calls.

## Official references

- [API protocol and complete documented endpoint list](https://yandex.ru/dev/dialogs/smart-home/doc/ru/concepts/platform-protocol)
- [Capability types](https://yandex.ru/dev/dialogs/smart-home/doc/ru/concepts/capability-types)
- [Range instances, including volume](https://yandex.ru/dev/dialogs/smart-home/doc/ru/concepts/range-instance)

## Replacement verification

Native n8n execution **1587** ran the public POST with its encrypted bearer
credential and marked the test reminder successfully. The temporary scheduled
workflow was removed and the original calendar activated. The stored fixed phrase
is still «Напоминания из календаря настроены»; changing it requires the official
app, not an internal API. Six calendar tests and thirteen blog tests pass.
