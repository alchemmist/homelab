# Inventory-driven NetBird node onboarding

2026-11-03. Current four-node installation has been bound to the new controller
without changing existing peers, addresses, policies, network or group membership.
A real fifth node has **not** been provisioned for this acceptance.

## Normal operator workflow

Prerequisites: the existing NetBird control plane and genuine Authentik JWT admin
policy are operational. A new machine still needs trusted initial SSH access,
a unique inventory WG address, a working inter-node WG mesh and Kubernetes
membership. This feature does not allocate addresses, replace inter-node WG,
accept unverified SSH host keys, grant Linux sudo, or configure a bare machine's
network/OS by itself.

1. Add `socrat-N` to `ansible/inventory/hosts.yml` under `Socrat`, with its trusted
   SSH connection information. Add its unique server address/public key to
   `wg_socrat_nodes` using the existing WG provisioning procedure. Human/device
   addresses in `wg_socrat_admin_clients` are reserved and cannot be reused.
2. Apply the baseline, then provision/join the node to Kubernetes. `base.yml` and
   `site.yml` run NetBird onboarding automatically. If the node is not yet in
   Kubernetes or is not Ready, it reports **deferred**, not successful enrollment.
3. `k3s-worker.yml` and `k3s-ha.yml` invoke onboarding after membership is ready.
   Worker host/name/IP are inventory-driven rather than fixed to socrat-3:

   ```sh
   cd ansible
   ansible-playbook playbooks/site.yml --limit socrat-4 --ask-become-pass
   # After WG provisioning; a Debian x86_64 worker, not another etcd voter:
   ansible-playbook playbooks/k3s-worker.yml --limit socrat-4 \
     -e k3s_worker_hosts=socrat-4 --ask-become-pass
   ```

   Both commands use normal Linux sudo authorization. Existing worker OS/version,
   primary datastore and management-interface checks remain. Control-plane nodes
   cannot be converted into workers by changing the name variable.
4. No additional NetBird command is normally needed. If a node joined Kubernetes
   through a different workflow, run the dedicated reconciliation play:

   ```sh
   ansible-playbook playbooks/netbird-nodes.yml --limit socrat-4 --ask-become-pass
   ```

Your already authorized Mac receives the new peer and WG /32 resource through
management sync. No human WireGuard profile or Mac VPN reconfiguration is needed.
SSH still uses the node's normal authorized keys/host-key verification; a local
short alias needs its usual SSH-client provisioning, not a NetBird setting.
Successful API reconciliation is not proof of an actual Mac SSH session to a
future node, and sync/route convergence is not guaranteed instantaneous.

## Admission sequence

- Complete inventory scope is rendered even under `--limit`; no implicit deletion
  of omitted/unreachable nodes or All-device grants.
- Existing API router, network, native admin INPUT policy and **genuine JWT**
  `netbird-internal-admins` must already exist. The controller never creates JWT
  source groups, changes human membership, impersonates a user or repairs roles.
- New Ready nodes get a hostNetwork Deployment and persistent 64Mi identity PVC,
  pinned client 0.82.0, 96Mi cap, client routes/DNS/NetBird SSH disabled. Only the
  reviewed bootstrap NoSchedule taint is tolerated, preserving workload admission.
- One-use key, 600 seconds, empty auto-groups; start the agent without grants.
- Match the actual official client's status/IP/public key with the API peer and
  Kubernetes placement. Restart without the setup-key env and verify the same
  identity. Known keys are revoked and temporary Secrets deleted even on failure.
- Verify the actual WG address and reachability of Ready inventory WG targets
  before admitting a new routing peer.
- Add only that exact peer to `netbird-node-agents`; existing admin INPUT policy
  covers its own address. The existing native group router automatically expands.
- Create one exact new host `/32` resource and directed admin FORWARD policy.
  No broader prefix, client config, machine SSH privilege or unrelated app grant.

Existing nodes are never rolled out just to re-render a manifest. Unknown image,
security/env, address, node UID, PVC UID, Deployment UID, public key, peer ID,
network or policy drift blocks instead of replacing a working identity.

## Durable state and credentials

Controller state: `/var/lib/homelab-netbird-nodes/`, root-owned 0700. Credential,
bindings and journals are 0600; scripts are owner-only. Cluster/namespace UID,
network/router/source/destination IDs, immutable node/storage/workload/peer
bindings and admitted resource/policy IDs are retained. Back up this directory
**encrypted**, not as a public Git artifact. This is not full DR acceptance.

