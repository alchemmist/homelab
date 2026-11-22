# SWE Mini: Monori autonomous maintenance

> **Retirement in progress.** The owner retired this service. The image release is
> disabled; do not dispatch it, provision credentials, unpause the queue or merge
> homelab#462. The steps and receipts below are historical, not operator instructions.
> A separate Git change removes the Application only after the foreground finalizer
> is observed on the live child. Do not treat either Git change as a live receipt.

## Historical architecture (acceptance pending at the time)

Owning Application: `deploy/argocd/apps/swe-mini.yaml`; local chart `charts/swe-mini`,
values `deploy/swe-mini/values.yaml`. Implementation and hash-locked dependencies:
`services/swe-mini`. Activation is requested (`enabled:true`), but the chart
renders NO controller until the native release has written its first immutable
image digest. Private prerequisites have been provisioned. This document is not
evidence of a running agent; inspect actual release/Argo/queue state.

Single Recreate controller on socrat-5, SQLite queue on a protected 2Gi PVC.
One active work/review job globally. First run is a provider-backed synthetic shell
acceptance; the next Monori run is admitted automatically without the usual idle
interval. Then rotate backend, frontend, security, polish and tests. Continuous scheduling, at least30minutes between task admissions;
100model steps /4500agent seconds,6900job seconds, no automatic retry of failed
jobs. The next queue task starts independently of model termination. State survives
controller restart; current Jobs continue without the laptop. This is not HA or
an off-node backup. Current single-page Venice provider serializes generation;
more concurrent agents would mostly wait and time out, not increase throughput.

A fresh job clones public `alchemmist/monori` at an exact SHA and installs locked
project dependencies. It runs baseline Python unit tests (excluding integration),
frontend tests, and production frontend build. mini-swe-agent v2.4.6 is invoked
through noninteractive `DefaultAgent.run`, not the interactive `mini` REPL.
It can execute Python/Node, start local services, use Playwright Chromium and
research public HTTP(S). This is a disposable Kubernetes container, NOT nested
Docker or a separate VM; no host Docker/containerd socket or privileged DinD.
Full compose/integration environments are not yet implemented.

Candidates must be small UTF8 regular-file changes to server/app, server/tests,
web/src, web/tests or common (20files/350KB maximum); dependency upgrades, CI,
deployment, migrations, tooling and agent instruction changes are not published.
All baseline and post-checks must pass; model completion alone is insufficient.
Worker results have per-run/per-phase HMAC authentication derived from durable
controller-only state. The wrapper removes result authority before spawning any
child and sets Linux PR_SET_DUMPABLE=0, denying same-UID child access to parent
/proc environ/memory/stdout. The build tests this boundary. This prevents a trivial
agent-written forged PASS marker; it does not prove semantic correctness of tests.
A separate fresh container installs dependencies from scratch and tests the exact
candidate BEFORE running any reviewer-model commands, avoiding trust in a work
agent's writable .venv/tools. Then mini independently reproduces/reviews it;
reviewer modifications reject publication. Model review is fallible and is not
independent-model consensus. Trusted controller, not the agent, creates the branch
and PR via GitHub Git Data API, then leaves merge to the owner. At most5open mini
PRs. Existing PR Agent may review according to its installed app policy; do not
claim it ran without a real check/comment. Reports inform following jobs to reduce
duplicates; this is not a perfect semantic finding-deduplication service.

## Credentials and isolation

`python3 scripts/provision-swe-mini.py` creates missing private prerequisites only:
- model-only LiteLLM virtual key restricted to `venice-deepseek`, parallelism1;
- pull credential from existing project robot;
- trusted controller's GitHub App signer from the existing PR Agent installation.
  Installation tokens request only Monori contents/write and pull_requests/write.
  Reusing the signer is an explicit trust coupling to PR Agent; a dedicated App
  would improve separation and requires owner installation. Agent pods receive
  neither signer nor GitHub tokens nor Kubernetes serviceaccount tokens.

