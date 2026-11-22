# Preferred-node return on Socrat

Git owner: `deploy/argocd/apps/descheduler.yaml`. Vendored upstream chart 0.36.0
matches Kubernetes 1.36; archive SHA256 `fae31d330236c0dee087241e0861759df16235c1f4d4c5a149d83788997b6b8f`.
Every five minutes, upstream evaluates soft node affinity, not utilization or
previous placement. No affinity means no move. NodeFit, PDB admission, pod age
15m, non-overlap and a one-pod total per run bound disruption. Minimum pod age
is not a recovered-node stability timer. A later pass does not wait on app-level
health of the prior service. A singleton can briefly be unavailable.

Generic profile: ReplicaSet-style pod-template-hash, no node-local storage or
PVC, not CNPG; excludes system/storage/Argo/database namespaces listed in values.
Only the named monitoring Deployments may use the separate NFS profiles; review
PVC and scratch semantics again if their storage changes. Alertmanager is a
StatefulSet and is not in these profiles. No database role changes. To stop future
runs set `descheduler.suspend: true` in Git (cannot undo a completed eviction).
Inspect `kubectl -n kube-system get jobs` and `kubectl logs job/<name>`; use the
`Evicted pod` and `totalEvicted` fields, not `Evicting pod` attempts beyond limit.

## Manifest review decisions (PR #494)

Two manifest findings intentionally remain pending owner decisions; neither is
addressed by weakening the eviction policy or adding a placeholder resource:

- **Readiness:** the chart renders a periodic CronJob, not a continuously serving
  workload. A readiness probe on its short-lived descheduler process would not
  gate CronJob scheduling or tell whether an eviction is safe. The existing
  liveness check only observes the process health endpoint; it is not an
  application-readiness or post-eviction health guarantee. Keep the readiness
  finding open unless an upstream-supported, meaningful readiness contract for
  this Job is identified and tested.
- **Pod isolation:** the Job must reach the Kubernetes API to inspect pods and
  request evictions, and may need DNS to resolve the API endpoint. A default-deny
  policy without the actual API endpoint / CNI path and DNS destinations can
  disable every scheduled run; allowing guessed peers could silently broaden
  access. No NetworkPolicy is added until the cluster's API and DNS network path
  is established offline from authoritative configuration and both required and
  denied traffic are testable. Preserve the current API RBAC and scheduling.

These are the exact residuals for the `no-readiness-probe` and
`non-isolated-pod` findings. Closing either requires the stated evidence/decision,
not a live-cluster experiment as part of this change.
