# Prometheus Operator manifest findings: approval required

Scope: the `prometheus-operator` target in PR #494, rendered from
`charts/prometheus-operator` (kube-prometheus-stack 92.10.0) into
`cattle-monitoring-system`. This records a blocker, not an exception or finding
suppression. No chart setting has been changed to hide these results.

## Current rendered behavior

The chart renders one `kube-prometheus-stack-operator` Deployment and two
admission-certificate hook Jobs (`kube-prometheus-stack-admission-create` and
`kube-prometheus-stack-admission-patch`). The operator Deployment has chart-
provided liveness and readiness probes. The one-shot hook Jobs have neither;
adding health probes to a completed Job would not establish a useful health
contract. Both hook Jobs run as `kube-prometheus-stack-admission` and need their
own admission Secret permissions.

The operator ClusterRole currently grants Secret `get`, `list`, `watch`,
`create`, `update`, and `delete`, and Pod `list` and `delete`. The separate
admission ClusterRole and namespaced Role grant Secret `get`/`create` for the
certificate Jobs. These are distinct identities and functions; narrowing one
must not silently break the other. The three rendered workloads (operator and
two hook Jobs) also have no workload-specific NetworkPolicies in this chart.

PR #494 associates these ten blocking findings with this target: operator
`access-to-create-pods`; operator `access-to-secrets` (two findings); missing
liveness and readiness probes on each of the two certificate Jobs; and
`non-isolated-pod` on the operator and each certificate Job.

## Decision required before a behavior change

Do not remove the operator's Pod/Secret authority or add guessed NetworkPolicies
until the owner approves a version-matched namespace/resource watch and traffic
contract. Required input is:

1. An upstream-supported watch scope for kube-prometheus-stack 92.10.0 covering
   bootstrap, steady-state reconciliation, upgrades and drift recovery, with
   resource names/namespaces and required verbs. In particular, specify how
   certificate/admission reconciliation and operator-created resources continue
   to work. The current broad ClusterRole is not proof every permission is
   necessary, but the rendered chart alone does not establish a safe smaller
   role.
2. Explicit allowed ingress/egress peers and ports for the operator and both
   Jobs, including API-server admission/certificate activity, DNS and required
   control-plane access. Tests must demonstrate both required flows and denial
   of unrelated peers; do not use an empty/default-deny policy as a substitute
   for the peer inventory.
3. A supported health contract for each Job if probes are proposed. A Job's
   completion/success condition is not a long-running-process liveness signal.

After that decision, implement the narrowest supported changes and test the
rendered RBAC and network allow/deny matrix, including the admission Jobs and
operator reconciliation paths. If upstream does not support a safe smaller
scope or the required flows cannot be established, retain the current behavior
and record the remaining findings for a separate owner decision. No production
reconciliation or live-cluster test is authorized by this document.