No production Monori volumes, bank credentials, databases, sessions or API keys.
Non-root/cap-drop/seccomp/read-only image, emptyDir per job, cpu/memory/ephemeral
limits plus namespace quota. Worker NetworkPolicy blocks inbound and private,
node, metadata and mesh egress except DNS and LiteLLM4000; public80/443 permitted
for source/dependencies/research. This is NOT domain-level egress filtering:
public production endpoints and public third-party services are technically
reachable; prompts explicitly prohibit probing them. No guarantee against a
malicious repository/package exploiting the container kernel or leaking its
scoped model key. Production attack surface scanning is not configured.

No synthetic banking activity, prod workflow execution, merge, release, cluster
mutation or paid-model fallback. Venice browser login/VPN remains untouched.

## Release and operations

`SWE Mini Release` tests boundaries, builds an immutable full-SHA Harbor image,
then calls existing `deploy-to-socrat@v1` in the SAME publish job (`app:swe-mini`).
CI never calls Argo sync. Prerequisites are Secrets outside Git. Bootstrap uses
an explicit empty-digest fence: activation is already requested in both values,
but no controller is rendered before the first successful native release records
its digest. Secrets must exist and offline/server dry-run must pass before this
release. Argo then activates automatically, without a manual laptop-side step.
No live image override. The first hosted-runner push stalled on large blob uploads;
registry observed partial transfers/client disconnects, not a missing robot grant.
The image now uses a slim Python base, separate dependency/browser layers, headless
Chromium only and OCI zstd compression. The existing isolated BuildKit TLS workaround
from `docs/harbor.md` is retained; no ingress/global TLS/VPN settings were changed.
CI has a bounded60minute budget for the observed slow external upload path.

Pause new tasks with `paused:true` in Git; active job/review finishes. Set
`enabled:false` to stop controller (not an emergency cancellation of existing Jobs).
Emergency worker cancellation is a separate bounded operator action; do not
blanket-delete workloads. PVC has Prune=false/Delete=false; never delete it to
reset queue. Worker Jobs TTL1h after completion to bound retained node-local checkouts/dependencies;
review proposal ConfigMaps removed on completion.

Read-only inspection:
```
python3 scripts/swe-mini-status.py
kubectl -n swe-mini get deploy,pods,jobs,pvc
kubectl -n swe-mini logs deploy/swe-mini-controller --tail=50
kubectl -n swe-mini port-forward svc/swe-mini-controller 9090:9090
# http://127.0.0.1:9090/healthz and /metrics; no public ingress
```

The private /metrics endpoint exposes queue-state counts. This cluster uses OTel
as sole scraper with a frozen native scrape bundle; a new ServiceMonitor would
NOT be collected. Custom queue metrics/dashboard/alerts are NOT yet integrated;
standard Kubernetes deployment/job health remains visible to platform monitoring.
Do not enable a second Prometheus scrape path as a shortcut. Worker result envelope in
private Pod logs is gzip/base64 JSON, NOT encryption; it includes candidate text,
report and bounded command-log tail, never intentionally keys. Full trajectories
and commands remain only in disposable job storage until TTL, not in the durable
queue. Queue database retains reports/checks/candidates/reviews/PR URLs; access via
trusted controller, keep copies private. No Grafana dashboard/alert acceptance
or artifact off-node retention is implied by the private metrics endpoint.

## Acceptance gates

Must separately prove: native image release, Argo Synced/Healthy, correct node and
imageID, scoped model route, isolated worker shell and tests, denied private/metadata
egress, persisted queue recovery, independent review and actual PR. A running
controller alone is NOT proof of a complete autonomous engineering pipeline.

### First live acceptance (2026-11-17)

Native release44145648310 succeeded; GitOps commit6e918a1f recorded immutable
`sha256:f48c542932282dc9274922d076661ffba4dcfb777fe486a618093a90b1926073`.
Controller Ready on socrat-5, PVC Bound, Argo Synced/Healthy. Real provider smoke
261117184641-9f68e finished Submitted: synthetic shell marker and multiple calls
both passed; controller authenticated the result. The next Monori backend Job
261117184946-f9bf3 started automatically, proving continuation without a laptop.
It failed before model execution on an existing npm peer conflict: charts9.5.2
requires core9.5.2 but main pins core9.6.0. Main-branch CI44020975264 also fails.
No actual improvement PR or end-to-end publication has passed yet.

