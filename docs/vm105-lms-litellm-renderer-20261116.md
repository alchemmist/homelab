# VM105: LMS accepted; LiteLLM and renderer rolled back —16Nov2026

> Historical handoff: placement below was superseded by the owner-authorized
> [post-transport retry](vm105-app-retry-20261116.md). Renderer/LiteLLM are now5;
> safety fences, retained data authority and DR limitations below still apply.

## Current authority, not intermediate green Pod status

Owner approved image-renderer, LMS application and LiteLLM application moves.
**Final accepted placement:**

| Component | Final node | Result |
|---|---|---|
| LMS web worker | socrat-5 | Accepted infrastructure/native login-start checks |
| LiteLLM proxy/UI | socrat-0 | RETURNED after real browser bulk-asset stalls on5 |
| Grafana image-renderer | socrat-1 | RETURNED after real alert render failures on5 |
| Grafana application | socrat-1 | Unchanged Deployment UID/spec/data |
| LiteLLM PostgreSQL | socrat-0 | Unchanged Deployment UID/spec/data |
| LMS database | Existing Deployment/CNPG topology | Unchanged |
| Rancher | socrat-1 | Earlier recovery unchanged |

img-proxy was NOT moved. Previously accepted workloads on5 were not moved back.
All3Argo apps final Synced/Healthy; one Ready/restart0 Pod per component. Final
node5 snapshot2591Mi RAM/6%,713m CPU/7%; capacity is not the present blocker.

## What actually passed

- LMS image/digest unchanged; single Recreate worker,45second graceful shutdown.
  Before switching submissions table EMPTY, after EMPTY, no interrupted checks or
  artificial exercise submissions. No concurrent LMS web workers. Original
  lms-data PVC remains retained and UNMOUNTED; runtime is PostgreSQL-only.
- Actual LMS Pod on5 authenticated to original DB: read-only SELECT1. Same native
  IdP HTTPS issuer metadata200. Public /auth/login uses same callback and PKCE S256.
  Real clean Chrome follows LMS -> Authentik and renders the full 'Log in to
  continue to LMS' username/password page with zero JS/request errors.
- Actual LiteLLM on5 reached original PostgreSQL, vLLM /v1/models with existing
  backend key, and IdP over verified HTTPS. WebUI's existing virtual key models200.
  These PASSED but were NOT sufficient to accept its UI: see failures below.
- Final LiteLLM back on0: machine models still200 with existing WebUI key; normal
  clean Chrome loads dashboard/login, clicks Login with SSO, and renders the
  'Log in to continue to LiteLLM' Authentik form; no JS/request errors.
- Final renderer back on1: real authenticated Grafana /render/d-solo/socrat-nodes
  returns PNG200,12840bytes,1000x500. Native minimum output size is1000x500 even
  with requested800x400; the initial800x400 assertion was a diagnostic mistake.
- Full final pre/post comparison:10referenced Secret objects UID/data EXACTLY
  unchanged, existing container env maps/images/mounts/volumes/graces unchanged;
  same Deployment UIDs; original PVC UIDs preserved; original Grafana and both
  checked DB Deployment specs EXACTLY unchanged. No account/password/role/key reset.
- No production inference/workflow runs, no user impersonation, no paid inference,
  alert silencing, fabricated student submissions or native auth bypass. Full
  human OAuth callback/account acceptance remains with owner, not claimed done.

## Why two moves were rejected

One successful PNG and green health were insufficient. With renderer on5, bounded
Grafana logs contained21render500 and3render429 records. Native alert callers
canceled around15seconds; subsequent Grafana error-template handling also failed.
Do not claim a clean pre/post failure-rate comparison: bounded logs are incomplete.
Actual production render failures, plus repeated acceptance failures, justified
return to original node1 locality. Existing auth, timeout, rate limits and2Gi
renderer memory/4CPU cap were not weakened to make the test pass.

