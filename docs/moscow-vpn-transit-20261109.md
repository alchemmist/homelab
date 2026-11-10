> **Production update:** this document retains historical staging evidence.

> Transport/runtime superseded10Nov: [accepted shared mesh + Pod/native](vpn-mesh-runtime-20261110.md).
> This dated document preserves the earlier cutover evidence, not current commands to replay.
> DNS/Hosts and known HOME flows were subsequently switched; current acceptance
> and resolved shared443/watchdog incident are in
> [production cutover](vpn-production-cutover-20261109.md). Do not replay staging.

# Moscow transit: 2026-11-09 accepted stage, not production cutover

## Authorized scope and safety boundary

Owner authorized `socrat-4` at `91.189.82.238`, constrained worker enrollment,
standard owner SSH/shell/welcome, telemetry, and eventual production VPN transit
Moscow → Netherlands while preserving `vpn.alchemmist.xyz`, original clients and
security settings. No further plan approval is needed. Mac Tunnelblick/WireGuard,
DNS and routes remain frozen. No subagents, reset, data deletion or cluster-wide
restart. Existing Netherlands ingress is intentionally retained at this stage.

New VPS SSH uses explicitly authorized **TOFU**, then dedicated pinned strict
checking: ED25519 `SHA256:sklLNdKO9fv4LvCOOt2hhJaqlRG11WKlJL48qzbSp/U`.
This was not independently console-verified; no console confirmation is required.
A changed key must stop. Existing nodes' pins were recovered through trusted
historical records/authenticated cluster access, not justified by repeated scans.

## Accepted live state

- Debian 13.7 x86_64, ~967 MiB RAM, 511 MiB swap, 15 GB disk.
- Standard `alchemmist` owner, zsh/starship, existing standard owner password hash
  and public keys securely copied from the protected existing baseline. Provider
  password was not reused. Port **2222**, independent key login and sudo verified
  before locking the bootstrap account password. Port 22 remains; no lockout claim.
- Standard SSH welcome installed after Rancher/Kubernetes metadata became available.
- Mesh **10.250.0.40**, not revoked assistant `.6` or historical restricted admin
  ACL `.8`. Initial new-peer `.8` conflicted with an old restricted-client ACL;
  only this newly owned peer was moved to `.40`. Historical ACL was preserved.
- New node is **agent only**, no control-plane/etcd, ServiceLB disabled. Effective
  allocatable CPU `800m`, memory `335196Ki`; system/kube reserves 256 MiB each,
  eviction threshold 128 MiB; swap retained. Bootstrap NoSchedule taint remains:
  ordinary workloads are **not admitted**. No storage/desktop/Syncthing rollout.
- Fresh final check: all **five Ready**, all MemoryPressure=False. Existing three
  etcd voters were not changed. K3s visibility is not a separate Rancher UI test.
- Native Collector and loopback-only node exporter installed from hash-verified
  existing stock executables, streamed via strict SSH/SFTP to avoid buffering the
  420 MB Collector through privileged Ansible slurp on small hosts.
- Only new leaf/SA/Role/RoleBinding created; cert-manager CA/old leaves untouched.
  Token self-renewal and denied CA-key access verified. Native queues/fsync retained.
- Grafana/Thanos returned fresh `node_uname_info{instance="10.250.0.40:9100"}` with
  `node=nodename=socrat-4`. Count-only mTLS Loki query found **104** new-host records
  in the last five minutes; no log bodies fetched.

## Native protected data path

Host-level `homelab-vpn-transit.service` does not depend on Kubernetes availability.
Exact running Netherlands Xray copied and hash-verified:
`a27e3f95ab6ce270956d0cecd32eda4686a811afc71c64a6a734a3dede14883e`,
version 26.10.21. Native `run -test` accepted committed configuration before start.

Separate `wg-vpn-transit`, UDP 51841, Moscow `10.251.4.1/30`, Netherlands
`10.251.4.2/30`; peer AllowedIPs only the other `/32`, no default route, MTU1420.
Both directions pinged successfully. Original `wg-socrat` was not restarted.
The Tunnel protocol is forwarding, **not encryption**: VPN relay targets use this
separate encrypted link. No direct-public-Netherlands fallback is configured for
VPN endpoints. Two separately tagged fixed management relays carry already
end-to-end encrypted WireGuard (UDP51832→NL51830; TCP51840→NL51840); HOME has
**not yet been switched** to them.

Proxy exposes only committed fixed ports; disabled32063 and protected
12096/18082/32087 are not opened. No second panel/client database on Moscow.
DynamicUser, bind capability only, memory maximum192 MiB; no privileged container.

## Actual authenticated functional acceptance

HOME Linux `socrat-0`, real HOME source109.173.40.247, explicit entry
**91.189.82.238**, not mobile/Happ interactive proof. Owned, expiring fixture only;
no human identity used. Per-process loopback SOCKS clients, unchanged host routes,
DNS and OS proxy. For each of **REALITY, Trojan, WireGuard (UDP)**:

