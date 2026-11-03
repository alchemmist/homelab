# NetBird: root-managed Argo CD ownership

2026-11-03. Follow [cluster deployment contract](../llm-wiki/cluster-deploy.md).
The historical direct `kubectl` pilot is not an allowed deployment path.

## Source of truth

- Existing `root` watches `deploy/argocd/apps` recursively.
- `deploy/argocd/apps/netbird.yaml` declares the child Application. No manual
  Application creation, root patch, new AppProject or ApplicationSet.
- Project `default`, revision `main`, chart `charts/netbird`, release `netbird`,
  value file `deploy/netbird/values.yaml`, explicit empty Helm parameters.
- Automated sync: `prune: false`, `selfHeal: true`. Git changes are published to
  main; Argo CD performs the Kubernetes deployment, not CI, Ansible or a manual Sync.
- Scope includes management, dashboard, edge forwarder/public entry, both relays,
  STUN, all declared node agents, Services, NetworkPolicies, Certificates,
  dedicated namespaces and identity PVCs. Initial adoption: 33 objects / 10
  Deployments across `netbird-pilot`, `netbird-host-peers`, and shared `identity`.
  Shared namespace `identity` is not claimed by NetBird.

The chart intentionally retains existing object names, placements, security,
resource caps, public paths, exact `/api/users/invites` GET exception, source-
preserving STUN, h2c Service and relay `publishNotReadyAddresses` + native-LB
readiness-cycle correction. It does not recreate users, peers, policy objects,
PVC data, OIDC connectors or setup keys. Native NetBird API objects live in its
persistent database, not a second Kubernetes configuration reconciler.

## Images, first render and storage

No version upgrade or registry migration is mixed into adoption. Existing vendor
images remain digest-pinned. Dashboard has root `image.repository/tag/digest` keys;
Helm renders `repository@digest`, falling back to `repository:tag` only when the
digest is empty. Other upstream component references retain their existing pins.
Changing the dashboard reference from `repository:tag@digest` to canonical
`repository@digest` is the only intended initial PodTemplate change: the artifact
is identical, but Kubernetes can recycle the UI pod. Management, routing agents,
relays and STUN must not restart merely for adoption.

PVCs and NetBird-owned namespaces have
`argocd.argoproj.io/sync-options: Prune=false,Delete=false`. Existing claim names
are adopted; no volume data or private keys are exported. Runtime-assigned PVC
volume IDs and Service cluster IPs are not forced as portable desired state.
No application-wide ignoreDifferences or ignored Deployment specs conceal drift.

The Application has the normal resource finalizer. Removing it from Git stops
managed workloads, even though PVC/namespaces are protected. This is a deliberate
operator decommissioning operation, not a safe way to troubleshoot access.
Keep the independently tested legacy recovery path.

## Secrets are dependencies, not Git contents

The chart contains Secret **references**, never runtime Secret values. Existing
private NetBird runtime configuration, relay HMAC credentials and TLS keys stay
in their current Secrets; cert-manager owns certificate issuance. This migration
neither copies credentials into values nor rotates signing/private keys. Secure
secret bootstrap/rotation is separate from deployment and cannot be reconstructed
from public Git alone. Encrypted secret/storage backup and tested restoration
remain necessary; this is not a full DR or control-plane HA claim.

## Inventory-driven node onboarding without shadow deployment

1. Add the trusted host/WG address using the normal inventory procedure.
2. Run `python3 scripts/netbird-gitops-nodes.py` locally. It uses the complete
   Ansible inventory and generates **only secret-free Git values**, never cluster
   objects or API grants. Commit inventory and values together; publish to main.
   `--check` verifies the generated state without writing files. Existing omitted
   nodes are retained; address replacement/partial resources fail closed.
3. Root/Argo CD creates the declared Deployment/PVC. An absent node leaves the pod
   Pending; that is not identity enrollment or successful access acceptance.
4. Normal baseline/worker/node Ansible plays install the host-side controller and
   reconcile the Ready node. They assert Git admission first. The controller
   requires Argo-owned workload/storage and never creates, applies, patches,
   scales or replaces Kubernetes workloads. Missing resources are deferred as
   `awaiting-argocd-workloads`.
5. A fresh `NeedsLogin` agent receives a 600-second, one-use, empty-group key over
   authenticated exec stdin using native `--setup-key-file /dev/stdin`. No key in
   argv, env, Git or Kubernetes Secret. Known keys are revoked even on failure.
6. A guarded operational pod restart checks persisted identity after key
   retirement; the existing Argo-declared ReplicaSet recreates the pod. No
   Deployment/PVC spec is mutated. Exact peer/key/UID and WG reachability checks
   precede API group admission and the exact admin `/32` resource/policy.

The host credential renewal timer is not a Kubernetes deployment reconciler and
cannot resurrect grants. Existing immutable controller bindings remain valid;
future normal Ansible runs install the updated controller before reconciliation.
A physical fifth node and real credential expiry-boundary renewal remain separate
acceptance tasks, not proven by this migration or mocked tests.

## Adoption verification and recovery

Compare the rendered objects with a private pre-migration readback before publish.
Expected changes are Argo ownership/protection metadata and the canonical UI image
reference only. Check `root -> netbird` tracking, Synced/Healthy, all object/PVC
UIDs, unchanged non-dashboard pod UIDs, existing peer/access graph, both public
trusted-TLS entrances and native Signal streams, and owner SSH to all four nodes.
Do not equate an Application manifest or a successful Git push with deployment.

Rollback is a new Git commit restoring a reviewed configuration, not a direct
`kubectl apply` of old pilot output. Do not automatically delete/recreate claims
or reissue enrollment keys on an ambiguous failure. Argo CD availability does not
fix the confirmed NetBird/Authentik singleton and cold-client startup limitations.

## Completed live adoption acceptance

Implementation commit `b613b1a`, published together with the preserved concurrent
main history as `d1874f0`. Root discovered/created the child automatically; no
manual Application creation, root patch or manual Sync was used. Actual child
status: **Synced / Healthy**, automatic operation **Succeeded**, 33 tracked
resources. Root tracks it as `root:argoproj.io/Application:argocd/netbird`.

Private before/after readbacks confirmed:

- All pre-existing Kubernetes object/PVC and dedicated namespace UIDs unchanged.
- All non-dashboard pod UIDs unchanged; only the canonical same-digest UI image
  reference required a new dashboard pod. All ten Deployments are available.
- Five connected peers, identical native identities, human roles, group membership,
  networks, routers, four exact resources and seven policies before/after.
- Five referenced runtime/relay/TLS Secrets have identical UID/resourceVersion;
  no Secret values were exported or changed.
- Both public trusted-TLS entries: dashboard 200, authenticated invite list 200,
  anonymous invite list 401. Native Signal stream headers passed both entrances.
- Existing Mac remains connected to all four agents. Strict SSH passed to all
  four WG aliases and all four explicit NetBird IP addresses.
- Helm lint, exact rendered/live desired-field comparison, inventory-generation
  check and Ansible syntax check passed; Python: 121 passed, 1 skipped, 122 subtests.

Fresh anonymous browser automation was unavailable in the validation environment;
no personal browser session was copied or impersonated. Physical fifth-node and
real PAT expiry-boundary acceptance remain pending as described above.

Root's aggregate status can still show unrelated drift for `rancher` / `remark42`;
NetBird's own child/resource entry is Synced. Those other applications were not
modified to make this migration appear globally clean.