Bootstrap exception: when frontend dependency installation fails, the agent can
propose EXACTLY web/package.json + web/package-lock.json (combined <=600KB).
Only semantic-version changes to EXISTING dependencies/devDependencies are allowed;
no package additions/removals, scripts/engines/metadata changes, source mixing or
nonstandard registry URLs. Controller compares against original manifest fetched
from GitHub at the exact revision, independently of model claims. Backend baseline
must pass; the repaired candidate's ENTIRE test/build suite must pass. A fresh
review environment must install the candidate successfully before its pre-model
checks, and a separate review must approve. No force/legacy-peer-deps or auto-merge.
All ordinary source patches retain the350KB budget and all-green baseline gate.

Network acceptance Job swe-network-acceptance-v2 ran with worker labels, non-root
security context and no model/GitHub credentials. DNS/model TCP4000/public GitHub
TCP443 succeeded; private Kubernetes API TCP443 and metadata TCP80 were rejected.
The controller independently reached that same API endpoint, confirming the worker
private-API failure is not simply an absent endpoint. Initial probe incorrectly
expected DROP/timeouts rather than CNI REJECT and was corrected; do not interpret
its failed assertion as permitted private access. No domain-level production block
is claimed. Admission backoff is now300seconds (single active task and5open-PR cap
unchanged), avoiding a30minute idle gap after a fast failed/no-op task.
An open dependency-repair PR blocks duplicate repair tasks against the SAME main
revision (health state waiting_for_dependency_merge). Once main advances or the
PR closes, admission resumes automatically; merge authority remains human-only.

Live Monori task261117190224-efbb4 started automatically after the bootstrap release.
Its real backend baseline passed430tests (243integration tests deselected) in35.61s.
Read-only credential-free ephemeral diagnostics confirmed actual model shell actions
and autonomous error/format recovery, not just a Running Pod. The model reached a
candidate whose npm ci succeeded (815packages); tests/build, exact candidate review
and actual PR publication remain unproven at this checkpoint. Controller Recreate
rollouts preserved this SAME active Job/run through the durable queue; no duplicate
worker was launched. Do not exec a debug process inheriting RESULT_KEY into an
active model container; use an env-empty read-only ephemeral inspector if needed.

### Controller alert incident, 2026-11-18

The initial overnight deployment restarted repeatedly (48observed), with
KubePodNotReady/KubeDeploymentReplicasMismatch. Errors reaching GitHub drove the
same /healthz used by liveness and readiness to503. The idle loop also anonymously
polled main every30seconds, exceeding GitHub's60/hour anonymous budget if sustained.
Old logs did not retain HTTP status codes; not every historical failure is proven
rate limiting. Network ConnectionErrors also occurred.

Fixes1374428d/7c9de534, native releases44275239467/44276749658: GitHub discovery uses
scoped installation auth; idle discovery/retries are bounded to every300seconds.
/livez and /healthz test the queue heartbeat, not external dependency availability;
/dependencies remains503 while a known dependency failure persists, including
through retry backoff. A stale heartbeat still fails liveness. Sanitized errors
now include HTTP status, never response bodies/tokens.31tests include real HTTP
probe semantics, retained errors during backoff and authenticated discovery.

Runtime: replacement controller Ready1/1 with0restarts, Argo Synced/Healthy;
health/livez/dependencies all200 and waiting_for_dependency_merge, PR500 unchanged.
Both native Alertmanager endpoints no longer listed the two reported Pod/Deployment
alerts after recovery. Image delivery temporarily hit TLS/auth failures; exact
manifest and robot access were independently verified and native kubelet retry
succeeded, with no insecure TLS or live image override.

Also correct namespace storage quota headroom from2Gi to4Gi: its existing2Gi PVC
otherwise continuously consumed100% and produced KubeQuotaFullyUsed. This is a
bounded namespace admission limit, NOT a PVC resize, extra allocation or alert mute.
No alerting/routing rules, production Monori data, identities or SSO were changed.