LiteLLM /ui/HTML/APIs and one anonymous browser run worked on5; repeated clean
browser runs stalled on many /litellm-asset-prefix/_next/static/chunks/*.js requests.
Small health/API responses were not evidence of usable UI. Failed/pending JS
requests at browser timeout were aborted by diagnostic browser close; that alone
is not proof the server returned an error.

Read-only transport evidence:

- Same229044byte JS, node0 host ->Pod5:0.054/0.059sec; Pod0 ->Pod5:0.072/0.150sec.
- Pod1 ->same Pod5 object:5.753/15.345sec. Several public asset GETs timed out after
 15sec with only27–40KB received. Node1 image-pull delay in an initial large-image
 probe was distinguished from network timing; repeated test used already-cached
 LMS image and no credentials, no app startup, no service-account token.
- Guest5 Flannel MTU1370, WG config bound to wg-socrat; node1 WG MTU65456 and
 Flannel65406. Jumbo values are observed, NOT a proven causal diagnosis.
- Single reversible node5-only experiment clamped SYN/SYN-ACK MSS1240 for forwarded
 cross-node Pod TCP. It did NOT improve the path. Both exact owned mangle rules
 removed and absence verified, source script deleted. No permanent network change,
 no filter/NAT/mark/route/AllowedIPs/key/MTU/DNS changes or new accept rules.
 Do not infer MTU is ruled out; one ineffective test does not identify root cause.

Further moves of bulk-data/UI-heavy consumers to5 are deferred pending dedicated
1<->5 overlay/transport diagnosis. Bandwidth, packet loss, encapsulation/offload,
MTU and relay behavior need measured comparison; do not blindly alter node1's mesh
or declare that raising VM bandwidth alone fixes it. Other existing node5 apps can
share this path; a specific native API passing does not clear all traffic classes.

## Native issuer route and retained source safety

Public IdP IPv4 cannot be reached reliably from5, as found during Rancher recovery.
LMS now uses a narrow per-Pod hostAliases entry auth.socrat.alchemmist.xyz -> existing
Traefik ClusterIP10.43.218.222, same issuer/certificate/SNI/callback/PKCE/allow-group.
LiteLLM keeps the same scoped alias even after node0 recovery; no global DNS change.
If Traefik Service is recreated, review these aliases. No TLS verification bypass.

Upstream LiteLLM chart1.105.1 lacks hostAliases. Source now uses charts/litellm,
exact pinned OCI chart with its bundled dependencies and only TWO template-file
extensions: optional hostAliases and a fail-closed placement-only migration guard.
All165upstream files have original SHA256 inventory; tests reverse the two patches
and verify every hash. Final patched chart WITHOUT new options renders BYTE
IDENTICAL to original pinned OCI archive. Runtime imageID on5 prewarm matched the
original running0 imageID; no version upgrade. Provenance in README.vm105.md.

Previous migration Job had SUCCEEDED and was already deleted before this move;
source migrationJob.enabled=false prevents it being recreated just for placement.
Original DISABLE_SCHEMA_UPDATE=true had been supplied conditionally by that chart;
final pre/post env check caught its temporary omission. Explicit original fence
restored through owning values, another natural rollout, all final env maps equal.
Read-only _prisma_migrations audit: ZERO newly applied or unfinished migrations
since20:45UTC15Nov, final runtime fence true. Latest placement Argo operation has
NO Job task. Do not call the temporary fence omission harmless without that audit.

migrationJob.placementOnlyImage pins1.105.1; changing image version FAILS rendering
until normal upgrade/migration handling is reviewed and re-enabled. DO NOT bypass
it or silently keep disabled migrations on future releases. Main Ansible playbook
now uses the same canonical values and local pinned chart, not old node0 snapshot.
Legacy monitoring helper refuses a direct OCI upgrade of this Git-chart managed
release instead of silently undoing route/placement/SDK configuration. No Ansible
production deploy/secret initializer or brand/user reconciliation was run here.

## Source, receipts, cleanup and pending work

- Renderer move decdd4d5; LMS move518102d4; pinned chart2af76bde; no-hook staging
 4af40887/f639a67c; LiteLLM attempt2a71545d; runtime fence d2e1b0ac;
 automation guards24d446f6; renderer recovery5f353cc2; failed MSS experiment
 4f9288d3; LiteLLM recovery + experiment removal a2a9739a.
- Six targeted unit tests, all3owning chart Helm lints, original-vs-local byte
 equivalence, actual backend SQL/native OAuth/real PNG/browser checks. Stock
 extraEnvVars map/list lint warning retained, not an ignored runtime error.
- Five exact-owned preflight/bulk probe Pods deleted; no test credentials created;
 original secrets/PVCs/DB data left intact. No forced production Pod deletion,
 blanket sync/prune, shared monitoring stash/reset/force push or VPN/Mac changes.
- Private0700/0600 preimages/logs/receipts:
 ~/Library/Application Support/homelab/vm105-render-lms-litellm-20261115.
 Midway acceptance with all3on5 was SUPERSEDED by final acceptance after recoveries.
- Deployment data was not moved; no VM backup/cold boot/full restore proof implied.
 Existing VM backup enrollment, cold-start acceptance and temporary SSH-key cleanup
 remain pending. User's prior 'всё нормас' confirmed chat availability, not a new
 full transport/DR acceptance. Owner should verify normal LMS account access.
