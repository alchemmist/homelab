# SWE Mini: Monori autonomous maintenance

## Desired architecture (acceptance pending)

Owning Application: `deploy/argocd/apps/swe-mini.yaml`; local chart `charts/swe-mini`,
values `deploy/swe-mini/values.yaml`. Implementation and hash-locked dependencies:
`services/swe-mini`. First release is deliberately disabled until its immutable
image and private prerequisites exist. This document is not evidence of rollout.

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
A separate fresh-container mini invocation reproduces/reviews the exact candidate;
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
CI never calls Argo sync. Prerequisites are Secrets outside Git. First activate
`enabled:true` in both values ONLY after native release records digest, secrets
exist, and offline/server dry-run passes. No live image override.

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
