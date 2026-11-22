# NetBird: user-access pilot (not the cluster transport)

> **The live-stage continuation:**
> [STUN and Kubernetes machine peers](../network/netbird/infrastructure/netbird-kubernetes-machine-peers.md).
> What is preserved below is the original routing/Network proposal, not the
> current status: control plane/OIDC-only already work; a simpler
> direct-overlay INPUT access to machine peers was chosen, without routed
> own-host prefixes and fake HA.

**Status as of 2026-11-02: the control plane can be planned separately; apply
and network are BLOCKED.** No NetBird component is installed; policies/IdP/
DNS/routes are unchanged. This is not a successful production acceptance
report and not HA Management. The approved FQDN
`netbird.socrat.alchemmist.xyz` and the Authentik OIDC are recorded.
DNS/TLS, the node, StorageClass, the ingress scope and STUN are not marked
done. The repository candidates `ingressClass=traefik` and
`storageClass=local-path` remain `verified: false`. The pilot is owner and
tim only. New machines are not approved. Router mode on the existing nodes is
allowed only after an explicit review; placement is not chosen and this
compiler does not generate it. Management is planned without routers. There
is no Argo Application for NetBird and no automatic synchronization.
`ansible/playbooks/netbird-control-plane.yml` by default runs only `check`
on localhost, without `become`. It is not part of `site.yml` and changes no
WG, routes or K3s transport.

## Boundaries and architecture

- `wg-socrat`, the addresses `10.250.0.1/3/2/5`, keys, AllowedIPs,
  Flannel/K3s, WG TCP transport, the existing recovery SSH and the user VPN
  are untouched.
- The user NetBird overlay has its **own CIDR, verified for collisions**. No
  exit node, `/0` routes, LAN `/24`, pod/service CIDR or all-to-all.
- The Community combined server (Management + Signal + Relay + STUN) is
  **one instance**, SQLite/PVC, `Recreate`, pinned to the chosen node. The
  Dashboard is also single. That is a SPOF; a local-path PVC does not become
  HA by recreating the pod.
- **Exactly two routing peers.** New machines are not approved. A peer on an
  existing node `socrat-0`…`socrat-3` is allowed only with
  `existing_node_router_mode_reviewed: true`. This compiler writes no
  host-router unit and calls no `router_compose` for such peers. Do not
  install the routing-peer Compose on K3s nodes. Placement in git is not
  reviewed. Each peer must independently reach **every** chosen backend. Two
  peers on different existing nodes are not proven as independent failure
  domains: power, switch or WAN failures are still shared.
- We use **Networks**, not legacy Network Routes: deny by default, resources
  only IPv4 `/32`, TCP 443 (web) and TCP 2222 (the existing OpenSSH). A
  separate destination group per resource; source groups only from JWT. The
  routing peer itself gets no input/peer-to-peer allow policy. Do not place a
  backend on the routing peer itself — otherwise other input-chain rules are
  needed, which are absent here.
- One Network with two individual routers, different metrics (for example
  primary/standby; the values are entered by the operator), masquerade=true.
  The reverse routes on the existing nodes are unchanged. All target ACLs
  must accept the SNAT address of **both** routers. Network identity does
  not replace application/SSH IAM.
- **NetBird SSH is disabled.** We change no SSH accounts, authorized_keys,
  SSH certificates, application settings, their roles, SSO/outpost or MFA.
  The existing OpenSSH checks the old host keys and user keys. Access to a
  login page does not mean access to the application without its
  authorization.

### An important L3/L4 boundary for web

Permitting `IP:443` permits all virtual hosts on that listener. Neither an
FQDN in documentation nor a NetBird domain resource is an SNI/HTTP ACL.
**You cannot simply permit the shared Traefik VIP** if it hosts unselected
applications. Before the pilot you need a dedicated IP/listener for the
selected services, or a separate default-deny frontend with a Host/SNI
allowlist, banning IP/default-vhost/other SNI. No such frontend has been
found; its addresses are not invented; this is a deployment blocker.
`endpoint_ip_port_scope_reviewed=true` means exactly the verification of
this boundary, not a formal agreement on a URL list.

## What is actually verified read-only

SSH with the existing keys/aliases, without TOFU/disabling HostKey checking:

```sh
ssh -o BatchMode=yes -o HostName=109.173.40.247 \
  -o 'HostKeyAlias=[socrat.alchemmist.xyz]:2222' socrat-0 'hostname; ip -4 route'
# socrat-1: the same override, HostKeyAlias [socrat.alchemmist.xyz]:2223
ssh -o BatchMode=yes socrat-2-direct 'hostname; ip -4 route'
```

