# Current n8n Calendar failure —15Nov2026

## CURRENT: user reconnected Google; OAuth recovered, latency caveat remains

User completed native Reconnect on15Nov; SAME credential ID updated16:22:44UTC.
Natural Calendar executions46584–46587,46589–46590,46593–46594 succeeded
16:24–16:33UTC (~1second each). At16:34UTC:8successes/2canceled since16:24;
last error-start remains16:22:44UTC, before credential update at16:22:44.714. No manual workflow run, graph/credential replacement or restart.

Not unconditional end-to-end acceptance:46588 and46592 lasted110seconds then
canceled; the newer run completed cancellation at16:33:34UTC. Existing workflow
executionTimeout=110 confirmed through native API. One simultaneous DNS probe in actual Pod resolves
both Google hosts successfully: libc43–47ms, c-ares13–22ms. That sample does NOT
rule out intermittent DNS/HTTP stalls or establish their cause. Six separate
unauthenticated official-Google HEAD probes with normal TLS/agent:false reproduced
one6500ms deadline between TCP connect and secureConnect; DNS lookup34–77ms.
Six additional explicit-family4 probes also reproduced one such TLS deadline,
other five completed220–314ms (expected unauthenticated HTTP403). Thus an
IPv6-only explanation is NOT supported, and DNS preload/IPv4 forcing is not a
proven remedy. No credentials used by probes, no calendar reads/speech/business
workflow runs. Root cause of intermittent TLS delay and its exact relation to
110second native cancellations remain unproven. DNS preload remains disabled;
no timeout increase, alert mute, network reroute or forced retry performed.

New exact-CronJob n8n-post-google-reconnect-20261115 succeeded on5, delivered to3:
n8n-20261115T162959Z-7f3481063ad2.tar.gz,46287026bytes,0600;
SHA256b8a6fa0a87b00fcabf9d6f0769a3a3fd19c3c80a7a114eaa9d4663e0e8f61d04.
Independent archive/sidecar/DB hash/integrity/sourceNode5/unchanged encryption key
and7workflows/10credentials/1user checks passed. New encrypted OAuth state backed
up. Private receipt: vm105-apps-20261115/post-google-reconnect-backup-verified.json
under ~/Library/Application Support/homelab.

## Initial diagnosis before user reconnect

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

Completed by user; instructions retained for recurrence: open existing native n8n Credentials -> Google Calendar account ->
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
consent is explicitly a user action under docs/n8n-workflows.md.
