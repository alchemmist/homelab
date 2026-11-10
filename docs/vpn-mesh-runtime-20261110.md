# Moscow relay: mesh reuse and Pod/native lifecycle

## Historical preparation — completed; final acceptance below

Authorized target: retain native management relays (51832 UDP/51840 TCP), run
user VPN relay as a single hostNetwork Pod on socrat-4 with independent fenced
native fallback, reuse wg-socrat .40↔.2 instead of wg-vpn-transit.
Subscriptions, users and keys stay unchanged. Mac networking untouched.

Preflight actual .40↔.2 endpoints are public91.189.82.238:51830 ↔
109.120.141.60:51830, routes direct wg-socrat, not via the management proxy.
No recursive dependency for user relay. Management relay stays native/public
outer encrypted WG/GOST; do not move it into the Pod.

Preparation chart replicas=0. Transitional Trojan allowlist permits both old
private.1 and new mesh.40 plus exact loopback health. New scratch image is built
offline from existing independently pinned static Xray binary, no registry needed
for boot/fallback. Image and native process share exact binary SHA; public
user.json hostPath is read-only and shared by both execution modes, no secrets.

Local watchdog uses real verified TLS/WS to NL. API loss alone never stops a
working relay. Four consecutive data-path failures trigger sticky native mode:
fsynced fallback marker → fence worker agent → terminate only verified owned
relay PID/cgroup/starttime → refuse unknown port owners → native start.
Agent ExecCondition blocks Pod restart in fallback. Explicit failback stops native
before releasing fence; on bounded Pod recovery failure it restores native mode.
Only socrat-4 worker agent can be stopped, no control-plane unit or etcd mutation.

NL already has dnsmasq on mesh:53; private authoritative Knot must use mesh:5354.
Do not steal dnsmasq's socket or restart the mesh. Old channel only retired after
native+Pod+fallback actual data/DNS/management proofs; receipts private0700/0600.

At preparation time pending: native provisioning, controlled handoff and actual acceptance, then
remove transitional .1, stop/archive dedicated interface and update current wiki.

## Final accepted state (supersedes preparation above)

- Normal mode: Argo-owned `vpn-transit/vpn-transit` Deployment, one hostNetwork
  Pod pinned to socrat-4, Recreate, explicit bootstrap-taint toleration. Worker
  taint retained; no cluster role/API token, no NET_ADMIN, read-only scratch FS,
  only NET_BIND_SERVICE. Static Go execution under this CRI dropped non-root bind
  capability; actual permission-denied startup diagnosed before changing to UID0
  with this constrained capability set (not a privileged container).
- Offline scratch image contains exact original Xray26.10.21 binary SHA
  a27e3f95ab6ce270956d0cecd32eda4686a811afc71c64a6a734a3dede14883e.
  `imagePullPolicy: Never`, pre-imported on the fixed node. Registry or control
  plane are not required to start native recovery. Image builder is deterministic.
- User relay uses existing wg-socrat10.250.0.40→10.250.0.2, explicit sendThrough.40.
  Management UDP51832/TCP51840 remain in separate native
  `homelab-vpn-management-relay.service`, with **public** outbound source, not.40.
  DNS native relay remains independent: .40:53→.2:5354 TCP/UDP. Existing dnsmasq.2:53
  preserved. Exact machine.40 exemption from old private-web443 DNAT; human ACLs,
  admin peers, TLS/SSO and public firewall unchanged.
- Real enabled `homelab-vpn-transit-watchdog.timer` recovered automatically after
  **actual local worker-agent stop plus exact owned relay PID termination**.
  No manual `tick`/`activate`, no control-plane stop or alert masking. Timer
  detected data-path loss, fenced worker, activated native; then explicit
  bounded failback returned healthy Pod. Native mode sticky, not automatic flapping.
  API loss alone while a working Pod forwards traffic does not trigger failover.
