# NetBird private network access

- **Connect a person:** follow [administrator onboarding](clients/netbird-administrator-onboarding.md). On a Mac using the corporate VPN, check [Tunnelblick coexistence](clients/netbird-tunnelblick-coexistence.md).
- **Understand the topology:** see [four routing peers and two relays](infrastructure/netbird-independent-access.md). A working route does not grant SSH, application or Kubernetes permissions.
- **Manage infrastructure:** use [node onboarding](infrastructure/netbird-node-onboarding.md), [Kubernetes machine peers and STUN](infrastructure/netbird-kubernetes-machine-peers.md), or [Argo CD ownership](infrastructure/netbird-argocd.md).

Updated: **November 7, 2026**. Overall network summary and boundaries: [network-access.md](../README.md). This is the current scheme, not the original pilot.
The old “NetBird postponed / do not deploy” notes describe an already completed stage.

## What it does and does not do

NetBird is the managed network entry for people: personal Authentik/MFA and
address-based access policies. The mandatory user/device approval requirement is
currently off; device ownership is still verified by the operator. Panel:
https://netbird.socrat.alchemmist.xyz/.
It replaces the manual distribution of **human VPN profiles**, but not the
inter-node `wg-socrat`, Linux SSH authentication, sudo, Kubernetes RBAC or
application roles. Network access to a node does not mean the right to log in
on it or become root.

**Standalone WireGuard is kept only as an independent recovery path, not the
human default:** a cold client start without management really did fail.
Successful tests of the existing connection do not mean full HA or permission
to remove the independent recovery path.

## How to add a new administrator

This is several independent permissions, not one all-powerful group.

1. **Identity.** Create a personal active person in Authentik, set up MFA and
   the agreed application/group bindings. Preserve the immutable UUID; do not
   clone the owner, do not use a service account and do not reuse someone
   else's account. **A created account without a password cannot start an
   ordinary login.** First choose the standard password setup; do not promise
   an automatic invitation or a first self-set screen. The current
   `antropophag` still has no password/MFA.
   [First login and status](../../auth/authentik/operations/identity-current-state.md),
   [creating a person](../../auth/authentik/operations/identity-operations.md).
2. **Device.** The person installs NetBird and logs in with their Authentik/MFA
   into our management system. The administrator verifies device ownership and
   the agreed identity/device policies; manual approval is not currently a
   mandatory step. We do not use setup keys for registering people.
3. **Network rights.** After separate agreement, add the person to the real
   Authentik/JWT source of the `netbird-internal-admins` group. It is currently
   **owner-only**; Tim does not become an admin automatically. In NetBird this
   must remain a genuine `issued: jwt` group, not a hand-made API analog with
   the same name. To refresh the OIDC session/groups use
   `netbird login --extend`, not the nonexistent `netbird up --force-reauth`.
   Verify the sync result, membership and the real policies; a group name alone
   proves nothing.
4. **Linux/SSH.** Pass the Linux name and the public `.pub` to the
   [manual Ansible playbook](../../auth/host-access/ssh-user.md). It creates an ordinary user **without
   sudo**, checks every selected node, and adds the missing key while
   preserving the others. No Authentik attributes or n8n workflow are needed
   for this.
5. **Kubernetes and applications.** Separately assign the needed
   Rancher/Kubernetes/app roles. Do not hand out the shared owner kubeconfig,
   private SSH key or root password. A Kubernetes administrative role does not
   require the Linux user's membership in sudo. A NetBird account admin/owner is
   also a separate right to manage the panel itself; it is not required merely
   for permitted network access.
6. **Acceptance by the person.** From their device verify MFA,
   identity/device policies, the connection, access only to the agreed
   addresses, SSH under their Linux name and the needed app/Kubernetes
   operations. Separately verify denied destinations and the absence of sudo.
   Success from the owner's Mac is not acceptance of another person or device.

## Current topology

At the last performed check: **five connected peers** — the owner's Mac and
four persistent machine agents on the existing nodes. This is an acceptance
snapshot, not a promise of their continuous availability.

| Node | Inter-node WG / administrative resource | NetBird agent IP |
| --- | --- | --- |
| socrat-0 | 10.250.0.1/32 | 100.100.155.241 |
| socrat-1 | 10.250.0.3/32 | 100.100.160.32 |
| socrat-2 | 10.250.0.2/32 | 100.100.166.186 |
| socrat-3 | 10.250.0.5/32 | 100.100.7.160 |

