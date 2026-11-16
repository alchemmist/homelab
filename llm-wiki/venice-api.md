# Venice browser bridge — server candidate, 16 November 2026

## Requirement

Venice WEB UI only, not paid official API. Dedicated real Google Chrome profile
for owner account agaga; normal operation must not require repeated interactive
logins. Google can still revoke a session or require MFA; persistent profile is
not proof of indefinite authorization. Initial Linux Google login is owner-only.

## Current deployment

Production venice-api remains unchanged and still uses Mac reverse CDP tunnel.
Do not describe production as Mac-independent yet.

A separate candidate is now deployed through the existing Argo Application and
charts/venice-api/templates/browser-candidate.yaml. Source b45fbfe6. Browser code
in alchemmist/venice-api branch browser-candidate, source 59c1c8b.

- Deployment venice-browser-candidate in namespace venice-api, pinned socrat-5,
  one replica, Recreate, stable hostname venice-browser.
- Real Google Chrome157.0.8103.78, headful Xvfb, sandbox not disabled. No cookie
  export/import, password injection or stealth scripts in this browser runtime.
- Immutable image harbor.socrat.alchemmist.xyz/homelab/venice-browser@
  sha256:10f6a5c13bfbaee22ae1648d34f454a9537e3f4da5004f7218b2035214f9708b.
- PVC venice-browser-profile, local-path venice-browser-retain SC, 10Gi request,
  RWO, actual PV Retain, node affinity socrat-5. This is local storage, NOT HA or
  proven off-node backup/DR. Profile /data/profile is private0700, single-writer
  process lock in addition to Chrome's own lock.
- Egress container runs native ssh -N -D127.0.0.1:1080 to mesh10.250.0.2:2222.
  Dedicated key secret venice-browser-egress; original owner host pin preserved.
  Authorized key restricted to source10.250.0.41, forced /bin/false for shell,
  port-forwarding only web80/443; remote listen restricted to privileged
  loopback port1. Do not broaden owner SSH rights or copy Mac private keys.
- NetworkPolicy denies ingress and external direct egress; allows only VPS SSH
  plus kube-system DNS. CDP9224 and password-protected VNC5900 are loopback-only.
  No public Service/Ingress/hostNetwork for candidate. No Kubernetes API token.
- Operator secret venice-browser-operator contains VNC password file. Private
  controller custody is ~/venice-auth/server-browser (0700/0600), not Git.

## Fresh acceptance

- Candidate pod 2/2 Running, Argo Synced/Healthy. This is process readiness, not
  authenticated inference readiness.
- curl via candidate SOCKS: venice.ai200; external exit-check109.120.141.60.
- Real browser opens Venice Agent page (guest) and Google Accounts login200.
- Dedicated machine key cannot execute /bin/true: forced shell exits1.
- Proxy request to non-web port81 denied; direct external1.1.1.1:443 denied.
- Candidate pod recreated twice. Persistent profile marker survives remount;
  SSH tunnel reestablished with VPS exit, no dependency on Mac reverse tunnels.
  This DOES NOT yet verify persistence of authenticated Google/Venice sessions.
- Operator VNC RFB3.8 password authentication independently passed.
- Existing production venice-api pod preserved, no restart or image override.

## Operator login and remaining gate

From an authorized Kubernetes client run the venice-api repository's
scripts/browser-operator.sh (or kubectl -n venice-api port-forward --address
127.0.0.1 deployment/venice-browser-candidate 5901:5900 9224:9224).
Open vnc://127.0.0.1:5901. Password is in the controller private file
~/venice-auth/server-browser/operator-password; never paste into chat/Git.
The port-forward is only a display/admin path. Closing it does not stop Chrome,
the persistent profile, or VPS egress. Recreate the forward after pod replacement.

Owner must complete initial Google agaga login in this server Chrome. No owner
password/MFA has been requested or captured. Then authenticate Venice via Google.
Afterwards verify exact model inference, restart-session persistence and actual
Venice session recovery through already logged-in Google. Only after these gates
may production CDP be handed off; existing candidate ingress policy and
loopback-only CDP require an explicit co-located bridge or narrowly scoped change.
Do not simply set production CDP_URL to candidate PodIP: it cannot reach loopback.
Old bridge DOM parsing and fail-open model-selection flaws remain outstanding.
