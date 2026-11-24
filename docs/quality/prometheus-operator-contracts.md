# Prometheus operator RBAC contracts

`kube-prometheus-stack-operator` (ClusterRoleBinding) must create and manage the
StatefulSet pods for every Prometheus/Alertmanager/Thanos resource it reconciles,
and must read the Secrets referenced by those workloads (object storage, TLS,
bearer credentials). Those are the operator's documented reconciliation
permissions, not an incidental broad grant.

`kube-prometheus-stack-admission` (RoleBinding) is the admission webhook's
secret read: it reads the serving certificate Secret used to secure the
admission webhook endpoint. The create/patch hook Jobs use the same reviewed
contract.

NetworkPolicies added in this pass restrict the operator and admission
create/patch Jobs to API/DNS/public-HTTPS egress, with operator admission and
metrics ingress scoped to kube-system and monitoring.
