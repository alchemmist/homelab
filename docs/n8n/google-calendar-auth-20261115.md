# Current n8n Calendar failure —15Nov2026

## Diagnosis, NOT repaired yet

Owner requested fixing continuous n8n errors after application migration.
Read-only execution audit identifies native Google OAuth `invalid_grant`, mapped
by the installed @n8n/client-oauth2/constants.js to the exact observed EAUTH
message. This is NOT the earlier12Nov EAI_AGAIN failure; do not activate a DNS
workaround, rotate TLS/encryption keys or restart n8n as an OAuth repair.

- Workflow Calendar -> Yandex Station Voice Reminder, ID Cdr4tggOc0kVAzx8.
- Node Get Upcoming Events; credential Google Calendar account,
  googleCalendarOAuth2Api ID ePyhkBESw5Ue7EH3.
- Last recorded success44001 at2026-11-14 19:31:23UTC (22:31MSK).
- Continuous errors begin19:32UTC (22:32MSK), before today's VM handoff.
- Audit window through15Nov15:40UTC:1040 Calendar errors in24hours; recent
  30 failed runs all the same EAUTH text. No provider revocation reason inferred.
- Four older SPI Analyze Incident errors02:10–07:17UTC;24 later SPI successes in
  the6hour audit window, no subsequent failed SPI execution in that snapshot.
- Yandex Session Maintenance has24successful executions in6hours; recent
  session_check_ok. Socrat Alerts31successes. n8n Pod Ready/restart0 on5.

Google's generic invalid_grant can mean expired/revoked refresh authorization or
client/redirect binding mismatch. Exact provider-side cause (including OAuth app
Testing status/seven-day token lifetime) is NOT established by this evidence.
No credential data decrypted/exported or auth tokens printed during diagnosis.
Raw saved execution evidence is private0700/0600 outside Git:
~/Library/Application Support/homelab/n8n-errors-20261115-mv892wd6 and
n8n-errors-20261115-ilbwe_pr.

## Required interactive step and acceptance

User must open existing native n8n Credentials -> Google Calendar account ->
Sign in with Google/Reconnect and complete consent with the intended account.
Do not ask for password/token in chat or substitute a new credential/workflow ID.
Native callback remains https://n8n.socrat.alchemmist.xyz/rest/oauth2-credential/callback.
If Google rejects redirect/client configuration, inspect that specific error
before changing client settings; moving Kubernetes nodes does not change callback.

After consent, observe the NEXT naturally scheduled Calendar run and verify the
Google node succeeds without a manual workflow run (which could speak aloud).
Then verify continued scheduled success and capture a fresh off-node backup
through the existing CronJob, preserving updated encrypted authorization state.
Do not claim repaired based on Pod health or successful unauthenticated HEAD.

Workflow activities/graphs/credentials/SQL/history, failure handler and alerts
were not modified or muted. googleDnsEnabled remains false. Interactive Google
consent is explicitly a user action under llm-wiki/n8n-workflows.md.
