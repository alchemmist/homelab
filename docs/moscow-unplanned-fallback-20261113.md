# Unplanned Moscow fallback13November: investigation and pending repair

## Status: source tested; NOT applied to hosts

Owner requested investigation and repair, not an intentional outage test. Do not
report the incident resolved until deployment, fenced worker return, authenticated
VPN checks and a stability observation have completed. Noninteractive sudo is
unavailable; previous temporary escalation files were deleted. No password value
is retained in current working context. Await an operator-provided private vars
file/path; do not recover credentials from logs or publish them.

## Confirmed observations

- Before08:37:17UTC activation, Moscow agent logged TCP timeouts to
  192.168.0.23:6443, including08:33:23 and08:35:40. These precede the native switch.
- NL logged lease/API timeouts and Raft pre-vote attempts. HOME0 reported TCP
  timeouts to NL10.250.0.2:2380. These prove a connectivity disturbance affecting
  multiple components, not global quorum loss: HOME0/1 leader metrics remained1
  and committed proposal rates stayed positive (~10–12/s) over the bounded period.
- Existing watchdog receipt records four data-path failures, not per-check stage
  details. The exact local TCP/TLS/WS failure that triggered activation cannot be
  reconstructed from that receipt. Do not claim a failed Pod or upstream alone.
-08:37:17 agent stopped;08:37:18 native relay active. NL server was not restarted;
  it recovered Ready. No controlled production failover was executed.
- At readback Moscow has NO host routes to the advertised HOME API addresses
  192.168.0.23/24: both route lookups go to public eth0/default gateway. Actual
  TCP connections to these two API addresses time out. Meanwhile10.250.0.1:6443
  and10.250.0.3:6443 succeed in~18–25ms. This uses actual sockets as well as route
  lookup, not the DNAT-invalid direct-IP inference corrected in earlier work.
- Existing NL has those LAN host routes over wg-socrat. Inventory already has
  explicit extra AllowedIPs for remote workers3/5, but not Moscow4. Worker-return
  preflight failed to test these advertised endpoint paths: a readiness omission
  in our restoration process, now addressed in source.
- CPU/memory minute samples do not demonstrate sustained CPU exhaustion or OOM:
  Moscow idle~50–72%, available RAM~332–418MB near the event; samples cannot
  exclude shorter spikes. Do not assert provider, power, probes, maintenance
  changes, rate blocking or resource pressure as the proven cause.

The route defect explains Moscow's advertised API endpoint timeouts. It does NOT
by itself prove the cause of every TLS failure or NL transport disturbance. That
part remains open; a retrospective upstream/local distinction is unavailable.

## Fixes prepared

1. `host_vars/socrat-4.yml`: exactly two extra /32 cryptokey routes, each assigned
   to its correct existing HOME WireGuard peer. No default route or whole LAN.
2. `moscow-api-routes-repair.py`: one-shot additive live/boot repair. Checks host,
   pinned public peer identities, full config/runtime AllowedIPs agreement,
   conflicting ownership, existing explicit routes/attempts and current WG API
   access. Preserves private-key and unrelated config lines, peers and routes;
   private before/intent/accepted custody; only two `wg set peer allowed-ips` plus
   `ip route add` operations. No wg-quick/interface/service restart, key changes,
   flush, endpoint rewrite or unknown-route replacement. Verifies actual TCP
   connections to both advertised API endpoints after repair. Partial failures
   require inspection; never blind replay.
3. Moscow watchdog: after four failures, distinguish a definitely absent local
   listener/inactive agent from a listening local path with unreachable upstream.
   With local listeners alive, strict direct NL TCP/TLS/WS check binds the existing
   Moscow WG source. Upstream/path failure defers agent stop; healthy direct NL
   with failed local relay permits existing fenced recovery. No automatic failback.
   No change to alert thresholds, certificate validation, ACLs or ownership guards.
4. Persist numeric failed stage/port/HTTP status/error class/errno plus timestamps
   without private WS path, user data or response body. Scope changes get bounded
   receipts; each tick updates current diagnostic state without a receipt flood.
5. A boot grace failure must persist healthy=false, not refresh an old green cached
   health observation. New boot also resets pre-reboot consecutive-failure count.

## Deployment and acceptance gate

`ansible/playbooks/moscow-watchdog-repair.yml` is scoped only to4:

- Default `preflight`: voter Nodes0/1/2 Ready, actual healthy native ownership,
  preserved kubelet identity/containerd DB, enabled worker/inverse boot fences,
  desired singleton relay, stage reviewed helpers and validate additive routes.
- Explicit confirmed `apply`: route repair; atomically replace only the exact old
  controller SHA81fa7062… under its existing lock while native owns ports. No
  production process restart. Unknown SHA, runtime conflict or prior attempt aborts.
- Separate explicit confirmed `return`: exact new controller SHA, actual TCP API
  reachability through correct WG routes, existing locked `failback` with native
  rollback on failure. No uninstall, re-enrollment, Node deletion or NL k3s stop.

Before execution re-check fresh HOME0/1 leadership/commits and actual component
health through existing read-only Grafana. After return verify all6Nodes Ready,
actual process ownership, no native marker/competing sockets, continuous API
connection stability, authenticated five-protocol transfers/checksum/NL exit and
mode freshness. Keep watchdog enabled; do not simply suppress warnings or clear
markers to manufacture green status.

148focused tests+2subtests and Ansible syntax passed. New tests cover upstream
failure never stopping a listening worker, direct-upstream-good local failure,
missing local listeners/inactive agent, boot health freshness, sanitized failure
stages, exact prefix addition and unchanged unrelated/private config lines,
conflicting cryptokey ownership, full AllowedIPs parsing, guarded atomic upgrade,
no mutation on SHA/runtime conflict and explicit separate return phase.

Private bounded Loki responses and actual API/route probes retained under
operator-private `vpn-unplanned-fallback-20261113/`. No raw private config, keys,
credentials or unreviewed logs are committed. At last readback both checks=1,
Moscow native/runtime1, NL K3S/runtime0, Moscow still fenced/NotReady. Source-only
fixes do not change that current operational state.
