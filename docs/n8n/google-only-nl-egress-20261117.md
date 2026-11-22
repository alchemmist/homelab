> **SUPERSEDED — architecture rejected by owner.** The SSH implementation below
> was replaced by native 3x-ui client `svc-n8n-google` and an official Xray-core
> sidecar in5b722c5c. Its dedicated SSH access and unused Secrets were revoked.
> Do not copy this historical mechanism. Current standard:
> [VPN-as-service](../network/vpn-egress/service-vpn-egress.md). Preserve this report as
> history, not deployment instructions. Venice remains separately pending.

# Google-only NL egress —17November2026

Owner explicitly authorized17Nov and requested comparison with Venice on5.
This supersedes the UNDEPLOYED-egress status in the earlier morning report.
Read network/context/publicwiki/Venice runbooks; no AI delegation.

## Why and scope

Google TLS from5(andoutsidePod) intermittently stalls afterTCP. Coverage8DNS
candidates stillhad5natural failures whenALL8stalled. Same8IPs fromNLverified
80–162ms. Exactprovider/Google/DPIroot unproven; this is scopedpath mitigation,
NOT globalnetworkrepair. NoDNS/MTU/WG/AllowedIPs/NetBird/Mac/Tunnelblick/VPN/route/
firewall/default-exit/cluster changes. UserMoscow→NLtransit remains untouched.

Venice already uses pinned nativeSSH -Dloopback viaNL. ReusedPATTERN, NOT its key,
profile/session/APIcredential, Deployment, ServiceorSecret. Google insteaduses
TWOstatic -Lforwardson127.0.0.1only:18443→www.googleapis.com:443,
18444→oauth2.googleapis.com:443 via10.250.0.2:2222. NoSOCKS/genericCONNECT/public
listener/newService. Dedicated n8n-google-egress identity, mount/read-onlySecret,
existingtrustedVPSHostKeyAlias[socrat.alchemmist.xyz]:2224, StrictHostKeyChecking,
IdentitiesOnly/BatchMode, -F/dev/null, keepalive15s/count3/ExitOnForwardFailure.

NL authorized key APPENDED underlock, preservesexistinglines, source10.250.0.41,
restrict+port-forwarding, forced/bin/false, exactpermitopenONLYtwoGoogle443,
permitlisten127.0.0.1:1(non-rootcannotbind). No shell/agent/X11/PTY. No SSHdaemon/
VPNservice reload/restart. Owncustody ~/.config/homelab/n8n-google-egress0700;
privatekey0600. Secrets provisionednativeprivatestdin, neverGit/logs. Trusted
known_hostscopiedfromexistingpinnedcontrollerfile, NOT unauthenticatedkeyscan.

## Native transport

N8N_GOOGLE_SSH_EGRESS=1 selects scopedAgentwrapper. Same twoexacthosts/443,
existingIPv6/socket/nonGoogledelegation contract retained. OnlyTCPendpointbecomes
Podloopback; originalGoogleSNI, CA, identity/session/clientcertificate/cipher
verification remain. No TLSterminationatSSHsidecar, no Google credential changes.
ExactlyONEverifiedTLSsocket reachesHTTP. Failedtunnel failsclosed/no directpath
fallback. NoapplicationbytesbeforeverifiedTLS/noPOST/reply/requestr retries.
Old9.5swholebudget/2sconnectionbound unchanged; localforwardonlyonecandidatesocket.
OtherAPIworkflowskeepnativeconnections. NoHTTP_PROXY/HTTPS_PROXY/globalDNSvars.

Sidecar uses alreadyVenice-pinnedbrowserimage ONLYtoexecuteinstalledOpenSSH,
NOT Chrome/browser/bridge. UID/GID1000, noSA token, allcapabilitiesdropped,
read-onlyrootfs/noescalation,32Mi request/128Mi limit,100mcpu limit. Listener
readiness tests ONLYprocess/listening, notGoogleAPIacceptance.

## Deploy incident, correction and acceptance