- Actual fixed-HOME authenticated REALITY, Trojan, VLESS32083/32084 and WireGuard
  each passed200/65536B/expected SHA and independent NL exit IP in native mode,
  accepted Pod mode, actual automatic fallback, and final Pod **after channel
  retirement**. The receipt named `home-pod-proof` from the first unsuccessful
  Pod attempt actually tested restored native mode: it is not Pod acceptance;
  `home-pod-accepted-proof` is the later genuine Pod proof.
- Dedicated wg-vpn-transit stopped/disabled on both nodes; old configs/keys and
  combined service archived root-private, interfaces absent. No wg-socrat
  restart/key rotation, no default route or Mac change. Old provisioning role
  and combined proxy play refuse invocation; transport play now only verifies mesh.
- Shared443 gate: only .40/32 and exact127.0.0.1/32, no old.1 range. Actual mesh101/
  public403 even spoofedXFF; NL native Caddy gate validated without forcing NL
  fallback. Other HTTPS and original watchdog checks retained.

### Resolved implementation failures (not a seamless operation)

Initial diagnostic `kdig` missing after successful Knot change: inspected actual
state and used native DNS wire queries, did not replay writes. Xray rejects
extensionless candidate filenames even with explicit format; stopped before live
writes, validated a `.json` candidate after exact preimage checks.

Initial handoff's bind-only TCP test confused TIME_WAIT with live ownership,
leaving user relay stopped until scoped fix/resume; management process remained running; the source-IP defect below still caused a
temporary management outage.
TCP guard now uses SO_REUSEADDR+listen, UDP never reuses; Linux-native live-owner
rejection and released-port acceptance verified. Shared shallow-copy outbound
initially pinned management to private.40; diagnosed temporary NL API unavailable,
removed pin from management only. Public-source handshakes/API recovered without
K3s restart, etcd reset/member replacement or new trust. Added regression invariant.
First Pod low-port permission error produced automatic failback rollback to native;
corrected capability execution context, then accepted Pod independently. All failed
attempt receipts retained privately; no uncertain write blind replay.

### Final acceptance / custody

3 original healthy voters/common leader, hashKV equal at revision17514049;
5Ready/noMemoryPressure; NL watchdog kubernetes/healthy/uninhibited, Moscow
watchdog kubernetes/healthy/native inactive/marker absent.17 identities/91 bindings,
32063 disabled.17 normal-DNS strict-TLS subscriptions URI84/JSON77 match backend,
old endpoint absent. Temporary fixtures/tokens removed, originals/proxy preserved.
Real shared-mesh default UDP sockets exact echo32/1200/1420/1472/8192B; no MTU,
PMTU/sysctl tuning. Authoritative DNS SOA accepted over UDP/TCP at NL public53,
NL mesh5354, Moscow mesh53. Echo bounded45s/5 packets, exited.

134 tests+14 subtests passed; Helm renders succeeded. Prior five-node backups
untouched. Final node2 archive1218560B SHA25616e473e3…6ec35 and node4 archive133120B
SHA256c9db295b…548a independently source-SHA verified off-host; root-private online
panel backup quick_check OK. No isolated DR restore/full physical reboot/complete
cluster outage proof; no mobile/Happ or authenticated AWG acceptance or HA guarantee.

## Operations / ownership

Git→Argo owns Pod desired state; Ansible owns native units, offline image and shared
`/etc/homelab-vpn-transit/user.json` (read-only single-file hostPath in Pod).
Changing that file is **not** an automatic reload of a running process or existing
file bind mount. Validate candidate/preimage/CAS and perform controlled handoff/
container recreation; verify shared effective config and actual client data after.
Initial `vpn-transit-mesh-runtime.yml` is guarded preparation, not a blind update
or recovery replay. User accounts/subscriptions stay in existing NL panel/API.

Read-only status on Moscow (sudo required):

```sh
sudo python3 /usr/local/libexec/vpn-transit-failover.py status
sudo systemctl status homelab-vpn-management-relay homelab-vpn-transit-watchdog.timer
```

`activate`/`failback` are production-changing, lock/CAS/receipt-sensitive operations,
not health checks; do not execute simply because an old runbook contains them.
The image archive can be reproduced from the verified static binary; do not replace
it with an unpinned registry image or remove the independent native management path.
