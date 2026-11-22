# n8n service-VPN correction —17 November2026

Owner rejected the prior ad-hoc SSH-to-NL implementation. Explicitly authorized
replacement by a service identity in existing3x-ui, its subscription and a Pod
VPN client. No AI delegation. Current standard: [runbook](../network/service-vpn-egress.md).

## Implemented

Native3x-ui client `svc-n8n-google`, ID40, enabled, only existing inbound32053
(VLESS/REALITY/XHTTP). 5GiB total quota,90day expiry,limitIp1. These are explicit
new-client parameters, not resets of existing traffic. Panel19clients: previous
18 full identity/config rows and their bindings remained exact. NativeAPI only;
noSQLwrites, shell passwords/MFA/owner accounts not reset. Temporary admin/worker
tokens removed and original tokens preserved by NativeSession cleanup.

Native JSON subscription for that same client is in automation/n8n-service-vpn.
No subscriptionURL/credentials inGit/logs. Node init gets it with verifiedHTTPS,
no redirects,8s/256KiB bounds; imports one expected Moscow VLESS/REALITY outbound.
Adapter only prepares config; VPN transport/crypto is official Xray26.10.21 from
pinned existing3x-ui image. No manually invented tunnel/credentials. Onlytwo
loopback dokodemo-door inputs targetGoogleAPI/OAuth443; imported direct routing/
publiclisteners removed. Profile retrieved atPodstartup, not unattendedhotreload.
Unknownendpoint/protocol/profile failsclosed; noSSH/directfallback. End-to-end
GoogleTLS retained; noHTTP/OAuthPOSTreplay. OtherAPI traffic staysnative/direct.

Client config lives in mode0600memoryemptyDir, notPVC. NoSA token/hostNetwork/
NET_ADMIN/TUN. Moscow→NL service/infrastructure existing path preserved; noWG/
NetBird/MTU/routes/DNS/firewall/daemon changes. Google credentials/native n8n
identity preserved. Venice deployment, profile/session/keys untouched; itsSSH
approach is separately marked deviation, not recommended template.

## Tests and rollout

48Node tests passed: subscription import/policy/no arbitrarypublicproxy/no direct
outbound, nativeCA/SNI/preHTTP/noPOSTreplay, scopes andrender. Official image
prefetched on5BEFORE pausing admission. Read-only realclient staging using own
subscription with exact approved runningcore: GoogleAPI/OAuth verifiedTLS HEAD
404 in373/272ms. RootHEAD404 is expected, notAPIfailure.

Source5b722c5c pushed AFTER relatedSPI/Calendar/Yandexadmissions paused and fresh
ALL native pending[]/SPIowner/processing/paid0, asserted againimmediatelybefore
push. No execution cancellation/replay/alertmute/paidprobe/quotareset. Argo
reconciled normally; newPodn8n-7bc974f784-cbbfn Ready2/2,bothrestart0. Restored
original6active/handlerinactive activities. All7businessgraphs/settings/native
credentialrefs/static/pin/activityexact; encryptionSecretUID/dataSHA/PVC/
DeploymentUIDsame. NoSPI/Venice rollout or liveDeployment override.

Runtime HEAD via inheritedGoogleadapter: Google404/TLSverified/vialoopback301ms,
OAuth404/TLSverified/vialoopback145ms; GitHub200/TLSverified/NOTloopback215ms.
Init logonlyVPN_SUBSCRIPTION_PREPARED. Xray26.10.21 exactrunningbinarySHAverified.
Initial byte-exact configcompare failed because native3x-ui randomly selects a
RealityshortId per render. Onlythatpathdiffers; verified against live inbound
allowedshortIds, remainingownidentity/transportexact. Neverdisabledverification
or rewroterandomnativeparams toforceequality. RuntimeSSHflagabsent/serviceVPN1.

Firstattempttocopypubliccorethroughkubectlexec hitwebsocketEOF onlarge stdout;
no network repair attempted. Used authorized nativeSSHread of runningexecutable
andverifiedSHA againstsmallkubectlexec output, onlyforownedread-onlystaging. Probe
process/binary/configremoved. This is diagnostictransport, NOT productionegress.

## Removed rejected implementation

Onlyafter replacement Ready/strictTLS and two naturalCalendar successes:
removed exactown `n8n-google-egress-20261117` authorizedkeyline underfilelock;
all otherlines preserved. OldPod/SSHsidecargone. Deleted ONLYownunused
n8n-google-egress andn8n-google-egress-pull Secrets, NOTsharedregistryrobot.
Oldprivatecustodyretired outsideGit, historicalreceipts preserved. NoVenice/
operator key, SSHdaemon, listener orsession changed.

## Finite acceptance and limits

8naturalCalendar successes12:17:14–12:24:14UTC,zeroerror/canceled inthatwindow.
N8N/SPI/VeniceArgoSyncedHealthy. Notovernight/HA/permanentavailability, voice/
Telegram delivery orrefreshPOST proof. ExistingVPNservice/NLpointsoffailure
remain. Track nativeclientexpiry/quota in3x-ui; noautomatedrenewal promised.

Currentdocs6065eac3registercorrectstandard andwarnhistoricalSSHreports. Private
receipts /tmp/n8n-service-vpn-private/; protectedpanel preimages/intents at
/var/lib/homelab-service-vpn/n8n-20261117 onNL. Do not print/substitute URLs or
reuse this client's credentials for another service. Do not blindly replay
provisioning: ID40alreadyexists. Newservice needs own nativeidentity.