Source55655e25/gatedcode; activation6cc2ec7e afterfreshglobalnaturalnativepending[]
andSPIowner/processing/paid0,related3admissionsonlypaused. FirstsidecarErrImagePull:
privateHarborpullrefwasmissing. This was MY rollout defect, notGoogle/Venicefault.
Pod1/2unready createdshortn8nserviceinterruption. Readinesswaittimedout, activities
restoredthenrepausedforGit-onlyrepair. OneCalendarerror49624retained. No history
removed/alertsmuted. Source2f26a12f addsnewnamespacepullreference toEXISTING
projectread-onlycluster-pullidentity; NOrobotrotation/VeniceSecretcopy. Freshglobal
pending[]/SPI0assertedagain beforecorrectivepush; norestart/deletion/liveoverride.

NewPod n8n-8679f69fc9-x8j9rReady2/2,restart0,ArgoSyncedHealthy. All7nativegraphs/
settings/credentialreferences/static/pin/activitiesexactbefore/after. N8NSecret
UID/dataSHA,PVC,DeploymentUIDsame. FullSPECdiffwhitelist ONLYextensionchecksum,
N8N_GOOGLE_SSH_EGRESS,SSHsidecar,ownSecretvolume,imagePullSecret. Same nativeimage/
dataPVC/placement/resourcesforn8n. VeniceDeploymentUID/specunchanged,ArgoHealthy.
Original6active/handlerinactive restored; n8nnotrolledagainforSPI-onlyrelease.

RealREAD-ONLYprobeusingownkey/temporaryin-memoryssh-agenton5: strictTLS1.3
www283ms/oauth247ms; example.com443/Google80/shellDENIED. NoauthenticatedGoogle
request/OAuthPOST/manualproductionworkflow/paidprobe/voiceevent. TLSend-to-end.
45NodeGoogleDNS/transport/Yandextests pass; TLSwinner/noPOSTreplay tests retained.
Finitepost-restore14naturalCalendar successes08:37–08:50UTC,zeroerror/canceled.
Extendfiniteobservationsbeforecloseout; NOT overnight/permanentguarantee,voiceor
refreshPOSTacceptance. Underlyingdirectpathissue andNL/SSHsinglepointremain.

RollbackrequiresfreshglobaldrainandGitgoogleEgress.enabled=false; preservesown
credentialcustody untiloperator-approvedrevocation. DirectGooglepathstillflaky.
RevokeONLYdedicatedkeyline/fingerprint; donottruncateauthorized_keys/rotatehostkey/
killVeniceSSHsession. ExistingSSHconnectionmustcloseforthatidentityonlytosustain
revocation. LostSSHkeynotpermissiontosilentlyreplaceowner/nativecredentials.
Privateproof /tmp/n8n-morning-20261117-private/google-egress-live/.

## SPI compaction follow-up (separate service)

Source8c89246 adds ALWAYS-before-final-model pipeline: rawmetric samples→observed
extrema/trends→losslesslabel/time/tablecompaction→explicitboundedprose→fulltoken
fit/admission. Compareoptionalvalue-dictionary/plainbydeployedcounter, notbytes.
Every100/100summaryrows survives,includinglastrowpeak; unknownformatsnotdropped,
sensitivelabelkeyskeepkeyedredaction,tableidentitiesnotexcerpted. Fulloriginals/
queries/artifactIDs/candidateslimits remain. NoextraLLMcall/budget/reset/schema/
workflowIDchange. Lastresortexplicitprefixfallbackstilldisclosesomissions.
Actualretained75e8…proof25618reservationwithinoriginal30000,ALL100rows/same10IDs/
candidate174/network&modelcalls0; oldminimal39595.469nativeCItests0skips.
Push44049556509successpublishesONLY; explicitrelease44050085445dispatchedafter
SPIONLYpause+freshglobalpending[]/owner/processing/paid0. Runtimeaccepted08:53UTC:newPodspi-triage-57c7cf45c9-2lltzReady/restart0,
image185bd5cdd5dda2381283e95bd57338ebfd7d6597b30a15d2238dde60aec71e6d,
ownedhomelabee921da6,ArgoSyncedHealthy. Exact5runtimefilehashes/health200,
DeploymentUIDsame/SPECdiffONLYworker+existingDBguardinitimages. SPIactivityand
business/static/pinrestoredidentical. NoN8N/VenicerolloutforthisSPIrelease.
Newlossless100rowmodel/reportnaturalacceptancePENDING:newrealjobonly,notreplay. Donotconfusewith2cfc5ccb'snaturalsuccess:
BOTHoriginalmorningcontextjobs completednormallyatattempt8/reporttrue BEFOREnew
compactionrelease. Theirhistoricalerrorstringsremain,notcurrentfailures.