Observed: socrat-0 LAN `192.168.0.23`, WG `10.250.0.1`; socrat-1 LAN
`192.168.0.24`, WG `10.250.0.3`, an additional `192.168.0.250/32`; the VPS
socrat-2 `176.98.185.59`, WG `10.250.0.2`. The Pod routes `10.42.0.0/16`
already use Flannel. On the VPS there are host routes to `.23/.24` via WG;
that is **not** permission to widen the mesh. On socrat-0 `sudo -n wg …` and
`sudo -n kubectl …` were refused (a password is needed). Therefore the
current AllowedIPs/handshakes, firewall, pod readiness, ingress and all
application listeners are **not confirmed** by this survey. No secrets were
read. `109.173.40.247` is an override for the SSH survey only, not a claim
about new DNS, Ingress or a STUN endpoint. The existing Authentik FQDN was
taken from repo values; its availability from an external client was not
verified in this work.

A repeated read-only SSH to `socrat-2-direct` on 2026-11-02, without sudo
and without reading secrets:

- The Traefik process matches the chart: ingress namespaces without NetBird,
  CRD only `argocd`, label `homelab.alchemmist.xyz/edge-transport=argocd`,
  `allowcrossnamespace=false`, `allowexternalnameservices=false`. UDP 443 is
  taken by HTTP/3.
- UDP 3478 is not listened on. TCP 22, TCP 2222 and TCP 443 are; the
  `sshd_config` contains `Port 22` and `Port 2222`. UDP 51830 is the existing
  WG and does not change.
- `kubectl` via `/etc/rancher/k3s/k3s.yaml` is unavailable: the file is root
  `0600`, `sudo -n` needs a password. Node Ready and the live StorageClass
  were not read on this visit. `local-path` remains only a candidate from
  other repository manifests.

## Release, security, license: official sources

Checked 2026-11-02; repeat before approving the deployment:

| Source | Result |
|---|---|
| [Latest release API](https://api.github.com/repos/netbirdio/netbird/releases/latest), [v0.82.0](https://github.com/netbirdio/netbird/releases/tag/v0.82.0) | Latest stable v0.82.0, published 2026-10-29; dashboard v2.96.0 |
| [Security advisories](https://github.com/netbirdio/netbird/security/advisories), [API](https://api.github.com/repos/netbirdio/netbird/security-advisories) | At the time of the request 9 advisories published, listed below; v0.82.0 is above all published fixed versions, **not** a guarantee of no unknown vulnerabilities |
| [LICENSE v0.82.0](https://github.com/netbirdio/netbird/blob/v0.82.0/LICENSE) | BSD-3-Clause outside management/signal/relay/combined; these server directories are AGPLv3; [dashboard v2.96.0](https://github.com/netbirdio/dashboard/blob/v2.96.0/LICENSE) AGPLv3 |
| [HA](https://docs.netbird.io/selfhosted/maintenance/scaling/high-availability) | Active-active Management and Signal — **Enterprise commercial license**, not free Community HA |
| [IdP](https://docs.netbird.io/selfhosted/identity-providers), [Authentik](https://docs.netbird.io/selfhosted/identity-providers/authentik) | Embedded IdP + external Authentik OIDC, JWT group sync; SCIM is absent in open-source Community, offered in Cloud/Commercial |
| [Routing peers](https://docs.netbird.io/manage/networks/how-routing-peers-work) | Multiple routing peers/failover — a separate data-plane feature; not a license for HA Management/Signal |

Advisories: GHSA-28q5-j9qm-gx35 (daemon file read, fixed 0.76.1),
GHSA-xmg2-v32j-x2hf (SSH Match injection, 0.74.7), GHSA-v5w2-pqxj-6r94
(relay unauthenticated gob, 0.75.0), GHSA-7wwh-vfq4-v488 (SOCKS bind, 0.74.7),
GHSA-jxxc-7jxf-v8hm (SSH dependency, 0.74.4), GHSA-fhw6-5mff-2gfh
(relay WebSocket DoS, 0.68.0), GHSA-qcpp-8vwj-hhwr (IPC privilege escalation,
0.76.0), GHSA-rxmp-8h9v-56cx (admin→owner escalation, 0.65.3),
GHSA-4g2w-p87c-hxch (Windows MSI repair escalation, 0.49.0).
Release 0.82.0 additionally fixes SSH root aliases/env handling, proxy
account validation and masking URL credentials. Do not enable unneeded
SSH/SOCKS/proxy features. The client daemon socket is a local privileged
surface; do not publish it or mount it into ordinary applications. Before
production separately check SBOM/CVE for the images and user installer
packages, security advisories for the dashboard, supported platforms and the
ability to security-update after the pilot.

AGPL does not forbid internal use; when modifying a network server component
there are obligations to provide the corresponding source to its users. A
legal review before an external service/distribution; this is not a legal
conclusion. **Do not scale Community replicas to 2** and do not promise
transparent management failover. Enterprise HA needs a separate project with
a license, PostgreSQL HA, Redis, NATS, an LB and separate relay endpoints.
The pilot does not implement it.

### Verifiable pins

`deploy/netbird/images.lock.json`: the index digest and Linux amd64/arm64
manifest digests, from Docker Hub Registry v2. A reproducible verification
compares the `Docker-Content-Digest` header, the SHA256 of the index **bytes
themselves** and the platform entries:

```sh
/tmp/homelab-iam-tests/bin/python scripts/netbird-pilot.py verify-images
```

The manifests/Compose use `repository:tag@sha256:…`, not `latest`. That is an
integrity pin, **not** a publisher-signature check. Before production,
verify provenance/signatures by the publisher's available mechanism and
approve the specific digests. The upstream installer is used only as a
reference, **was not run** and must not be run via `curl | sh`. URLs/SHA256
reference files and the docs commit are fixed in `upstream.lock.json` (docs
commit `f9fcde283a90733c38f701f1def05a6db68ebeb0`).

## The exact missing inputs / prerequisites

`deploy/netbird/pilot.inputs.json` is deliberately not deployable. Fill it in
a separate reviewed local file (do not substitute test fixtures):

1. `management_fqdn`: approved as `netbird.socrat.alchemmist.xyz`. DNS, A/AAAA
   and external TLS for this name are not yet verified;
   `dns_tls_public_before_vpn` remains false. The TLS secret lives in the
   `netbird-edge` namespace, not next to the runtime secret. The live Traefik
   on socrat-2 watches only the already-listed namespaces and only the
   `argocd` CRD with the label `homelab.alchemmist.xyz/edge-transport=argocd`;
   cross-namespace and ExternalName are off. Therefore the control plane
   renders an ordinary Ingress in `netbird-edge` and a local forwarder at the
   same digest already pinned in `charts/traefik-edge`. The forwarder itself
   goes to the `netbird-pilot` ClusterIP via DNS. The chart is unchanged:
   the Argo application `traefik-edge` has automated self-heal and the Role
   on the watched namespace reads Secrets. Adding only `netbird-edge` to
   `watchNamespaces` is described in
   `deploy/netbird/traefik-scope-delta.json` and not applied. Do not add
   `netbird-pilot` to the watch. Until that exists, the rendered Ingress
   creates no public endpoint. Bootstrap Authentik and
   Management/Dashboard must be reachable before the VPN, but not through
   the public `/api/setup`. A private-only Authentik is still forbidden.
2. `management_node`, `storage_class`: the real node, free CPU/RAM/disk,
   storage locality, PVC backup/restore, release-compatible K3s/Traefik. The
   `local-path` candidate is not confirmed by the live API. `stun_node_port`:
   a free UDP NodePort, external UDP **3478 → the chosen node:NodePort**,
   firewall/NAT, mapping persistence after a restart, an external STUN test.
   Upstream `autoConfigureClientSettings` advertises `stun:<fqdn>:3478` to
   clients, not the NodePort number. On socrat-2 UDP 3478 is currently
   closed. Do not forward this NodePort to other nodes:
   `externalTrafficPolicy=Local`.
3. `overlay_cidr`: a separate IPv4 `/16…/24`; check the client's routes, LAN,
   CGNAT, other VPNs, Docker, Kubernetes. The built-in ban on known CIDRs is
   not a full inventory check. Configure the account range **before** any
   peer enrollment.
4. `routing_peers`: exactly two `{name, host, failure_domain, metric}`.
   Placement **not chosen**. Approve real DNS/IP, distinct physical failure
   domains, recovery SSH/console, Linux kernel/netfilter/TUN/Docker Compose,
   endpoint reachability, the target SNAT/firewall and an independent path
   for both peers. Do not move these functions onto the existing nodes. The
   control-plane `plan`/`apply` renders no Compose and issues no network.
5. `oidc_client_id`, the confirmed `authentik_issuer` (only a repo-based
   candidate slug pre-filled), `login_group`; exact source group names, the
   pilot users/devices, owner/break-glass custody. The client secret and
   setup keys are **not input JSON**.
6. `resources` deliberately empty. Private Grafana and the existing socrat-2
   OpenSSH are approved as the pilot's targets, but not as deployable
   `/32`s. Grafana is one virtual host of the shared private frontend `:443`
   together with other applications; a shared IP:443 is not a boundary. The
   socrat-2 OpenSSH already listens on the public `:22` and `:2222`; the
   address `10.250.0.2` belongs to the mesh and is not used as a pilot
   destination. A separate listener/firewall is needed before any allow
   policy.
7. All review gates, including `ingress_scope_reviewed`,
   `storage_locality_reviewed` and `management_node_reviewed`, must become
   explicitly `true` only after an actual check. The control-plane apply
   requires the five control-plane gates and requires no router gates.
   Access to resources still requires all gates, an empty snapshot and two
   router IDs. Owners/change windows, out-of-VPN recovery, the SLA for
   failover/revocation, rollback, an external test client and a second
   control unprivileged client are needed.

Additionally, after the initial control-plane setup you need the real IDs
`network_id`, `source_groups`, `resource_groups`, `peer_ids`, a fresh
read-only API snapshot and an independent diff review. The generator **does
not guess** API IDs, DNS, IPs or credentials.

## Reproducible preparation, without production writes

```sh
PY=/tmp/homelab-iam-tests/bin/python
$PY -m unittest discover -s tests -p 'test_netbird*.py' -v
$PY ansible/scripts/netbird-deploy.py check          # expected BLOCKED: audit and empty gates
$PY scripts/netbird-pilot.py validate        # expected BLOCKED with repo inputs
# After a separate reviewed inputs and a new audit with the blockers cleared:
$PY ansible/scripts/netbird-deploy.py plan --inputs /protected/pilot.inputs.json --audit /protected/audit.json --out /tmp/netbird-reviewed
# apply requires --context and the passphrase apply-netbird-control-plane. No Argo sync is called.
```

## Control plane without issuing a network

`render-control-plane` writes only the `netbird-pilot` and `netbird-edge`
namespaces. One server Deployment and one dashboard, strategy `Recreate`.
That is a SPOF, not HA. The runtime secret `netbird-runtime` is not created by
a manifest. There are no keys in git. `runtime-config` writes `0600` outside
the worktree. The bootstrap mode keeps `localAuthDisabled: false`, because
v0.82.0's `NewEmbeddedIdPManager` refuses to start with `localAuthDisabled`
while Dex has no external connector. The `auth.owner` field is not written:
upstream puts the YAML `password` bcrypt `Hash` in without hashing.
`NB_SETUP_PAT_ENABLED` is not set. The public forwarder refuses `/api/setup`
and `/api/users/invites` (`ipAllowList` only `127.0.0.1`, without trusting
`X-Forwarded-For`). `scripts/netbird-bootstrap.py` accepts only the loopback
origin from `kubectl port-forward` and prints `user_id`/`email`. The password
and PAT are not printed. The body matches `SetupRequest` v0.82.0: `email`,
`password`, `name`, without `create_pat`.

After an external connector appears, a separate witness
`{"external_connectors": N}` and `--auth-mode idp-only` switch off the local
password login. A witness with a secret or with zero connectors is rejected.
That by itself creates no Authentik application.

Native gRPC goes through a separate Ingress with `scheme: h2c` to
`/management.ManagementService/` and `/signalexchange.SignalExchange/`. The
WebSocket `/ws-proxy/management`, `/ws-proxy/signal` and `/relay` go over
HTTP/1.1. STUN stays the container's UDP 3478, externally a NodePort. Metrics
9090 are not published by the Service. The simplified YAML does not load
`disableDefaultPolicy`, so the first account still gets the Default
allow-all; the access compiler still requires an empty policy list before
enrollment.

The SQLite backup is `scripts/netbird-backup.py plan`. It describes stopping
the single replica and a read-only pod without the runtime secret. `execute`
requires the passphrase `quiesce-netbird-sqlite` and was not run in this
work. The same store/cookie keys are needed for the restore; new keys make
the old database unreadable. This is not HA and not an online copy.


The output directory must not exist. The result: management Kubernetes YAML,
two separate router Compose files, an account-settings **merge fragment**,
OIDC public fields, access intent. This is not an Argo application and not
an apply command. The files contain no secrets. Do not place the rendered
directory into `deploy/argocd/apps` or a watched Argo source.

An additional upstream contract check (needs `jsonschema` in the test venv,
optional):

```sh
curl -fsSL https://raw.githubusercontent.com/netbirdio/netbird/v0.82.0/shared/management/http/api/openapi.yml \
  -o /tmp/netbird-v082-openapi.yml
NETBIRD_OPENAPI_FILE=/tmp/netbird-v082-openapi.yml $PY -m unittest discover -s tests -p 'test_netbird_pilot.py' -v
```

The test will check the SHA256 against the lock and the JSON request bodies
against the official schemas. A successful schema/unit test does not prove
the runtime semantics of the IdP/routes.

### The source check actually performed (2026-11-02)

- 17 new tests PASS in `/tmp/homelab-iam-tests`, including the optional
  pinned upstream OpenAPI contract test; without `NETBIRD_OPENAPI_FILE` that
  one test explicitly SKIPs.
- Digest verification of three images PASS (index bytes + amd64/arm64
  manifests).
- The rendered **synthetic test fixtures**, not production: seven core
  Kubernetes objects passed the strict JSON schemas v1.34.0; the
  IngressRoute — the official Traefik v3.5 CRD schema; both Compose files
  passed `docker-compose config -q` and the Compose schema. That is not a
  server-side dry-run on the target cluster and not running containers.
- The existing Authentik tests: 30 PASS; identity tests: 14 PASS.
- The existing WireGuard suite: 28 tests, 26 PASS, **2 baseline failures** in
  `test_wireguard_admin_client`:
  `test_profile_does_not_capture_dns` (the template already contains
  conditional DNS) and
  `test_dns_is_privileged_and_scoped_to_dns_tag` (≥4 `become: true` expected,
  2 in the baseline). These tests/templates/roles are not changed by the
  pilot; their fix is out of scope of the narrow commit. The initially
  missing `jinja2` was added only to the test venv, after which the suite was
  repeated without import errors.
- The default `validate/render` is deliberately BLOCKED until filesystem
  output. Live probes, actual NetBird runtime config parsing, IdP login,
  failover, revocation, restart, restore and production acceptance were
  **not performed**.

## Only after an explicit reviewed deployment approval

The following steps are a **plan of future production writes**; none were
performed in this work.

1. Take a protected baseline of `ip addr/route/rule`, the WG public peer
   IDs/AllowedIPs/handshakes (never `wg showconf`/`wg … dump` with a private
   key), the firewall, Node Ready, cross-node pod/DNS, ingress/SSH probes.
   Verify console/public recovery and the backup. Do not save these data in
   Git. Outside the VPN verify the DNS/TLS of Authentik and the new edge.
2. Protect the first-owner bootstrap: a temporary edge source-IP allowlist
   for the operator, or an authenticated administrative tunnel until the
   initial setup. Do not leave the unclaimed `/api/setup` open to everyone
   and hope the real owner manages to be first. First the namespace, the
   TLS secret/cert and the runtime config; then the reviewed singleton
   manifest.
3. Runtime secret injection: the secret manager issues **distinct**
   `NB_RELAY_SECRET` (at least 32 random characters), `NB_COOKIE_KEY`,
   `NB_STORE_KEY` (both base64 of 32 random bytes). Do not print/pass the
   values in CLI arguments, Git, shell history, CI logs, `set -x`, env
   dumps. Run from a trusted operator in a protected process;
   `runtime-config` writes a new 0600 file and does not follow symlinks:

   ```sh
   # The variables are already injected by the secret manager; their values are NOT here.
   $PY scripts/netbird-pilot.py runtime-config --inputs /protected/pilot.inputs.json \
     --out /run/user/"$(id -u)"/netbird-config.yaml
   # Only after approval; the runtime file is on tmpfs, not in the repo:
   kubectl -n netbird-pilot create secret generic netbird-runtime \
     --from-file=config.yaml=/run/user/"$(id -u)"/netbird-config.yaml
   ```

   The command assumes an already-created namespace. Delete the temporary
   file after injection, remove the env from the session; encrypt the
   Secret in etcd/backups, restrict RBAC. Keep the encryption/cookie keys
   together with the encrypted backup — do not regenerate them on a restore.
   Missing secrets mean the server does not start; do not create a
   placeholder Secret.
4. Through the protected initial setup the first owner creates only the
   pilot account. **Immediately delete the Default allow-all policy and any
   legacy Routes, before enrollment**. Apply the account-settings merge
   fragment via a read-modify-write of the current account, preserving
   unrelated settings. Do not treat the fragment as a full account PUT
   body. No canary or routing peer before checking
   deny-by-default/overlay range.
5. Authentik: separate OAuth2 confidential provider/application for the
   NetBird pilot; leave the existing app providers/bindings/SSH IAM
   unchanged. Apply a separate group application binding (deny for
   outsiders), the existing MFA policy, a signing key. The issuer is the
   exact application issuer with a trailing `/`. In NetBird Settings →
   Identity Providers choose Generic OIDC, the runtime client secret; copy
   the **real Redirect URL from the UI** into Authentik as Strict; do not
   guess the callback, no regex/wildcard. Take the optional strict logout
   callback from the UI/docs. The Dashboard uses the embedded issuer
   `/oauth2`; Authentik is an upstream connector — do not substitute the
   dashboard authority with Authentik.
6. **OIDC/group sync remains STOP; a working configuration is not proven.**
   The pinned upstream [v0.82.0 `idp/dex/connector.go`,
   `buildOIDCConnectorConfig`](https://github.com/netbirdio/netbird/blob/v0.82.0/idp/dex/connector.go)
   was checked: generic OIDC (and the `authentik` branch) requests **only
   `openid profile email`** from upstream, with
   `insecureEnableGroups=true`. Only the special okta/pocketid branches add
   groups. The Dashboard's `AUTH_SUPPORTED_SCOPES=... groups` applies to the
   embedded issuer and does **not** widen this upstream request. The repo's
   `homelab-groups` with `scope_name=groups` is therefore by itself
   insufficient; do not change the shared mappings of other applications.
   Check the real authorization request without writing code/token/secret
   into logs. For a separate NetBird Authentik provider a separate mapping
   bound to the **requested `profile` scope** may be needed, e.g. a filtered
   allowlist `{"groups": [g.name for g in request.user.ak_groups.all() if g.name in APPROVED_NAMES]}`
   (APPROVED_NAMES are reviewed values) and `Include claims in id_token`.
   That is a hypothesis for a separate acceptance, **not an
   applied/verified setting**. Do not change the global default profile or
   substitute the connector type for the sake of a scope request. Before any
   allow policy prove the upstream claims, the resulting embedded NetBird
   access JWT `groups`, JWT-issued membership and propagation/removal on
   **every** device. Do not store/print tokens. No correct groups in at
   least one link, a fresh login or a removal — **STOP**; do not open
   access. JWT group sync=`groups`, propagation=true, JWT allow
   groups=`login_group`. Verify the owner is in the login group before
   saving the allowlist (otherwise a lockout). Source groups **are created
   by sync from JWT**, not manually with a matching name: a matching
   API-created group does not automatically become JWT-synced.
7. Only after deny/account-settings and an explicit
   `existing_node_router_mode_reviewed`: placing the two peers on the
   existing nodes produces a separate host-router artifact. This compiler
   neither writes nor applies it. New VMs are not used. Setup keys:
   usage_limit=1, short expiration, auto-group only for routers, not user
   access groups; revoke after enrollment. The setup-key file is 0400/0600,
   not in git and not in the environment. Do not install the routing-peer
   Compose on the socrat nodes. Do not clone one peer identity. For the
   canary install the verified client **0.82.0**, not `latest`, on a
   separate external device without a simultaneously active administrative
   WG (otherwise the `/32` resource routes could intercept the recovery
   path). After approval:
   `netbird up --management-url "https://$REVIEWED_MANAGEMENT_FQDN" --allow-server-ssh=false --disable-dns`.
   That preserves the system DNS; the selected names must resolve via the
   approved public-private-A or split records before enrollment. A single
   user canary may log in to materialize the JWT groups while the policies
   are still **zero**: there is no access to resources.
8. Create an **empty** Network `netbird-pilot` and empty **`issued=api`**,
   uniquely named destination groups `pilot-resource-<resource.name>`
   (without peers/resources). JWT/integration-issued destination groups are
   forbidden: propagation could later add user peers to destinations instead
   of only the approved resource `/32`s. The Network response must contain
   the current API fields `routers=[]`, `resources=[]`, `policies=[]`,
   `routing_peers_count=0`; a missing/null/partial response does not count
   as empty. The group response must explicitly contain `issued`,
   `peers=[]`, `resources=[]`. The compiler rejects a partial
   deployment/replay; an old snapshot is not permission to re-apply. After
   any write take a new snapshot and make an independent current-state diff
   before the next reviewed action; the offline compiler makes no atomic
   transaction with the server and will not detect stale-file drift.
   Collect into a protected local JSON snapshot the responses of GET
   `/api/policies`, `/api/routes`, `/api/groups`, `/api/peers`,
   `/api/networks` as the keys `policies`, `routes`, `groups`, `peers`,
   `networks`. The API token is read-only for reading; do not print auth
   headers; the snapshot may contain PII. The bindings JSON has the keys
   `network_id`, `source_groups` (name→ID), `resource_groups`
   (resource.name→ID), `peer_ids` (router.name→ID). Then:

   ```sh
   $PY scripts/netbird-pilot.py compile-access --inputs /protected/pilot.inputs.json \
     --bindings /protected/bindings.json --snapshot /protected/snapshot.json \
     --out /protected/access-requests.json
   ```

   The compiler requires the absence of **all** policies/legacy routes, a
   separate Network, JWT source groups, empty destination groups, two
   distinct router IDs. The output is an ordered list of API requests,
   **not an auto-apply and not an idempotent reconciler**. Before the manual
   execution repeat a fresh snapshot/diff; a stale snapshot is no protection
   against concurrent writes. Verify the Network still has no
   resources/routers. POST the two routers, then the resources and the
   narrow policies, without a Default policy. A repeated POST creates
   duplicates — after a partial failure first do an inventory/reconcile
   manually, not a replay.
9. Verify the independent reachability of both routers, the client's split
   DNS/selected FQDNs and the absence of unrelated DNS changes. Do not give
   the client the whole management subnet for DNS's sake; exact public
   private-A records or reviewed local split records require no route to
   `10.250.0.0/24:53`. If a separate DNS backend is needed, the current
   allowlist does **not** permit it: a separate review/schema extension, not
   a bypass of the ban.
10. A manual change review and dry-run/schema validation on the target
    API/CRD version, then one canary. Do not include the others before the
    acceptance below.

## Acceptance: the author's checks, in fact NOT performed

Keep UTC timestamps, client/server versions, the commit/input hash, the
topology, the results and the chosen routing peer ID; not tokens/passwords/
config backups. All fault injections — not on the WG transport and not by
installing the router Compose on production nodes. A fault-injection host
router is a separate reviewed change.

The read-only probe runs **on the external pilot client**, not on the
routing peer:

```sh
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect allow --phase baseline > /protected/baseline.json
# With the approved shutdown of router-a, then router-b (the second must be restored):
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect allow --phase router-a-down --attempts 30 --interval 2 > /protected/router-a-down.json
# After revoking the same user's access, without client logout/restart:
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect deny --phase revoked > /protected/revoked.json
# One pre-chosen forbidden endpoint/port, no scanning:
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect deny --phase negative --negative-ip "$REVIEWED_DENIED_IP" \
  --negative-port "$REVIEWED_DENIED_PORT" > /protected/negative.json
```

The probe makes new TCP connections; for web — CA/hostname-verified TLS/SNI
and a check of the exact DNS A/AAAA set against the `/32`; for SSH — TCP
only, **not a user login/host-key test**. For SSH separately run the
ordinary OpenSSH with the existing keys/known_hosts,
`StrictHostKeyChecking=yes`, without creating users or changing
authorized_keys. Deny is verified by direct IP: a DNS or TLS error on an
open TCP does **not** count as deny. Connection refused/timeout **by
itself** does not prove a policy deny: a healthy backend and a simultaneous
allow probe from a non-revoked control user are needed. The repeated allow
probe returns exit 1 on any transient failure: for failover evaluate the
time series/recovery time rather than demanding zero packet loss.

| Scenario | Criterion / required evidence |
|---|---|
| External bootstrap without VPN | DNS/TLS of the Dashboard, Management discovery and Authentik reachable; ordinary private apps unreachable without VPN; MFA/strict callback works |
| Baseline | The selected web DNS→only the approved private IP, correct CA/SNI, the existing app IAM; the selected SSH host key and user login; direct/relayed status recorded |
| Default deny | A foreign user/device, peer-to-peer between users, the router's own NetBird/LAN IP, unselected hosts, other ports of the same host, K3s 6443, etcd 2379/2380, Pod/Service CIDR, LAN and Internet exit are not provided. Unrelated internet/DNS use the previous path |
| Shared-IP bypass | A different Host/SNI, an IP URL, an unknown/default vhost, IPv6 and an alternative public endpoint give no access to unselected private apps. A bypass found → STOP |
| Each router separately | Isolate in turn **only the NetBird process/VM** of primary and standby. On primary failure new connections recover via standby within the approved SLA; the client's `netbird status -d`, `netbird networks ls`, the switch reason + counters on the surviving router confirm the other path. On standby failure the primary keeps working. Then swap the metrics in a separate review to prove both directions |
| Hard failure and relay | Not just a clean stop: loss of the VM/NetBird network (relay may detect in about a minute). Verify the direct and forcibly relayed path, reconnect/roaming/sleep; do not block the production WG. Agree on the SLA before deployment, provisional pilot budget 120 s, measure detection separately from connect |
| Failback / SNAT | After the lower-metric router returns the client fails back automatically; masquerade changes the source, TCP/SSH may reset. A fresh connection works; **do not promise seamless SSH survival** |
| Both routers down | The selected endpoints fail closed, no fallback via public ingress/another VPN; after recovery again allowlist-only |
| Management/Signal/Relay outage | Separately switch off the pilot Deployment/close the pilot edge. Record: existing direct sessions may continue, new enroll/policy/reconnect may not work; a relay outage breaks relayed data. That is not an HA acceptance. No immediate revoke can be promised while the management plane is unreachable |
| Deleting an Authentik group | Remove the web/SSH group from an already-connected client; verify the new JWT after refresh/reauth, the NetBird user group and propagation to **all devices**, both routing ACLs. Without reauth an old JWT may stay in effect: record the real delay. Login-group removal must block a new login, but that is not proof of the old tunnels being torn down |
| Emergency revoke | NetBird block user + revoke/delete **all his peers**, not only the setup key/session; on a live connected client verify new TCP and already-open web/SSH sessions via both routers. The healthy control user works. If established conntrack/old maps keep access — STOP until an agreed targeted pilot containment; do not flush the shared conntrack/firewall WG |
| Offline/stale client and control plane down | Repeat the revoke with an offline/sleeping client, on refresh/connection, then with the management unreachable. Record the boundaries: JWT sync is not SCIM push and not real-time revoke. A strict immediate isolation needs an independent target/routers firewall kill path and a separate project; without it the pilot does not meet such an SLA |
| Restart/restore | Each VM, the server pod and the approved NAT restarted; same state identity, TLS renewal, a backup restore in isolation, deny does not disappear |
| Production immutability | Before/after: addresses/WG public peer IDs/AllowedIPs, routes, K3s Ready, cross-node pod/DNS, the existing private web/SSH/recovery and the user VPN; no differences outside the pilot namespace/VM |

Peer login expiry=3600s reduces the lifetime but **is not a guarantee of
immediate network revocation**. Setup-key expiry/revoke does not revoke an
already-enrolled peer. An operational emergency runbook, monitoring of the
group-sync delay and the absence of manual extra memberships that would
outlive the JWT group's removal are needed.

## Rollback / operational risks

Before the rollout approve the owner and a recovery contact. On a leak/broad
exposure first disable the pilot policies/peers or stop **both reviewed
routing peers**; do not change `wg-socrat`/the K3s routes. Remove the pilot
profiles/split-DNS on the clients; remove only the new edge/STUN mapping;
stop only the pilot workloads, keeping the protected backup/PVC and keys for
the investigation. Do not delete the cluster-wide Traefik/cert-manager or
the existing Authentik; remove only the separate NetBird
provider/application after the sessions end. Restore the before/after
health baseline. Deleting the namespace/PVC is a separate decision about the
data.

Risks before production: SPOF Management/Signal/Relay/IdP/storage; a shared
LAN/WAN for the two routers; NAT and SNAT resets; shared-ingress lateral
access; stale JWT/maps/conntrack; privileged router capabilities and daemon
IPC; unverified target firewalls; unperformed runtime acceptance/restore/
upgrade; the limited Community observability. The backup includes the
SQLite store/events/embedded IdP DB and the encryption keys; take it
consistently with the stopped singleton or the ordinary verified backup — do
not copy a live SQLite without consistency.

**Deployment-ready:** the locally reproducible compiler/intent, the
runtime-secret contract, pins, offline tests and the acceptance plan.
**Not deployment-ready:** the actual topology/DNS/TLS, the
endpoint/group allowlist, the IdP provider, the recovery/revocation SLA and
the real acceptance. A canary deploy is possible only after all blockers are
closed and a separate reviewed approval.
