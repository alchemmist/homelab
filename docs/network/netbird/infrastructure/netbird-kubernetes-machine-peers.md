# NetBird: STUN and machine peers in the existing Kubernetes

## Result of the live stage, 2026-11-02

This continues `d6cf22b` and is **not a claim of a successful user VPN**.
Management/Dashboard remain on socrat-0, a single SQLite writer, no HA.
TLS/OIDC-only on `netbird.socrat.alchemmist.xyz` preserved,
`localAuthDisabled=true`. After the change, the independent relay nonce passed
again in both directions through the two TLS entrances. The combined v0.82.0
generic `/health` was not fixed and not faked as “healthy”: management readiness
and the relay payload are separate checks.

**STUN really works:** `stun:176.98.185.59:3478` (UDP).
Do not use the management FQDN as the STUN hostname: it has two entrances, and
`109.173.40.247:3478` does not respond. The home NAT/router was not changed.

Before writing, the exact Kubernetes resources, Services/externalIPs and UDP
listeners on both nodes were checked: no conflict on 3478; the existing WG51830
was preserved. A fresh quiesced encrypted backup of SQLite + Kubernetes/runtime
configuration was created and verified by decryption in a **closed** remote
journal. PAT/keys/Secrets were not copied into git and not printed.

### Why not an ordinary externalIPs Service

1. A new `netbird-pilot/stun-public`, UDP3478, externalIP176.98.185.59 with the
   endpoint combined server on socrat-0 produced a correct STUN transaction, but
   **XOR-MAPPED-ADDRESS=10.42.0.0**. Inter-node kube-proxy SNAT makes such an
   answer useless for NAT discovery. That was a test failure, not STUN
   acceptance.
2. A STUN-only coturn pod on socrat-2 + `externalTrafficPolicy: Local` fixed the
   external client, but a request from socrat-0 itself still got **10.42.2.0**:
   kube-proxy separately routes locally-originated externalIPs through the
   cluster chain. Local alone does not remove the host hairpin.
3. Per the agreed placement refinement, on the **existing socrat-2** a single
   `Deployment/netbird-pilot/stun` with `hostNetwork:true` remains, listener
   strictly **176.98.185.59:3478/UDP**. Its own Service and the additive
   NetworkPolicy were deleted with DELETE preconditions on exact
   UID/resourceVersion. No changes to global kube-proxy, the host firewall, WG,
   NAT/router or new machines.

Renderer: `scripts/netbird-stun.py`, official `coturn/coturn:4.7.0` with an
immutable index digest in `deploy/netbird/images.lock.json`. The manifest
SHA256 was compared with `Docker-Content-Digest`; this is an integrity pin, not
a publisher signature. The container is nonroot65534, without
hostPID/rootfs mounts/SA token, read-only rootfs, 32Mi memory cap, 100m CPU cap,
requests8Mi/5m, tmpfs<=1Mi, one relay thread.
`--stun-only --no-tcp --no-tls --no-dtls --no-cli`; no TURN/admin/web/debug
exposure. `--stun-only` ignores TURN requests; `--no-auth` here concerns public
Binding, **not TURN permission**. RFC5780 is not enabled. The official
`/usr/bin/turnserver` carries the file capability NET_BIND_SERVICE: with
dropALL and without that bounding bit, exec gave EPERM, so only NET_BIND_SERVICE
was kept, although port3478 itself is unprivileged. No blanket privileged
option. The initial non-working pod was replaced; the final pod has 0 restarts.

Into the private runtime `netbird-runtime`, **only** this was added:

```yaml
server:
  stuns:
    - uri: stun:176.98.185.59:3478
      proto: udp
```

This is a **delta, not a complete Secret/config for apply**. `combined/cmd/config.go`
v0.82.0: `ApplySimplifiedDefaults`, `applyRelayDefaults`,
`autoConfigureClientSettings` — a nonempty `server.stuns` disables local STUN
and publishes exactly this list. Therefore a Service on the combined server is
no longer needed. Reading the Secret after the guarded replace confirmed the
absence of other changes.

### Real checks, not only the UDP socket

`scripts/netbird-stun-check.py` verifies the source endpoint, response
type/length, the magic cookie, the exact random transaction ID, the XOR-MAPPED
IPv4 and the TURN Allocate denial. One run — three UDP requests with a 3s
timeout, no load test.

| From | Endpoint | Verified XOR-MAPPED | TURN Allocate |
|---|---|---|---|
| external worker | 176.98.185.59:3478 | public 93.158.185.136 | timeout/ignored |
| host socrat-0 | 176.98.185.59:3478 | **109.173.40.247**, exact expected | timeout/ignored |
| host socrat-2 | 176.98.185.59:3478 | **176.98.185.59**, exact expected | timeout/ignored |
| all three | 109.173.40.247:3478 | timeout, **not advertised** | — |

