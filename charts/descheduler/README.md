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
