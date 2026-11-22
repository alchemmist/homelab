# cert-manager manifest findings: residual decisions

PR #494 reports 18 findings for the cert-manager owner: `access-to-create-pods`
(1), `access-to-secrets` (7), `job-ttl-seconds-after-finished` (1),
`no-liveness-probe` (2), `no-readiness-probe` (3), and `non-isolated-pod` (4).
These were reviewed against the vendored cert-manager v1.16.2 chart and the
Argo-rendered values at `deploy/platform/cert-manager/values.yaml`.

No policy, RBAC, or retention changes are made here. Each would need a specific
owner decision/evidence to avoid impairing certificate issuance, renewal, or
admission:

* **Pod creation and Secret access:** cert-manager creates HTTP-01 solver Pods
  and consumes solver/ACME credentials and writes issued certificate Secrets.
  ClusterIssuers and certificates can be used outside the cert-manager
  namespace. Before narrowing the chart's controller ClusterRoles, approve the
  supported Secret namespaces/resource scope and a test matrix covering both
  namespaced Issuers and ClusterIssuers, HTTP-01 solver creation/cleanup, and
  certificate create/renewal. The chart's current upstream grants cannot be
  safely reduced based only on these lint findings.
* **Network isolation:** the chart's HTTP-01 solver must receive challenge
  traffic from the ingress path and reach DNS/ACME services; the webhook must
  receive API-server admission calls; controller and cainjector need their
  Kubernetes API access. Approve the actual source identities, ports, and
  required egress (including resolver/ACME destinations) before enabling
  default-deny policies. No peers or egress destinations are guessed here.
* **Probe findings:** the render confirms controller liveness at `/livez` and
  webhook liveness/readiness at `/livez` and `/healthz`. The cainjector template
  does not declare a health endpoint/probe (its optional metrics listener is
  not, by itself, evidence of readiness), and the one-shot startup API check is
  a Job, not a long-running service. Do not substitute a metrics TCP check or
  duplicate liveness as readiness. A fix requires upstream-supported cainjector
  health/readiness semantics and the precise finding-to-container mapping.
* **Startup API-check Job TTL:** the hook already deletes successful Jobs and
  retains failed Jobs for diagnosis (`hook-delete-policy:
  before-hook-creation,hook-succeeded`). Choose whether failed startup checks
  should be retained for debugging or automatically expired, and the desired
  retention interval, before adding `ttlSecondsAfterFinished`.

## Offline render evidence

Rendered with Helm using the real Application values:

```sh
helm template cert-manager charts/cert-manager \
  -f deploy/platform/cert-manager/values.yaml --namespace cert-manager
```

The render contains the controller, cainjector, webhook and startup API-check
Job, the chart's issuer/certificate/solver RBAC, and no enabled NetworkPolicy
under these values. Inspecting rendered container probes confirms the paths
above. The Job's hook deletion policy is preserved. These checks establish the
current behavior and the missing approval inputs; they do not certify a live
cluster, prove successful issuance, or claim the lint findings have been
resolved. No live cluster or deployment operation was performed.