A dedicated NetBird **service user**, `homelab-netbird-node-automation`, has admin
API capability and no human password/MFA flow. Community API capability here is
broad; this is **not least privilege**. No token value is stored in inventory,
Ansible argv/output, source, ConfigMap or logs. Initial adoption used the trusted
old private stage to pin exact IDs, never friendly-name-only adoption.

`homelab-netbird-credential.timer` checks daily. A 365-day machine PAT is replaced
within 30 days of expiry: issue, verify, atomically store new token, then revoke
old. The timer only maintains credentials; it does not periodically restore
permissions or enroll undiscovered nodes. Human five-minute bearer and MFA/session
settings are unchanged. Failure/ambiguous issuance retains a private intent marker
and requires inspection, not repeated uncontrolled token issuance.

The connection-only `netbird-controller` inventory alias is outside `Socrat`.
It pins the home public IP and canonical known-host alias with strict checking;
the shared public DNS name must not randomly select the VPS SSH server. Defaults
load main inventory, the existing socrat-3 overlay and this controller alias.
Explicit `-i` options override defaults: include required overlays when using them.

## Safety, removal and recovery

- `--check` makes no live API mutation. `-e netbird_node_apply=false` runs the
  installed controller's read-only API validation; on a new controller it cannot
  work before credentials exist. A plain script invocation plans by default.
- `netbird_node_enabled: false` opts a host out of management. It is **not** a
  revocation/decommission command and does not delete working peers or resources.
- Bound peers, group admission, resources or policies intentionally removed or
  disabled are not silently recreated. Retire identity and its grants explicitly
  before reinstalling/replacing a machine, changing its IP or reusing its name.
- Interrupted enrollments, uncertain POST/PUT outcomes, partial PVC/Deployment
  state and orphan peers fail closed. Inspect private `bindings.json`, its pending
  operation/cleanup marker and native API before remediation. No automatic setup
  key reissue or whole-state rollback.
- The exclusive controller lock serializes onboarding and token maintenance.
  Group membership is reread before updates; API has no general compare-and-swap,
  so do not run external admin edits of that same group concurrently.
- Controller/management remains on socrat-0. Management and Authentik HA, outage
  cold-start behavior and disaster recovery are **not solved** by this feature.
  The earlier management-less cold-client test still failed; legacy recovery
  access must not be retired based on this automation.

For a genuinely fresh cluster, establish the identity/control-plane foundation
first, or explicitly disable this role while applying only the host baseline.
Do not supply an arbitrary bootstrap token to an unknown control-plane instance.
One-time initialization parameters are `netbird_node_bootstrap_token_file` and
`netbird_node_adopt_state` (private file paths, never token values). They are empty
by default; the current installation already has credentials/bindings and needs
neither flag. Same-name service accounts are not automatically adopted.

## Verification performed

- Mocked new-node lifecycle: one-use enrollment, key-free restart, key retirement,
  resource/policy/group admission, and second-run no-op. Negative tests cover
  identity/storage/image/address drift, reserved IP collision, fake JWT groups,
  broadened/revoked grants and uncertain writes.
- Mocked credential renewal order, no-op when not due, account-role changes,
  uncertain issuance and explicit bootstrap requirement.
- Ansible syntax checks plus local read-only check-mode rendering, including
  delegated alias and complete inventory under `--limit`.
- Live trusted controller alias SSH reached socrat-0. Linux passwordless sudo was
  not available, so initial root installation used bounded, UID/host-guarded
  Kubernetes maintenance jobs; host systemd activation required host namespaces.
  Temporary payloads/jobs were removed; root-only state/credential remains.
- Live existing-node adoption and second run: all four returned no-op on replay;
  final root-installed controller also returned no-op for all four. Native graph
  compared unchanged after canonicalizing unordered API arrays. The initial raw
  array-order comparison assertion failed and was not treated as a graph change.
- Daily credential timer enabled and active; its service ran successfully without
  rotation being due. Real expiry-boundary rotation and real new physical-node
  onboarding remain separate acceptance, not claimed from mocks.

Current topology and earlier outage results: [independent access](netbird-independent-access.md).