- Management/Signal: `netbird-pilot/server` on socrat-0, version 0.82.0.
- Four agents: `netbird-host-peers/machine-socrat-N`, persistent PVC, no setup
  key in the permanent environment. Client routes/DNS/NetBird SSH are disabled;
  the server's ordinary SSH and host key verification remain.
- Network `wireguard-internal`, a single native `peer_groups` router to the
  exact API group `netbird-node-agents`, metric 80, masquerade. Four separate
  WG `/32`s, no shared prefix and no overlapping duplicate routes.
- Seven policies: four admin resource FORWARD, admin own-node INPUT and two
  limited pilot SSH policies. INPUT is needed for the routing peer itself,
  FORWARD — for an address behind another peer. No all-device grants or fake
  JWT groups.
- Two separate authenticated relays: home on socrat-0 and the VPS on socrat-2;
  STUN-only coturn on socrat-2 UDP3478. TURN is not enabled; no new VMs were
  purchased.
- Dashboard 2.96.0; management/client/relay and the remaining images are
  digest-pinned. Authentik and management/Signal remain singleton dependencies.

## Deployment: Argo CD only

**`root → netbird`**, built-in project `default`, branch `main`:

- Application: `deploy/argocd/apps/netbird.yaml`;
- chart: `charts/netbird`, values: `deploy/netbird/values.yaml`;
- auto-sync, `selfHeal: true`, `prune: false`, Helm `parameters: []`;
- 33 resources at migration, including 10 Deployments: management/dashboard,
  edge, relay, STUN and machine agents. PVCs and their own namespaces have
  `Prune=false,Delete=false`; the shared `identity` namespace is not captured;
- Secret values, private keys and PVC contents are **not in Git**. The existing
  runtime/relay Secrets remain private bootstrap dependencies; TLS is issued by
  cert-manager.

Root created the Application from the apps catalog itself. Verified
**Synced/Healthy** and tracking of all resources. The objects'/PVCs'/namespaces'
UIDs, secrets and the access graph were preserved; due to reference
normalization only the UI pod pointing at the same digest was recreated, not
management/agents/relays. The historical direct-apply scripts are not the
deployment path. Do not create the Application by hand and do not heal drift
with a manual Helm. Details: [contract](../../platform/delivery/cluster-deploy.md),
[adoption](infrastructure/netbird-argocd.md).

## How a new node is added

1. Explicitly add the trusted host and a unique server WG address to the
   inventory. Do not take a human device's address; the existing WG mesh is
   separate.
2. In the repo root run `python3 ansible/scripts/netbird-gitops-nodes.py` and
   commit/publish the inventory together with the updated
   `deploy/netbird/values.yaml`. The generator only prepares Git; it does not
   deploy into the cluster. Check mode: `--check`.
3. Root/Argo CD creates the Deployment/PVC. Join the node to Kubernetes with
   the ordinary baseline/worker/HA playbook. A non-Ready node is deferred, not
   considered enrolled.
4. Ordinary Ansible onboarding installs the host-side controller and works
   with the NetBird API: a fresh Argo-owned agent receives a one-time 600s key
   without groups via exec stdin, the key is revoked, and preserving the peer
   identity is verified after a key-free operational restart. The
   Deployment/PVC is created **only by Argo CD**.
5. After WG/UID/key/peer verification, the exact machine peer, the `/32`
   resource and the admin policy are added. The already permitted Mac needs no
   new VPN profile.

Missing workloads: `awaiting-argocd-workloads`; missing/non-Ready node:
`deferred-node-not-ready`. Do not bypass a refusal by re-issuing peer/PVC. The
controller does not restore deliberately removed grants. Root-only state is in
`/var/lib/homelab-netbird-nodes/`; a machine PAT is served by a separate daily
timer. This API account has **broad admin rights, not least privilege**. A real
fifth node and PAT expiry-boundary rotation have not yet been physically
verified. Full order: [node onboarding](infrastructure/netbird-node-onboarding.md).

## Fixed problems that must not come back

- Native Signal requires h2c and a separate Service
  `netbird-edge-forwarder-grpc`; an HTTP/1 fallback does not fit. Real bidi
  stream headers were verified through both public entrances, not just an
  ordinary HTTP health check.
- In 0.82, external relay addresses disable the combined relay. The top-level
  `relay:` is ignored; the two standalone relays are the real current
  deployment.
- Relay health checks the public TLS endpoint. For the dedicated Service,
  **both** `publishNotReadyAddresses` and Traefik `service.nativelb: 'true'`
  are needed, otherwise a readiness loop occurs. TLS/HMAC/health were not
  disabled.
