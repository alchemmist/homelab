# Venice browser API — Mac-independent production, 16 November 2026

## Current state (supersedes candidate-only/initial-login notes)

Public https://venice.socrat.alchemmist.xyz now routes to the bridge beside the
server Chrome on socrat-5. Old Deployment venice-api has desired replicas0.
The live Deployment retains the name venice-browser-candidate to preserve its
profile/PVC identity; it is now the production backend, NOT a second test writer.
No Mac browser, Mac HTTP proxy, or reverse SSH tunnel is in the serving path.

Requirement: Venice WEB UI through real Google Chrome, not official paid API.
Owner completed initial Google agaga login in the dedicated server profile.
Venice was initially Guest; ordinary Continue with Google signed it into the
existing owner account without password/MFA. No Google passwords handled by code.

## Ownership and runtime

GitOps: existing Argo Application venice-api, charts/venice-api plus
 deploy/venice-api/values.yaml. browserCandidate.enabled/bridgeEnabled/serveApi
are true. Service venice-api selects app=venice-browser-candidate. Legacy
hostNetwork/proxyServer/cdpUrl values cleared. No live image overrides.

Pod containers:
- chrome: real Google Chrome157.0.8103.78 + Xvfb, dedicated /data/profile,
  Default profile, sandbox enabled, no cookie injection/stealth. Image pinned
  to sha256:10f6a5c13bfbaee22ae1648d34f454a9537e3f4da5004f7218b2035214f9708b
  in harbor.socrat.alchemmist.xyz/homelab/venice-browser.
- egress: same image, native SSH -N -D127.0.0.1:1080 to10.250.0.2:2222.
  Dedicated venice-browser-egress Secret, existing VPS host key pin. VPS
  authorized key limited to source10.250.0.41, forced false shell, web80/443
  forwarding only; remote listen limited to privileged loopback1.
- bridge: canonical .Values.image repository/digest, CDP on127.0.0.1:9224,
  existing API_KEY from venice-api-env, public API on8080. bridgeImage override
  empty so ordinary CI/deploy-to-socrat releases update the live sidecar.

One replica/Recreate, stable hostname venice-browser, no API serviceaccount token.
PVC venice-browser-profile, 10Gi request, local-path venice-browser-retain,
RWO, actual PV Retain and node affinity socrat-5. Profile0700, process lock and
Chrome single-writer lock. This is local persistence, NOT HA/off-node DR.

NetworkPolicy denies direct external egress; permits only VPS SSH and DNS in
kube-system. Ingress only8080 (API bearer required); CDP9224 and VNC5900 bind
pod loopback, not publicly exposed. No hostNetwork.

## Authentication and response behavior

Bridge checks actual non-Guest account state, not merely account-menu existence.
Background startup/15s maintenance reuses the existing Google session if Venice
needs sign-in, serialized with request navigation. Password/MFA/identity selection
or consent is not bypassed; operator verification may still be required if Google
revokes its session. Persistent Google login is not an infinite-session guarantee.

Exact model DeepSeek V4.1 Flash Uncensored is verified before sending. Missing
selector or unsupported requested model fails closed. Assistant text is read from
.assistant .assistant-content .prose, never by cutting whole-chat text or deleting
legitimate answer lines. Generation deadline errors are not reported as normal stop.

SSE is deliberately BUFFERED until the DOM answer is final: Venice can rewrite
partial Markdown and append-only forwarding corrupted it in acceptance testing.
Initial role event + keepalive comments are sent while waiting; final assistant
text/stop/[DONE] follow. This is not native token streaming. Roles remain flattened
into a prompt; temperature/top_p/max_tokens and tools are not native backend API
semantics. Do not advertise full OpenAI feature compatibility.

## Acceptance evidence

- Direct server SOCKS Venice200, independent exit109.120.141.60.
- Direct external1.1.1.1:443 denied, proxy port81 denied, machine shell denied.
- Google/Chrome profile survives pod replacements; authenticated model pong
  passed after replacement, without owner relogin.
- Scoped Venice cookie clear (Google cookies untouched) redirected to /sign-in;
  automatic Google recovery then returned pong. This also found/fixed Guest
  account-menu detection and pre-login navigation ordering.
- Public endpoint: anonymous401, unknown model400, pong, long prompt -> violet.
- Public buffered SSE repeated twice, exact integers1..20 and [DONE].
- Obsolete Mac Venice reverse tunnels were absent; old Mac Python HTTP proxy
  explicitly stopped. Public pong and both SSE tests passed with them off.
- Eleven unit tests passed in the application image, including exact-model
  refusal, Guest detection, unmodified assistant text and DOM rewrite buffering.
- Process readiness/Argo Healthy is NOT a continuous model inference guarantee.

Source in alchemmist/venice-api main, release source8fc7600; browser-candidate
branch is retained as history, not the canonical development branch. The older
venice-api/docs audit is historical; this runbook records current acceptance. Current effective
image digest must be read from values/runtime; CI may publish a new digest of
that source after the initially accepted manual immutable image.

## Operator access / custody

Run scripts/browser-operator.sh from venice-api checkout on an authorized client.
Open vnc://127.0.0.1:5901. Password is in controller private file
~/venice-auth/server-browser/operator-password; never paste in chat/Git.
venice-browser-operator Secret stores its VNC password file. Controller custody
0700/0600; no runtime dependency on controller or /tmp files.

Closing port-forward only closes operator display, NOT Chrome/egress. Reopen the
forward after pod replacement. Do not terminate the owner's Mac Chrome or touch
its profile: it is no longer involved. Do not start another Chrome on the server
profile, broadly change VPN/DNS/routes, expose CDP/VNC, or promise session immunity.

Remaining: off-node profile backup/restore acceptance, extended soak and actual
Google-session revocation recovery (requires human if password/MFA requested).
Normal recovery uses Google SSO and was tested; full Google logout/revocation was
not deliberately induced. Any future browser image update requires rechecking
sandbox, SSO and DOM selectors before production handoff.

## Final CI and live closeout

GitHub Actions43866523454 completed SUCCESS for source8fc7600. Native release
updated canonical image through deploy-to-socrat; Argo reconciled40c1b553 and
recreated production pod with image
sha256:84244bd0d88e6669ed8bfa69adefbaab669a3e34a6f9910fee187de1f0209ffa.
No image override, Google relogin or Mac proxy was used after this rollout.
Fresh public checks after CI rollout passed: pong, four exact answer lines
(assistant/private/DeepSeek is a model/sources preserved), SSE pong+[DONE],
anonymous401 and health authenticated=true. VPS exit109.120.141.60 repeated.
Argo Synced/Healthy, one production Pod3/3; old standalone deployment0/0.
