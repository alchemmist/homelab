# Morning Calendar failures —17Nov2026

## What returned and why yesterday was incomplete

Same n8nPod587cfcd774-spp8b Ready/restart0 after9h. Morning errors are NOT old
110second cancellations. Read-only native SQLite audit at07:41UTC:Calendar
52error/409success since00UTC, firsterror04:57:56UTC. At06:21UTC sample100:
70success/30error. Latest sampled errors are GOOGLE_CONNECT_EXHAUSTED on native
GetUpcomingEvents,~8seconds/four pre-HTTP connection candidates. All earlier
finite acceptance claims remain historical, not an all-night reliability claim.

Direct officialGoogle HEAD in a separate child with NODE_OPTIONS removed
ONLY FOR THAT CHILD (main preload remains active):3freshDNS/peraddress matrices
showed4of8Google addresses stalled before TLS,4were healthy. Yesterday's recorded
sample had1of8bad. No fixed IP blacklist or provider cause assertion is justified:
by a later candidate-proof probe some previously bad addresses were healthy.
First morning matrix mistakenly inherited preload (address options overridden);
that sample NOT used for peraddress conclusions. Corrected child explicitly
unsets NODE_OPTIONS, never productiondeploymentenv, and retained independentTLS.

Our previous cap at4sequential candidates could reject a healthy5th address in
samefreshDNS response. This is an implementation limitation in our mitigation,
not a reason to increase workflowtimeout/retryHTTP/rotateOAuth. Exact failed
historical4IPs were deliberately not logged, so do not claim which4each failed
execution selected. The reproduced context is now multiple flaky endpoints.

## Correction contract

Keep exacttwoGooglehosts/443 scope, originalTLSidentity/CA/cipher/session,
existingPodDNS/exactresolve4, no persistentcache/pin/blacklist, no HTTPrequest
replay, original110secondworkflowtimeout and TOTAL_MS9500 unchanged. Cover up
to8distinctCURRENT DNS candidates with at most2simultaneous pre-HTTP TLS
sockets; second starts only after250ms if firststillpending. Replace failed
slots under same2secondperattempt/9.5secondoverallDNS+connect budget. First
verifiedTLS socketwins; destroy EVERY losing socket/timer beforeHTTP receives
winner. OAuthPOST/applicationbytes can go only tosinglewinner; no losingHTTPS
requestexists. Certificate/identity failurefatal anddestroysracing siblings.
Healthyfastfirstconnection avoidssecondTLS attempt. No maxwalltimeincrease,
model/paidbudgetchange,providerfallback,network/MTU/WG/NetBird/VPN/CNI changes.
Diagnostics add fixed numeric candidates/handshakeTimeouts, not IPs/secrets.

Regressionfixture first4stall/fifthhealthy:retainedoldversionrejectsEXHAUSTED
with4calls;newconnects5th underSAMEbudget andbounded2sockets.42Node tests cover
racewinnerexactlyonce,all8exhaustion,losercleanup,deadlinebothsockets,certificate
fatal,fastfirstnohedge,and REAL nativeHTTPSlostPOSTexactly1serverrequest.39Python
n8nregressionspassed. RealinstalledAxios/nativeagents/verifiedTLSHEAD exercised
newcodeinchild (bad-prefix records selected fromfreshDNS only; networkchanged,
so this particularprobe did NOT needfifthcandidate—do not call it live5thproof).

## Separate SPI failures also found

14SPIerror/21success since00UTC at07:41UTC. Latest49547/49521/49502 fail
AnalyzeIncident HTTP422 LLM_CONTEXT_METADATA_TOO_LARGE. This is separate from
Calendar/network; no modelquota/OAuthreset/replay/paidprobe permitted or done.
Diagnose actualretainedcontext andfailclosedaccounting separately; this n8n
transportcommit does NOT claim to fix SPI.

NativeIDs/settings/credentials/static/pin/image/PVC/SSO/alertactivities must
remainunchanged. Freshall-workflowpending[] +SPIowner/processing/paid0 before
Gitpush;restoreoriginalrelatedactivities. Argoownsonlydeployment; inspectnew
naturalscheduledruns,notmanualCalendar/speechtest. Preserveallhistory.
