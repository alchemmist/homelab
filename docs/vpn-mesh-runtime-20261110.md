# Moscow relay: mesh reuse and Pod/native lifecycle

## Implementation phase — preparation, NOT final acceptance

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

Pending: native provisioning, controlled handoff and actual acceptance, then
remove transitional .1, stop/archive dedicated interface and update current wiki.