The HTTPS proxy egress of the worker differs from the UDP egress; do not compare
STUN with `curl` through an HTTP proxy. For the external worker a public address
was confirmed; an independent attestation of its egress is not claimed; the two
host tests compare against pre-known exact public addresses. `ss` on the VPS
confirmed the UDP listener only on 176.98.185.59:3478, no TCP3478/5349 and no
UDP5349. Existing unrelated listeners, including 8080, were not touched.

```sh
python3 scripts/netbird-stun-check.py
# on host socrat-0:
python3 /tmp/netbird-stun-check.py --expected-source 109.173.40.247
# on host socrat-2:
python3 /tmp/netbird-stun-check.py --expected-source 176.98.185.59
```

This is not a TURN relay, but a public STUN can still be used for UDP
reflection. CPU/memory are limited; a **packet-rate limit is not set**: changing
the host firewall was out of scope for this stage. coturn's
`max-bps`/`bps-capacity` limit TURN sessions; they do not prove rate limiting
of Binding. A candidate for separate review: a source-keyed UDP3478 limit of
about 30 Binding/s, burst 60, plus a general ceiling; assess shared NAT and
monitoring, do not apply blindly.

## The simpler architecture: two machine peers, no routes

`scripts/netbird-host-peer.py` is a **new** Kubernetes renderer, not the
Docker/systemd `netbird-host-router.py`. The legacy router/Network plans remain
historical and are not used for this stage.

- socrat-0 and socrat-2 are ordinary machine peers with **their own** overlay
  addresses.
- No route `10.250.0.2/32` via socrat-0 is needed; no routing of one's own host,
  SNAT/FORWARD, exit node, fake route HA or route imports.
- Both agents: `NB_DISABLE_CLIENT_ROUTES=true`,
  `NB_DISABLE_SERVER_ROUTES=true`, `NB_DISABLE_DNS=true`, a separate
  `nb-host`/UDP51871 (check for a conflict before activation); NetBird SSH off.
  The native OpenSSH on socrat-2 already listens on 2222.
- socrat-2's own overlay :2222 is an **INPUT** chain that the NetBird agent
  filters. v0.82.0 source `client/firewall/iptables/chains_linux.go` and
  `client/firewall/nftables/chains_linux.go` binds the INPUT ACL to the peer
  iface. Do not add global SSH accept/drop and do not change public/recovery SSH.
- Only group-based directed TCP policies:
  JWT `netbird-pilot-grafana` → API destination `netbird-machine-grafana`, 8443;
  JWT `netbird-pilot-ssh-socrat-2` → API destination
  `netbird-machine-ssh-socrat-2` (socrat-2 peer only), 2222.
  No `All`, protocol-all, bidirectional grants or route/Network resources needed.
  The Grafana destination may include socrat-0 and later socrat-2 with separate
  frontend listeners — that is not route HA.

### What is prepared, and what is NOT installed

The renderer produces a separate namespace `netbird-host-peers`, a 64Mi PVC per
host, Recreate Deployments, pinned NetBird 0.82.0, hostNetwork, **only**
NET_ADMIN/NET_RAW/BPF + the CharDevice `/dev/net/tun`. No Docker daemon,
hostPID, privileged, host `/`, `/etc/wireguard`, SSH files or cluster API token.
State/private key is stored in the PVC; the Secret is passed only via
secretKeyRef. A client image smoke pod on socrat-0 really printed `0.82.0`, was
then removed; it did not connect to management, without
hostNetwork/NET_ADMIN/TUN/credentials.

**All peer and frontend Deployments are deliberately replicas=0.** The renderer
applies nothing, creates no keys, calls no API and authorizes no activation.
The namespace/PVC/peer/frontend workloads are not installed yet. Kubernetes
server-side validation passed with the resources' namespace temporarily
replaced in a dry-run by the existing `netbird-pilot`: a Kubernetes dry-run
does not create namespaces for subsequent documents. No real apply of machine
resources happened.

```sh
python3 scripts/netbird-host-peer.py > /tmp/netbird-machine-stage.yaml
# render the frontend only with the ACTUAL address of an enrolled machine peer:
python3 scripts/netbird-host-peer.py --frontend-host socrat-0 \
  --overlay-ip 100.96.1.2 > /tmp/netbird-machine-with-frontend.yaml
# this address is an example only, NOT an actual peer/IP
python3 scripts/netbird-host-peer.py --frontend-guard
python3 -m unittest discover -s tests -p test_netbird_host_peer.py -v
```