- authenticated request returned HTTP200 and **65536 bytes**;
- body SHA256 `34dd6758c2908cf5be0e411173f61877f8faf2dcdcfed135b5a5fa90577447bc`;
- independent HTTPS request through that tunnel returned Netherlands IPv4
  **109.120.141.60**;
- original fixture identity/bindings and all temporary native API tokens removed;
  complete original configuration and original token preservation checked.

First TCP-only receipt had an old hardcoded endpoint metadata field; the probe
source was corrected and the later **three-protocol run** emitted the actual Moscow
endpoint and egress checks. Retain old receipt as historical evidence, not as a
correct endpoint description. An initial UDP preparation stopped before client
creation (server had no `address` list); verified cleanup removed only owned tokens.
An initial egress check was rejected by the deliberately restrictive synthetic
client domain allowlist; only test-client configuration was corrected, then a new
local test directory was used. No production server routing was relaxed.

## Explicitly not completed

**DNS, native Hosts addresses, subscription publication and HOME→NL routes have
not been switched. Production VPN migration is not complete.** No claim that all
HOME traffic already transits Moscow. In particular management WireGuard/GOST,
DNS/monitoring/probes and other relevant HOME→109.120.141.60 connections must be
inventoried and moved, not merely client endpoints.

Next authorized work:

1. Stage protected HOME→Moscow fixed-destination gateway with tests before routing
   production; retain a persistent fail-closed fence when its interface is down.
   Do not rewrite default routes or change Mac routes. Preserve management keys;
   use the dedicated management relays to avoid nested-WireGuard MTU overhead.
2. Verify remaining protocols/AmneziaWG, MTU/large UDP, return path, bounded memory
   and failure/no-hidden-direct-fallback behavior. Current WG transfer is real UDP
   proof, not an exhaustive datagram-size/fragmentation or all-protocol acceptance.
3. Fresh native online panel backup and identity projection; native Hosts API
   preimage/CAS migration to Moscow, preserving SNI/TLS, disabled bindings and all
   original identities. Validate URI/JSON for all current identities, including
   legitimate concurrent additions. Keep subscription URL/domain unchanged.
4. Switch only the VPN DNS record after the path/subscription-web tests. Preserve
   ns1 HOME and ns2 accepted glue; no registrar resubmission or blind health-writer
   deployment. Both authoritative writers must agree on the intended VPN record.
5. Close only direct Netherlands VPN paths after acceptance. Port443 is shared
   with ordinary public HTTPS: **no blanket443 drop**. Use scoped TCP/HTTP route
   allowlists as needed; preserve backend12096/32087 protection and existing apps.
6. Fresh Rancher native/UI, telemetry, client-preservation and data-path checks;
   publish honest limits (mobile/Happ, blocking/HA/DR remain separately unproven).

## Private evidence and replay rules

Controller state: `~/Library/Application Support/homelab/socrat4-transit-20261109/`,
0700/0600. `phase-state-private.json` supersedes old console-blocker state.
`moscow-udp-probe/home-proof.json` is the corrected three-protocol acceptance.
No fixture configs/binary retained in that controller probe directory after cleanup.
Verified stock artifacts remain in its protected artifact directory.

Native state includes `/var/lib/homelab-recovery/20261109-socrat4-bootstrap`,
`20261109-socrat4-peer*`, `20261109-socrat4-telemetry`, plus panel native-session
receipts under `/var/lib/homelab-vpn-hardening/vpn83-moscow-*`.
Do not replay session preparation or temporary token issuance in an existing state
path. Inspect preimages/uncertain markers first. New infrastructure private keys
remain root-only `/etc/wireguard/*.key`; committed vars contain **public keys only**.
HOME gateway keys are staged but unused; no production HOME route change yet.

Scoped runner uses dedicated pinned inventory overrides; do not replace global
known_hosts or rely on a default runner with stale pins. A short initial sudo
prompt timeout occurred before transport config writes; after inspecting that
failure, a 45s privilege/connection timeout succeeded. No alternate CLI fallback.

Scoped accepted-stage native backups were also fetched off-host into protected
controller `evidence/` and independently source-SHA verified: NL transport-only
10240B (`2e2aa7f15fb572b538b2718f66cb07342209596f2b3788c6684aa4f41405f557`),
Moscow owner/SSH/mesh/worker/proxy configuration645120B
(`a16169b1a7317a6d46e0c3ffd82eb87768b5785b9ea9235ccb9c01de77d43249`).
These private archives are not in Git and are not a full isolated restore test.
Scoped validation: **68 tests plus12 subtests passed**, including fixed-target
proxy/backend protection, no management default route, worker taint and public-only
infrastructure key inventory contracts.