- An SSH host-key mismatch must not be “fixed” by deleting the correct
  known_hosts. Public DNS points at different servers: use a verified SSH alias
  and the exact endpoint/HostKeyAlias; the connection-only
  `netbird-controller` is pinned to the trusted home IP and is not part of the
  `Socrat` node group.
- **The historical Mac resolver exceptions were removed November 6**, including
  the restorer lifecycle. Ordinary public DNS is used now; NetBird DNS is off.
  Do not run the old `netbird-macos-bootstrap-dns.py` for normal onboarding;
  the guarded retirement script is `scripts/macos-public-dns-cleanup.py`.
- The 403 on the Users page was caused by a shared edge-deny of
  `/api/users/invites`. Only the **exact GET read** is allowed, with native
  auth/role checks; local invite creation/acceptance, setup and local
  login/signup remain closed. Verified admin 200 / anonymous 401 through both
  entrances.
  [Diagnostics](../../records/incidents/netbird-users-invites-403.md).

## What was really tested and where the boundaries are

| NetBird service failure | Result |
| --- | --- |
| socrat-0 agent + management/Signal stopped | New SSH to 1/2/3 succeeded; another routing peer was selected |
| Only the socrat-2 agent left, management stopped | New SSH to the VPS succeeded from the existing authorized Mac |
| Agent/VPS relay/STUN on socrat-2 stopped, Mac down/up | Home relay available; SSH failed at first, recovered by the third round. Immediate availability **not proven**, no numeric RTO |
| Management/Signal stopped, then Mac down/up | **Failure:** timeout, LoginFailed, SSH does not work; after management was restored, access returned |

All stopped services were restored. SSH over WG and NetBird addresses of the
four nodes, both relays and Signal were verified. These are **bounded
service-outage tests**, not a physical node/site/power/WAN outage. The cached
Signal-connected flag alone does not prove server availability. Full
evidence/timings: [independent access](infrastructure/netbird-independent-access.md).

Not covered: physical/site outage, full DR, a separate nonadmin/Tim-device
test, session/device revocation timeframes, management/Authentik HA and
cold-start resilience. The verified encrypted backups are not equal to a
successful full restore. The earlier exposed legacy WG private key is
compromised; do not reuse it. Before rotation, confirm the owner of the `.7`
profile (inventory: Tim's phone, owner Mac `.4`); no automatic revocation was
done; we do not remove the independent recovery path.

## Access revocation — a separate operation

Revoke the agreed IdP/JWT groups and app/Kubernetes roles, delete/block the
needed NetBird devices/accesses and separately revoke SSH keys on all needed
nodes. Disabling an Authentik user does not erase `authorized_keys`, and the
adding `ssh-user.yml` revokes nothing. Follow the reviewed
exact-key/disabled path of the [host access](../../auth/host-access/identity-host-access.md#4-ssh-revocation);
already-open SSH sessions and forwards need a separate decision. Until a
separate acceptance exists, do not promise instant revocation from a single
group change or the expiry of a five-minute bearer.

## Operational summary, November 6

- NetBird is the Mac's primary transport; the recovery WG was verified via the
  new VPS `109.120.141.97` and left off. Tunnelblick was not disabled/
  reconfigured. All ordinary SSH goes over internal `/32`/2222, pinned host
  keys, with no public fallback.
- Mac: `disableDns=true`, `disableClientRoutes=false`,
  `disableServerRoutes=true`, only the four `wg-socrat-*` routes selected.
  The built-in All does not hand out DNS to future peers. No exit/LAN/pod/
  service/corporate route capture.
- `ansible/scripts/netbird-access.py` / `ansible/playbooks/netbird-access.yml`:
  audit-first scoped grant/revoke/offboard, owner/service protections, private
  snapshots and a fresh exact hash. The temporary lifecycle was verified; the
  bootstrap admin is limited; fixtures removed. Membership does not
  automatically grant app/Linux/Kubernetes/admin roles and does not revoke all
  old sessions.
- Approval mode is off, but genuine JWT group admission and personal MFA are
  preserved. The first real new person/device remains a separate acceptance.
- The inter-node WG was not removed. Only the obsolete assistant `.6` and the
  explicitly agreed TV `.8` were revoked; the owner recovery `.4` is kept.
  The phone `.7`/compromised key is a separate decision.
- After fixing overlapping transport marks on the flannel ingress
  NetworkPolicy, cross-node ordinary/forged probes were verified. Do not bring
  back the old bypass and do not change NetBird marking globally:
  [overlay guard](../../platform/kubernetes/k3s-networkpolicy-overlay-marks.md).
