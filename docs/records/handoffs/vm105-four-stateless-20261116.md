# VM105: four additional application-only moves —16Nov2026

> Later owner-approved stateful batch also moved Monori backend+sync and SPI
> worker/data to5. Their remaining-on0/1 protection checks below are historical
> evidence for THIS earlier frontend-only handoff, not current placement. See
> [current stateful handoff](vm105-stateful-20261116.md).

Owner approved exactly blog-updates-worker, wiki-openapi-worker, SPI queue UI and
Monori frontend. No stateful backend, business job or native identity migration.

## Accepted placement

| Workload | Before | After | Protected scope |
|---|---|---|---|
| blog-updates-worker |1 |5 | single Recreate, WRITE_ENABLED=false unchanged |
| wiki-openapi-worker |1 |5 | single Recreate, WRITE_ENABLED=true unchanged |
| spi-queue-ui |3 |5 | worker/storage/GitHub broker remain unchanged |
| Monori frontend |0 |5 | monori-back + monori-sync and hostPath data remain0 |

All4one Ready/restart0 production Pod on5. Existing Deployment UIDs preserved.
Argo SPI/Monori Synced Healthy. Workers are owned by checked-in manifests and
normal deployment helpers, not falsely described as Argo-managed applications.

Source before production changes: b0526df3 (merged/pushed as c186c494), guarded
handoff correction4aecc85e. Owning source:

* `deploy/blog-updates/worker.yaml`: only Deployment nodeSelector5 added.
* `deploy/wiki-openapi/worker.yaml`: only worker Deployment nodeSelector changed;
  broker CronJob/node1/RBAC/Secret management untouched.
* `deploy/spi-triage/values.yaml`: queueUI.nodeName5 and one hostAliases entry.
* `charts/spi-triage/templates/queue-ui.yaml`: optional UI-only hostAliases;
  default empty list, no backend/RBAC/jobs/NetworkPolicy modification.
* `deploy/monori/values.yaml`: frontNodeName5; chart default0 and frontend-only
  configurable selector. Back/sync node0 and images/storage unchanged.
* `scripts/vm105-stateless-handoff.py`: source-based single-worker service
  quiesce, read-only idle checkpoint, ordinary Recreate, canonical Service
  restoration in finally. No workflow invocation, secret initializer or force.
* `deploy/migrations/vm105-four-stateless-20261116/drain-services.yaml`: guarded
  TEMPORARY Service selectors, not an Argo application source. Do not apply as
  an ordinary final manifest. Both production Services restored after handoff.

## Preflight and worker drain

Fresh private0700/0600 snapshots/receipts, outside Git:
`~/Library/Application Support/homelab/vm105-four-stateless-20261116/`.
Saved Deployment/Service identity+spec, referenced credentials, protected
backends, worker code/prompt ConfigMaps and broker CronJob.3owned diagnostic
Pods on5 ran only sleep/read-only probes, unique labels excluded them from
production Services/ReplicaSets. No worker process or duplicate stage executor
was started in those Pods. They also prewarmed exact runtime images.

Actual5 preflights: existing scoped GitHub credentials GET repo metadata200,
PyPI pinned-version metadata200, existing LiteLLM key `/v1/models`200, no
inference. Both n8n workflows remained enabled; authoritative SQLite was opened
read-only and showed no running/new/waiting executions at preflight. No
workflow configuration/execution/credentials were changed or manually rerun.

Old worker servers have no dedicated drain API. The helper therefore:

1. Verifies PID1 is original Python server and3consecutive single-thread idle
   checks, before pausing service (wait for a long existing stage while service
   remains available).
2. Applies ONLY selected checked-in temporary Service, whose extra selector
   matches no Pod; waits for zero ready EndpointSlice addresses.
3. Waits again for old accepted/lock-queued handler threads to finish (PID1/task
   count; never reads task bodies or credentials).
4. Applies ONLY selected canonical worker Deployment; replica1/Recreate gives
   no old/new business-worker overlap. Original30s termination grace unchanged.
5. Checks new direct Pod health200 and restores ONLY canonical Service in a
   finally block. It does not promise continuous availability to new callers.

Observed service pause windows (UTC):

* blog:07:35:27.039–07:36:06.942,39.9s;
* wiki:07:36:11.839–07:37:00.423,48.6s.

No active request was force-stopped and no force-delete/grace reduction used.
Do not claim SIGTERM exit-code0: default lifecycle grace remained in place; the
proof is idle-before-replacement, not an instrumented graceful-exit handler.
Read-only authoritative n8n check after handoff showed zero execution records
for these two workflows since maintenance began07:34:34Z, hence no observed
workflow run/failure in those pauses. This is not a zero-downtime guarantee for
arbitrary future callers; future handoffs need the same controlled window.

