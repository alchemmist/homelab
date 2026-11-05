# Fleet GitOps retirement (2026-11-05)

Argo CD is the only homelab application GitOps release controller. The obsolete
GitRepo manifests in `deploy/fleet` and the `fleet.yaml` bundle descriptors were
removed. The wiki bootstrap playbook no longer installs/registers a Fleet
repository, discovers a Fleet agent namespace, or creates `wiki-deployer` RBAC.
The unused live `wiki-deployer` Role, RoleBinding and ServiceAccount were removed
after confirming no Pod uses that service account. Wiki data, tokens, Secrets,
PVCs and the existing Argo Applications are preserved.

## Mandatory Rancher dependency: full removal is not yet approved

The running Rancher version is **v2.15.2**. Its initialization forcibly enables
Fleet when `multi-cluster-management` (MCM) is enabled:
https://github.com/rancher/rancher/blob/v2.15.2/pkg/rancher/rancher.go#L225-L229

This was verified live: setting Fleet false and restarting Rancher resulted in
the Fleet Feature becoming true again. `continuous-delivery=false` remains off
and is persisted in `deploy/platform/rancher/values.yaml`. The unsupported
`fleet=false` startup attempt was removed from desired values, avoiding repeated
conflicting startup state. Rancher MCM was NOT disabled.

Full removal of Fleet controllers, its agent and CRDs requires a separate
operator decision to give up/disable Rancher cluster-management functionality.
Do not blindly delete Fleet namespaces/CRDs while Rancher still requires them.
In particular `fleet-local` contains Rancher's local provisioning Cluster; deleting
that namespace can remove Rancher's local-cluster registration/control metadata.

At inventory time there were no Fleet GitRepos. The only remaining Bundle and
BundleDeployment installed the Fleet agent itself. Rancher internal controllers,
budgets and their excluded monitoring descriptions remain until the operator
chooses how to handle Rancher. This is NOT a claim of complete Fleet uninstallation.

Historical migration documents may mention Fleet; they describe retired flows,
not a supported installation path. No application data/PVC or Rancher cluster
registration was deleted during this step.
