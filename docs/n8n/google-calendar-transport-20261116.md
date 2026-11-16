# Calendar pre-HTTP Google connection failover —16Nov2026

## Intent and diagnosis

Read llm-wiki/context/network-access/vpn-hardening/n8n-workflows and public
wiki/content/network/vpn before selecting a change. NetBird is human access,
wg-socrat is node transport, Moscow→NL is USER VPN transit, not a blanket app
exit node. Preserve Mac/Tunnelblick, routes, mesh identities/AllowedIPs, overlays,
NetworkPolicy mark guard, DNS ownership and the node1↔5 relay. This change does
NOT alter any network infrastructure or send application traffic through VPN.

Calendar48242 canceled110.007seconds; immutable executionTimeout110. Initial
100execution sample45success/54canceled/1error;48142 Google Backend Error.
Installed core1.122.52 Axios default300seconds; native Calendar list helper has
no explicit request timeout. Outer workflow deadline therefore wins. Native
list pagination itself does NOT use the separate recurrence retry helper.
Credentials were legitimately reconnected15Nov; no new401/invalid_grant proof.
Do not rotate credentials again or attribute these cancellations to the oldOOM.

Unauthenticated bounded official-host HEAD (no workflow/Calendar/auth calls):
DNS andTCP complete, but someTLS handshakes stall. Reproduced on host5 outside
Pod too. Default-family and explicitIPv4 both stall; lookup family6 does not
mean socketIPv6 (captured remoteFamilyIPv4). IPv6-only is not the explanation.

Fresh DNS returned8www.googleapis.comIPv4s. Per-address matrix:7responded in
~250–350ms, one failed before secureConnect. Exact suspect was still present
in freshDNS:6/6handshakes to that address failed within3.5s bounds across native
TLS1.3, X25519-only andTLS1.2. Healthy addresses worked. Node0curl comparison
also timed out on suspect and succeeded on control. No evidence selects MTU,
post-quantum crypto, general DNS, CNI or any precise provider/Google fault.
Raw address data in private receipts; no IP is checked into production config.
The5/3.5second bounds measure a stall, not infinite duration or exact earlier48242
packet flow. Path/edge root remains external/unlocalized, not a cluster-wide fix.

## Narrow correction

`googleTransportEnabled` preloads `google-transport-preload.js`. It adapts only
standard native HTTPSAgent.createConnection for exact www.googleapis.com and
oauth2.googleapis.com on443. Nonmatching hosts/ports, explicitIPv6, existing
sockets and unrelated agents delegate unchanged. No global DNS monkeypatch;
legacy googleDnsEnabled remainsfalse. Exact-name c-ares resolve4 uses existing
Pod resolvers,2.5second hardDNS deadline, no persistent cache or pinned address.

The original native createConnection still creates TLS sockets with native
CA/hostname/cipher/session options and the ORIGINAL SNI. The adapter DOES NOT
return the raw socket to HTTP. Only after authorized secureConnect is it handed
to Agent's callback. Until then no HTTP request/header/body/POST can be written.
A transient pre-HTTP failure destroys that candidate and tries next CURRENT DNS
address. Maximum4candidates,2seconds each,9.5second wholeDNS+connection deadline.
No permanent blacklist; Google controls future addresses normally.

Certificate/identity/policy failures are fatal, not failover candidates. Explicit
TLS bypass/differentSNI rejected. Once a verified socket reaches HTTP, the
adapter never retries: lostOAuthPOST, HTTP5xx and response/body failures remain
native failures. This is connection establishment failover, NOT request replay.
Fixed diagnostic host/code/attempt count, neverIPs/headers/credentials/rawerrors.
Native Calendar ID/nodeIDs/credentials/settings/static/pin/history unchanged.

This deliberately fixes the reproduced pre-TLS stall rather than introducing
new Calendar pagination/retry/business logic speculatively. Slow response-body/
provider5xx need separate bounded native request handling if naturally observed;
outer110second deadline remainsfinite and not increased. No continueOnFail,
node-wideRetryOnFail or silentpartial event lists. Existing due-15s..due+75s
reminder window/dedup/voice semantics unchanged; historical missed reminders
not replayed. No exactly-once speech guarantee manufactured.