96Mi agent / 32Mi frontend is a **candidate budget, not proven working memory**.
Before the STUN VPS had 557Mi available, after — 568Mi; the actual STUN uses
about 4Mi, 0 restarts. The conservative budget preflight: available>=417Mi
(256reserve+96agent+32frontend+32STUN+1tmp). Do not treat these numbers as a
guaranteed fit: before activation, repeat the memory/CPU/port/interface
baseline; watch cgroup memory/OOM/events/latency. If the margin is <256Mi or
there is an OOM — stop the new workloads; do not raise limits/change existing
services blindly.

### The Grafana frontend

TLS listener on **the actual overlay IP:8443 only**, not wildcard/public/WG.
Traefik uses strict SNI + the certificate for Grafana, HTTP router only
`Host(grafana.socrat.alchemmist.xyz)`, fixes the upstream Host to the same
hostname, and the upstream is **10.250.0.3:443**, serverName=Grafana, TLS
verification on. Before the frontend, the user provides a separate runtime TLS
Secret; the renderer does not copy TLS private keys from other namespaces.
A separate nft guard belongs only to `table inet netbird_peer_frontend`:
DROP TCP8443 when iifname!=nb-host; no SSH/UDP/WG/NAT/FORWARD changes. Before
installing: make sure the table does not exist, check `nft -c`, then install via
the separately authorized NET_ADMIN path; the renderer does not apply the guard
itself. **Do not enable the frontend without a real verification of this guard**,
SNI/Host negative tests, allow/deny peer ACL and a direct-public negative test.

The upstream was verified with real trusted TLS with SNI/Host Grafana through
10.250.0.3:443: HTTP200, `<title>Grafana</title>`. No public Kubernetes Ingress
for Grafana was found; none was created or changed. The separate private path
works independently of publishing the NetBird frontend.

## The blocking human step and a safe continuation order

The read-only native owner handover was checked once: there is no exact owner
subject yet, **OIDC users0**. The API shows only `All(issued=api)`, JWT source
groups absent, **policies0 / peers0 / setup-keys0**. Therefore enrollment and
grants were **NOT performed**. The owner must personally go through a real OIDC
login — not impersonation, password/MFA reset, person creation or email merge.
Only the approved exact UUID+connector may pass the separate native handover;
this stage elevated nobody and transferred no owner role.

After the real login:

1. Read-only verify the owner subject and both source groups `issued=jwt`. Do
   not create same-named API groups and do not rewrite JWT source membership by
   hand.
2. A fresh encrypted backup; re-read **policies=[]**, peers/groups/setupkeys,
   the safe membership and fresh CPU/memory/ports/TUN/interface/netfilter
   baselines. `preflight()` fails closed on an unexpected peer/group/state; it
   is a helper for a live read, not a “paper” permission to apply.
3. Create native API keys one by one, `type=one-off, usage_limit=1, expires_in=600,
   auto_groups=[], ephemeral=false`, one per host. Store the key only in a
   private journal with 0700/files 0600 and in the Kubernetes Secret; not in
   argv/output/the repository.
4. Activate only one agent, without policies; verify identity, the real overlay,
   the agent default-deny and the absence of client/server route imports.
   Watch for OOM. Remove/revoke the enrollment Secret/key per a separate
   restart plan: the entrypoint runs `netbird up` on restart; the PVC identity
   must be preserved.
5. Create only dedicated destination groups with the exact peer IDs; re-read
   the memberships, then the exact two TCP policy bodies from `policies()`; no
   All.
6. The frontend only after the actual IP/TLS secret/guard; verify
   positive/negative JWT group access, wrong Host/SNI, direct public denial,
   a separate SSH login with the user's private key (the existing SSH
   keys/config unchanged). Only after these tests can the user VPN be accepted.

### Rollback of the current STUN stage

Before rollback, re-verify resource UIDs/owners and a fresh snapshot. Restore
**only** the previous content of `netbird-runtime` from the private
`journal/stage5-runtime-secret-before.json` with a guarded replace using the
current resourceVersion, restart the single server, verify OIDC/readiness/relay.
This returns the original FQDN-STUN configuration, **not a working external
STUN**. Delete only the own `Deployment/netbird-pilot/stun` by UID
precondition. The deleted `stun-public`/`allow-stun-binding` no longer exist;
do not recreate them. Do not delete the existing management PVC/Secrets; do not
change WG/SSH/firewall. Roll back future peer/frontend work separately; do not
delete their identity PVCs automatically; the nft guard removes only its own
table after the frontend stops; API policies/peer revocation — by the exact
created IDs.
