# Rancher server RBAC: replacement not established

**Decision for PR #494:** leave the Rancher server binding and both blocking
findings in place. The evidence identifies required access, not a complete
smaller role. A green render alone would not establish that Rancher can start,
reconcile native authorization, or recover from drift.

The owner confirmed that Rancher must retain the ability to grant its native Admin
role. Removing that function is not a remediation option. This decision does not
approve an exception or certify the current server binding as least privilege.

## Which identity?

`deploy/argocd/apps/rancher.yaml` installs `charts/rancher` with
`deploy/platform/rancher/values.yaml` into `cattle-system`. The rendered
Deployment uses `system:serviceaccount:cattle-system:rancher`;
ClusterRoleBinding `rancher` binds just this subject to `cluster-admin`.
The release pins Rancher v2.15.2 by image digest. The pre-upgrade and
post-delete Jobs have separate accounts, roles and bindings. So does the
observer-membership CronJob in the Application's public-entry source. Neither
hook cleanup rules nor end-user observer grants describe server permissions.

## Implementation evidence (lower bounds, not a role specification)

Source links below are to the v2.15.2 tag's commit. The actual values set
`continuous-delivery=false`, not `multi-cluster-management=false`.
[The Fleet retirement record](../fleet-retirement.md) explains why Fleet and
the local provisioning Cluster are still required. The public-entry chart
enables `observerAccess` and declares a GlobalRole, RoleTemplate and local
ClusterRoleTemplateBinding. The [management handoff](../vm105-management-20261116.md)
records retained native users, roles, bindings, clusters, projects and OIDC
configuration; these aren't a static set of Helm-generated rules.

| Server path | API access evidenced on the management cluster |
| --- | --- |
| [Initialization](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f0f9ae9d6d356e3b8/pkg/rancher/rancher.go#L193-L229) and [CRD installation](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f9ae9d6d356e3b8/pkg/crds/crds.go#L39-L64) | Installs/ensures cluster-scoped `customresourcedefinitions.apiextensions.k8s.io` for enabled features; not a namespace-only or steady-state read operation. With MCM on and Fleet off, [SetFeature](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f9ae9d6d356e3b8/pkg/features/feature.go#L370-L385) does `get`, `update` on cluster-scoped `features.management.cattle.io` named `fleet`. |
| [GlobalRole reconciliation](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f9ae9d6d356e3b8/pkg/controllers/management/auth/globalroles/globalrole_handler.go#L138-L199) and [client helper](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f9ae9d6d356e3b8/pkg/rbac/common.go#L393-L423) | `list`, `get`, `create`, `update`, `delete` on cluster-scoped `clusterroles.rbac.authorization.k8s.io` across create, drift and stale-role cleanup. The desired rules come from the native role. The namespaced counterpart reconciles `roles` in the namespaces keyed by `NamespacedRules`, not just `cattle-system`. |
| [GlobalRoleBinding reconciliation](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f0f9ae9d6d356e3b8/pkg/controllers/management/auth/globalroles/globalrolebinding_handler.go#L382-L610) | `create`, `update`, `delete` on cluster-scoped `clusterrolebindings.rbac.authorization.k8s.io`; `create`, `delete` on namespaced `rolebindings` for native grants. Replacing a binding whose roleRef changed is not an update. |

In particular, upstream [seeds the Admin GlobalRole](https://github.com/rancher/rancher/blob/272e65580ca92b9dc51e0f0f9ae9d6d356e3b8/pkg/data/management/role_data.go#L83-L91) with wildcard resource **and non-resource** permissions.
The GlobalRole reconciler copies rules into Kubernetes RBAC. Kubernetes checks
whether the caller may grant those permissions, not just whether it can write
a ClusterRole or binding. Copying wildcard rules into a differently named
ClusterRole or granting broad `escalate`/`bind` is not an evidenced reduction.
Conversely, copying only the observed reads would omit writes on cold start or
drift. This does not prove that every operation allowed by `cluster-admin` is
necessary.

## What would unblock a change?

A version-matched, supported restricted server role or a reviewed per-controller
permission inventory covering bootstrap/upgrade, local MCM/Fleet, informer
reads, delegated/native grants and recovery. Separate the server's identity
from downstream agents, hooks and user requests; include names/subresources,
namespace boundaries and the authority to grant native roles. Then test the
candidate's effective allow/deny matrix offline, including unrelated resources,
subjects and namespaces. Reducing Rancher functionality to fit a smaller role
would be a separate owner decision. A future delivery plan also needs to handle
immutable binding `roleRef` and this Application's `prune: false` without
leaving the old grant behind.

`tests/test_quality_system.py` renders the two Rancher sources to check the
server/hook account and role wiring, pre-upgrade read scope, and that no other
subject or binding receives the built-in admin grant. These are manifest
regressions, not an API-server authorization simulation. They do not require
that the grant remain or exempt it from the blocking gate.