First blog attempt stopped before Deployment modification: Kubernetes emitted
`endpoints:null`, the initial helper expected a list. Finally restored Service
in~2.1s; old worker stayed1. Corrected null handling and added regression test
before retry. Failed receipt retained separately, not overwritten. No claim of
an uninterrupted service window over that initial attempt.

## SPI native SSO and backend boundary

5's public IdP path still fails. A preflight using exact hostname/SNI and normal
verified HTTPS to existing Traefik ClusterIP10.43.218.222 returned discovery200
with the same issuer. Added ONLY queue UI hostAliases:
`auth.socrat.alchemmist.xyz →10.43.218.222`. Public issuer, certificate/SNI,
callback, client credentials, PKCE S256, group policy, allowed egress and
machine-control API remain unchanged. No global DNS/TLS bypass or public5
listener. Review alias if Traefik Service is recreated.

Actual new UI Pod, under its existing NetworkPolicy, passed:

* issuer discovery200 over verified TLS, exact existing issuer;
* fixed backend `/operator/queue/list` with its existing mounted control token:
  HTTP200/JSON object, read-only operation, no queue content printed;
* UI anonymous `/queue/api/list` with valid public Host/Origin:401 AUTH_REQUIRED.
  No cancel, dispatch, retry or queue write endpoint was exercised.

Clean browser: normal SPI entry ->full Authentik Email/Username form,4.99s,
no JS errors, failed requests or server5xx. Separate check confirmed native
HTTPS authorization URL, exact `/oauth/callback`, and S256. No human account,
MFA, operator-group role or authenticated session impersonated. Existing UI
sessions are bounded process memory; restart can require ordinary login again,
not a credential/group reset. Full human callback acceptance remains owner-led.

## Monori frontend and protection of finance data

Exact existing frontend digest and imagePullSecret retained. Public landing
HTTP200, clean browser1.35s, no JS/errors/failed requests/server5xx. Clicked only
native Sign in; `/login` password form visible. No credentials entered, account
created, import, sync, demo mutation or finance transaction performed.

Inside actual new frontend, through unchanged nginx proxy to back0:

* `GET /openapi.json` ->200,0.055s (schema only, not personal ledger data);
* anonymous `GET /api/snapshot` ->401,0.021s; public HTTPS same path ->401.

Backend/sync Deployment UIDs and full specs EXACTLY unchanged, still node0;
source render comparisons prove no Secret/Service/Ingress/backend/storage
object change from the frontend placement option. No hostPath/PVC data copied
or declared stale, and no claim of authenticated ledger/account acceptance.

## Final invariants and caveats

* Every target Deployment UID/full spec unchanged after removing only the
  intended nodeSelector and queueUI hostAliases difference. Images, container
  commands/args/env, mounts, resources, probes, grace, write modes preserved.
* All4Service UIDs/VIPs/full specs exactly match preimages. Neither temporary
  drain selector remains. No production Pod manually deleted.
*6static referenced Secrets UID+data unchanged. `wiki-openapi-github` UID/key
  names unchanged; token data renewed by the normal broker cadence, not frozen,
  rolled back or printed. Broker CronJob UID+spec unchanged. Do not claim every
  token byte stayed immutable across a legitimate broker refresh.
* Protected SPI worker and Monori back/sync UID+spec unchanged; worker code/
  prompt ConfigMap UID+data unchanged. No workflow replay or GitHub write probe.
*3owned preflight Pods deleted normally; no new account/token, permanent
  security grant, network-policy expansion, tunnel/router/MTU change or database
  migration. Shared browser profile, Mac VPN/routes/DNS left alone.
* Final sample5:235m CPU/2%,4288MiB RAM/11%; capacity not proof of DR/HA.
*5new targeted offline tests pass, including null EndpointSlice regression.
  Existing SPI OIDC suite:15pass/1KNOWN BASELINE failure. The old test requires
  production OIDC disabled despite its already-approved/live enabled source;
  same failure reproduced on clean baseline d11079aa. Not introduced or hidden
  by this migration; no unrelated auth setting/test was changed to green it.

Existing relay0 dependency for1↔5 remains. Earlier renderer first500/UI canceled
navigations and SDK verification caveats are not erased by these four moves.
VM full backup/independent restore/cold boot still separate and unproven.

## Rollback

For workers, publish original placement (explicit1 for deterministic rollback),
quiesce ONLY the selected Service, wait handler idle, ordinary Recreate, restore
canonical Service. Do not rerun an old payload or roll back refreshed broker
credentials. Helper deliberately refuses already-on5 replay; rollback must be
reviewed for its reversed target/known state, not blind helper reuse.

For SPI UI, revert ONLY queueUI.nodeName to3 and remove its scoped hostAlias if
restoring exact prior placement; do not remove OIDC, reset sessions/accounts or
sync/reconfigure SPI backend/storage. For Monori, revert ONLY production
frontNodeName to0. Commit/push owning source, targeted refresh and native checks.
No data rollback is needed for these four stateless frontends/workers.