## Verification before activation

37Node tests including existing Yandex/DNS suites: mocked bounds/latecallback/
cert/SNI/delegation/error sanitization plus REAL localHTTPS test with stalled
first handshake, verified second handshake, and lostPOST:server received exactly
ONE request, no replay.39Python n8n regressions pass throughuv pytest. Initial
system-Python discovery lackedpytest; not recorded as a product test failure.
Default disabled render byte-identical to prior fullchart. Enabled render has
exactlyoneNODE_OPTIONS and proper dependencies; image/PVC/SSO unchanged.

Real installed n8nAxios with nativeaxios-config/agents in isolated child, NORMAL
TLS and unauthenticatedHEAD only: freshly resolved suspect first (test ordering,
not a production pin) then adapter successfully used second address,2/2Google
requests~2.3s verifiedTLS;OAuth root180ms. No HTTP/auth production request replay.
First diagnostic child failed because test Module.filename was undefined; that
isolated process exited134, not main n8n. Corrected harness passed, no app restart.

## Rollout and acceptance

Argo is sole deployment owner. Activation requires temporary authorized related
SPI/Calendar/Yandex admission pause, ALL-workflow native pending[] plus SPI
owner/processing/paid0 ASSERTED fresh before Gitpush. Never mute alerts or cancel
existing executions to manufacture drain. Restore original related activities
and compare other workflow graphs/settings/credentials. Verify runtime fileSHA,
NODE_OPTIONS, exactimage/PVC/SecretUID/data hashes privately, native graph/static/
pin and unrelated activities unchanged. Observe new natural scheduled Calendar
runs INCLUDING successful google_connect_failover; Argo Healthy/HEAD are not
natural acceptance. Unrelatedwebhook activity/static data may legitimately evolve
while observing; never overwrite from a stale snapshot.

Evidence private /tmp/calendar-network-fix-private0700/files0600. Official
https://developers.google.com/workspace/calendar/api/guides/errors recommends
backoff for HTTP backend/rateerrors, NOT blanketPOST retries. n8n docs
https://docs.n8n.io/workflows/settings/ confirm workflow timeout cancels execution.

## LIVE initial acceptance —20:21UTC16Nov

Code e9297126, activation9a014aa2 pushedmain after related trigger pause and
natural last execution completion (old48685canceled by its ORIGINAL110second
deadline20:20:34; not manually canceled). Fresh all-nativepending[] and
SPIowner/processing/paid0 ASSERTED immediately beforepush. No native definition
PUT, no credentials write, no alert mute or live deployment override.

Argo reconciled9a014aa2 SyncedHealthy; newPod n8n-587cfcd774-spp8b on5,
Ready/restart0. Runtime3moduleSHA256 and loadedpreload exact. Original Deployment
UID, immutableimage, volumes/PVC identity/spec and SecretUID/dataSHA unchanged.
All7native graphs/settings/nodeIDs/credentialreferences/pin/staticData match
preparation snapshots EXACTLY; original activities restored (6active, handler
inactive). Static data was only compared, never overwritten from snapshots.
One post-push snapshot GET racednormalrollout and failed; no writes/retries were
performed for that read. Recovery verification after readiness succeeded.

First NATURALLY SCHEDULED new48686 started20:21:56UTC, completed20:22:01UTC,
GoogleCalendar4827ms, MatchDueReminderssuccess. Two mainn8n transport diagnostics
reported CONNECTED after2attempts on www.googleapis.com; no manual workflow,
Calendarrequest or speech probe. This is real initial failover acceptance, not
justHEAD/Argo. No Announce node executed in that run. Observe a longer finite
natural window before asserting ongoing reliability; never declare all future
provider/DNS/network/HTTP errors impossible. Historicalcancellations preserved.
