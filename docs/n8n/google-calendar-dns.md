# Native Google Calendar DNS transport

19841/19875 and later failures were native EAI_AGAIN, not OAuth401/403 or invalid_grant.
Actual n8n libc default lookups exceeded6.5s; exact c-ares A queries usually took
10–70ms. ndots5/search/A+AAAA expansion magnifies exposure. Upstream packet loss
location remains unproven; TCP was not uniformly fast either. Do not claim a
cluster-wide DNS repair or rotate credentials based on these failures.

Prepared scoped compatibility preload `google-dns-preload.js`: callback DNS lookup
only for exact www.googleapis.com/oauth2.googleapis.com, using c-ares resolve4,
existing Pod-configured nameservers,750ms/two DNS tries with2500ms hard deadline.
Only in-flight work is shared (max two hostnames), no persistent address cache or
IP pin. Numeric-family/callback/all-result shapes are supported; other domains
and explicit IPv6 delegate unchanged. Unknown/empty/oversized DNS answers fail
closed. Safe diagnostic emits only fixed host/code/phase. No HTTP interception,
request retry, credential change, TLS override, public replacement DNS or auth
bypass. Existing NODE_OPTIONS must be absent (verified) or explicitly preserved
before adoption. NODE_OPTIONS preloads before native HTTP imports; ESM exports
synchronized. Native graph/credentials/Google Calendar node stay unchanged.

25 Node tests including existing Yandex tests and31 Python n8n regressions passed.
Real n8n installed Axios + native agent config exercised in an isolated process,
unauthenticated official-host HEAD only:364/280ms,404 responses, one scoped DNS
lookup each, verified normal TLS. No workflow/manual Calendar/paid probe.

## Activation blocked12 November11:21 UTC

NOT LIVE. No Git push/Argo change performed. socrat-5 became NotReady during
preparation; API→kubelet502, public native API503, node ICMP/SSH/kubelet unreachable
from approved socrat-0. Pod local storage must not be force-moved or reset.
Related admission pause request TIMED OUT; exact partial result unknown. Saved
original states for SPI J9akzlydrf9XZiID, Yandex BJczDRwqaikJBnyo, Calendar
Cdr4tggOc0kVAzx8 were all active=true. Cannot verify/restore while node/API offline;
restore these original states via native API as soon as access is legitimately
recovered. Do not mutate auth/workflow SQL. Unrelated alerts were not paused.

Before push: recover node access separately, inspect/restore activities, fetch/
rebase concurrent main, rerun tests, pause only authorized related admissions,
wait natural global native pending empty (all workflows, including alerts) plus
SPI logical owner/processing/paid0, ASSERT immediately before push. If occupied,
fail closed, no force restart. Preserve snapshots/settings/static/pin/credentials/
PV/image/key. Observe a new naturally scheduled Calendar execution after rollout;
HEAD/tests/Argo alone are not natural acceptance. This file is a preparation
receipt, not a deployment success claim.
