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

## LIVE outcome and remaining blocker —08:14UTC

Source0ab81dac activated viaGit/Argo after freshall-nativepending[] and
SPIowner/processing/paid0.42Node/39Pythontests passed. Newn8nPod
n8n-56b8cdc48b-8w5rkReady/restart0. Runtimehash/max8/parallel2 exact; all7native
businessgraphs/settings/credentialrefs/static/pin/activities unchanged. Secret/
PVC unchanged; only extensionchecksum changed in DeploymentSPEC. Relatedthree
activities restored. Early10scheduledsuccesses were a FINITE sample, NOT a fix
claim: later49576/49578/49581/49583/49585 failedall8TLS attempts withinoriginal
budget. Current finitepostpatch28run sample23success/5error. Stop increasing
attempt counts or walltime; candidate coverage fix alone is insufficient.

Read-only rootAF_PACKET capture on5ens18, IPv4/TCPheaders/lengths/recordtypeONLY,
neverpayload/HTTP/certificate bytes, showedfailedflows: SYNACK arrives, outgoing
ClientHello retransmits, nopeerTLSdata/ACKprogress. OtherGoogleIPflows complete.
Matchedboundedprobes preserveTLS.4of8flaky inearlier3matrices,2stillflaky inlater
matrix; endpoints changeavailability over time. SmallX25519ClientHello still
fails on affectedpaths; strict-noSNI diagnostic does NOT provide validGoogle
identity (defaultselfsignedcertificate) and is REJECTED, neveradopted. No TLS
bypass/CAimport/SNIremoval or cipherdowngrade deployed. Initial25secondcapture
missedtraffic; correctedETH_P_ALL75secondcapture470headers supportsactualclaims.

Samefresh8GoogleIPs fromsocrat-2NL allvalidatedTLS80–162ms. Node5hostoutsidePod
alsohasfailures, so CNI-only explanationunsupported. DirectexistingNL privateDNS
returnsSAME8IPs; changingDNS upstream alone willnotselecta differentendpointset.
NL5354 deniedPodqueries(asdesigned);53returnednormalanswers. NOresolverchanges.
This localizes remainingissue to source/path-dependenttransport beyondsimple
n8nretrycap, NOT proof ofpreciseprovider/Google/DPI/MTUroot. Node5interfaces show
noerrors/drops, n8nPodlowCPU/280Mi/noOOM. No globalVPN/WG/route/MTU/firewallchange.

A reliable alternative would be a narrowlyscoped privateopaqueTCP/CONNECT egress
forONLYGoogleAPI/OAuththrough existingNLnode, preservingoriginalend-to-endTLS,
HTTP/credentialidentity and noHTTPPOSTreplay. No suchgateway/proxy/generalexit
route hasbeencreated. This is an architecture/routingdecision, not silently
smuggled into retrycap. PreserveuserVPN/NetBird/mesh/publiclisteners and investigate
providerpath independently. CurrentCalendar remainsPARTIALLY UNRESOLVED.

## Separate SPI fix LIVE

Fullmorningclassificationat07:52UTC:14contextoversizeerrorsin2retainedretryjobs,
1LLM_UPSTREAM_NETWORK_ERROR joba3f3c312…2b3f alreadyCOMPLETE/reporttrue naturally
beforeourrelease. Historicaljobs.error retained, notcurrentfailureclassification.

Canonicalsource alchemmist/spi-triage2cfc5ccb: model-only explicitmetricseries
prefix16/8/4/2/1 afterordinaryscalarcompactionfails; allcandidate/artifactIDs,
querypaths/params/fulljob andimmutableevidence unchanged. SelectionNOTaggregate
orrelevanceranking; original/selected/omittedcount+SHA+not-reviewedlimitation.
Originaljob75e8…:oldminimalreservation39595>30000;new16810withsame10artifactIDs
andcandidate174,selected16/omitted84onlyhighcardinalityquery. NOmodel/networkcall
forproof. Budgets30000TPM/3RPM/parallel1/output2500 unchanged;noreset/replay.

Push44041846995 tested464nativecasesZEROskips andpublishedonly. Explicit
workflow_dispatch44042321782 deploy_target=spi-triage afterSPI-onlyadmissionpause
andFRESH all-nativepending[]+owner/processing/paid0. Calendar/Yandexwerenotpaused
forthisSPI-onlyworkerrollout. Releasepassed464nativecasesZEROskips, immutable
image sha256:c25911c573cc62944e8f81ffb0d906d466efe41718b825824f29967e2b2cabe4;
ownedhomelab97538d93,ArgoSyncedHealthy. Exact5runtimefilehashes/health200. Worker
andexistingDBguardinitimage changed together, nothingelseinfullDeploymentSPEC.
Initialcomparisonassertionforgotinitimage;correcteddiffconfirms2image-onlyfields.
SPIactivityrestored withsamegraph/settings/static/pin. n8nNOTrolledforthisrelease.

Twooriginalcontextjobs stillretry/attempt7withORIGINAL futureavailabletimes
(~08:33and08:48UTC); nolease/budget/backoffreset toforceacceptance. Config/runtime
andoriginalofflineproofverified; newnaturalmodel/report/publicationacceptance
stillPENDING. Do not report asnaturallycompleted untilthose jobs runnormally.
Private /tmp/n8n-morning-20261117-private/ holds read-only evidence and release.
