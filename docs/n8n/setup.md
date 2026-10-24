# n8n: Calendar -> Yandex Station Voice Reminder

Runbook for deploying and operating the self-hosted n8n workflow that polls the
user's Google Calendar and makes the Yandex Station speak each event's own
popup reminders.

- n8n runs in Kubernetes namespace `automation`, host `n8n.socrat.alchemmist.xyz`
  (private access via the private gateway).
- The companion `yandex-voice` microservice runs in namespace `voice` and is
  reachable in-cluster at
  `http://yandex-voice.voice.svc.cluster.local/say` (POST `{"text": str}`,
  header `X-Voice-Token`).
- Workflow definition (source of truth copy): `docs/n8n/calendar-voice-reminder.json`.

## 1. Google Cloud Console

1. Open <https://console.cloud.google.com/> and create (or select) a project for this integration.
2. **APIs & Services -> Library**: enable the **Google Calendar API**.
3. **APIs & Services -> OAuth consent screen**: choose External, fill in the
   app name and support email. Add the target Google account (the one whose
   calendar will be polled) as a **test user**.
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URI:
     `https://n8n.socrat.alchemmist.xyz/rest/oauth2-credential/callback`
5. Create the client, then copy the **Client ID** and **Client Secret**.

## 2. First n8n login

n8n is already deployed behind the private gateway.

1. Open `https://n8n.socrat.alchemmist.xyz` from a machine with private access.
2. On first run n8n shows the owner-account setup page: enter your email and a
   password to create the local owner account.

## 3. Create credentials in n8n

### Google Calendar OAuth2

1. n8n UI -> **Credentials -> New -> Google Calendar OAuth2 API**.
2. Paste the Client ID and Client Secret from step 1.
3. Click **Sign in with Google**, approve access for the test user added above.
4. Save, e.g. as `Google Calendar - socrat`.

### Header Auth for yandex-voice

1. Get the token from the cluster secret:

   ```sh
   kubectl -n voice get secret yandex-voice-secrets -o jsonpath={.data.voice-token} | base64 -d
   ```

2. n8n UI -> **Credentials -> New -> Header Auth**, name it
   `yandex-voice-token`:
   - Name: `X-Voice-Token`
   - Value: `<token from the command above>`

## 4. Import and activate the workflow

1. n8n UI -> **Workflows -> Import from File**, select
   `docs/n8n/calendar-voice-reminder.json`.
2. Open the imported workflow and assign credentials:
   - **Get Upcoming Events** (Google Calendar node) -> `Google Calendar - socrat`
   - **Announce via Yandex Station** (HTTP Request node) -> `yandex-voice-token`
3. Save, then toggle the workflow **Active**.

## 5. Testing

1. Create a test calendar event a few minutes in the future. In its reminder
   settings, turn **off** "Use default reminders" and add a **notification
   (popup)** *2 minutes before*.
2. Within a minute of the reminder being due (eventStart - 2 min), the Yandex
   Station should announce it exactly once.
3. Wait for the next minute's poll and confirm there is **no duplicate**
   announcement - dedup via workflow static data must suppress it.
4. Check the execution list in n8n (all runs should be green; the HTTP node is
   configured to continue on error, so a voice-service failure will not mark
   the run as failed) and, if needed, `kubectl -n automation logs deploy/n8n`.

### Troubleshooting

- **Voice service 401**: `X-Voice-Token` value in the n8n Header Auth
  credential does not match the token in the k8s secret. Re-run the
  `kubectl ... base64 -d` command and update the credential.
- **Google 401 / auth errors on the Calendar node**: the OAuth credential
  expired or the test-user grant was revoked. Open the credential and
  **Sign in with Google** again (reconnect).
- **No speech at all**:
  - Confirm the Yandex Station is powered on and online.
  - Do Not Disturb on the station silences announcements at night
    (by default **23:00 - 09:00**) - test outside that window.
  - Check the voice service: `kubectl -n voice logs deploy/yandex-voice`.
- **Missed or repeated announcements**: check clock skew between the n8n pod
  and the node (`kubectl -n automation exec deploy/n8n -- date -u`); the trigger
  window is based on the n8n pod's clock.

## 6. Ops notes

- Logs: `kubectl -n automation logs deploy/n8n`.
- Workflow static data (used for dedup) is **reset when the workflow is
  deactivated and reactivated**. After a re-activation, a reminder whose window
  is still open may be announced one extra time - this is expected.
- **git is the source of truth**: after any edit made in the n8n UI, export the
  workflow (n8n UI -> Save/Download) and update
  `docs/n8n/calendar-voice-reminder.json` in this repo, then commit.
