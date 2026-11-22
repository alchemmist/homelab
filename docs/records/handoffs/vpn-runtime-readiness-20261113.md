# Fixed Moscow→NL VPN: native standby readiness and composite monitoring

## Owner-approved boundary

Only client→Moscow4→NL remains the user path. HOME ingress, direct client→NL and
node5 user-data fallback are abandoned. Node5 may still be used as an existing
strictly pinned administrative access path; no new user relay is deployed there.
Moscow MUST retain Kubernetes worker membership. Native fallback can temporarily
fence/stop its worker, but must not retire/delete it. Return remains explicit,
not automatic on the first recovered API check. Deliberate outage tests need a
separate window; this change does not authorize stopping HOME voters.

## Audit and stale standby correction

`vpn-runtime-observer.yml` initially audited both hosts without recovery actions:

- Moscow relay binary/config valid, mesh route .40→.2 direct wg-socrat, native and
  worker inverse boot fences, actual watchdog active/enabled.
- NL server identity k3s.service correct; both server and retained agent fenced;
  native primary/Caddy units guarded; watchdog active/enabled/uninhibited;
  required files and live SQLite quick_check valid; native Caddy config valid.
- Both hosts use provider resolver IPs, not Kubernetes DNS. Native exporters and
  OTel agents are active; source configs use127.0.0.1:19100. NL intentionally keeps
  its original frozen exporter alias10.250.0.2:9100/old pod metadata without a node
  label. Such labels do NOT imply the process is a Kubernetes exporter.

A real readiness defect was found: retained NL primary image marker ended
6c7e73c5…c89c2ec1, but current Kubernetes/source image is
`ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b`.
Audit correctly refused installation rather than silently accepting the mismatch.

`vpn-native-image-refresh.yml` staged the already-cached current image into
`/opt/homelab-vpn-failover/staged-20261113/primary`. No registry pull or active
workload replacement. An extended isolated smoke copied live SQLite via read-only
online backup plus cert/ACME/runtime files, then ran native primary and Caddy in
a separate network namespace. Local strict TLS/WebSocket/listener health passed;
transient units, namespace and private DB/cert copies were removed before writing
cleanup-verified acceptance. This is NOT authenticated VPN/UDP/full-host recovery.

Promotion required fresh accepted smoke, exact UI SHA and candidate Xray core
matching the one live running core. Under the existing watchdog lock, with latch
absent, server active, native units inactive and current health positive, an
atomic renameat2 directory exchange replaced ONLY dormant image contents. The
old image remains at staged-20261113/primary; production units/DB paths/guards and
working Pod did not change. Private intent/acceptance prevents blind replay.
Current NL Pod remains x-ui-79787488f4-fzxdb, ready, restarts0; k3s.service has
NRestarts0 and ActiveEnter10November. No live DB migration/restore, user/token
mutation, control-plane stop, firewall flush, certificate gate change or service
restart was requested by this maintenance. Later source hardens receipt-directory
fsync; never replay the completed promotion to apply that source-only hardening.

Future image updates must refresh the standby through a new reviewed stage and
receipt; do not overwrite the retained directory or replay this dated migration.

## Native observation and VPN mode

New standalone observers on2/4 only read runtime state and publish numeric
`vpn-runtime.prom` via existing native exporter→sole OTel scraper→Thanos. No API
credential, private WS path, per-account content, extra listener or new scrape
owner. Services have96MiB memory bound, low CPU weight, hardened read-only host
view, only metrics directory writable. They NEVER call tick/activate/failback.
Moscow periodic observation reuses the real watchdog's atomically persisted
health+file timestamp; it does NOT add another TLS handshake/controller lock to
the constrained host. Unit states are obtained in one call. Explicit audit can
still perform a fresh transport check.

Panel9 now requires both exact exporter aliases and component identities:

| Display | Meaning |
|---|---|
| K3S green | Both actual runtimes Kubernetes; both component transport checks pass |
| OS amber | At least one actual component is native; inspect component checks |
| K3S amber | Kubernetes execution, but a component check failed; not proven total OFF |
| OFF red | A required fixed-path component positively has no TCP data listeners/established sessions AND no UDP data sockets |
| NO DATA grey | Missing/stale/error/inconsistent component observations |

Metric samples alone cannot make an old cached health result fresh: both wall-time
observation value and scrape timestamps are gated, including limited clock skew.
Stale OFF cannot override current healthy data. A details link opens native
Grafana Explore with per-component runtime/check/off/observation/freshness values.
No TV geometry/style/scale/auth or alert thresholds changed. These are runtime and
transport checks, NOT proof of authenticated VPN or all protocols/global reachability.
OFF detection is conservative; live sockets with an unproven path failure produce
amber, not fabricated total failure or green.

## Unplanned automatic Moscow transition during this operation

At08:37:17UTC the EXISTING Moscow watchdog fenced/stopped its agent after its four
consecutive actual data-path failures; native relay became active08:37:18. No
operator command stopped the production agent, activated this fallback or removed
the Node. This was NOT the planned outage test and is NOT presented as formal
acceptance. Current local transport health subsequently recovered.

NL briefly became NotReady, then recovered to Ready without service restart.
A bounded08:32–08:40 NL journal classification found lease/timeout messages;
Moscow's recent kernel check found no OOM match. The cause of the failed path
checks is NOT established; no claim that Kubernetes alone failed, provider CPU,
network loss, new observer load or any particular change caused/did not cause it.
Existing Moscow watchdog receipts lack per-failed-check diagnostics, limiting
retrospective localization. Its detection policy was NOT changed during this audit.

At final readback: Moscow observer runtime1/native, check1, off0; NL runtime0/K3S,
check1, off0. Actual composite query returns1/OS and Grafana model matches source.
Moscow Node object remains present but NotReady while its agent is fenced; other
five nodes are Ready. Native fallback is sticky by design. No unapproved manual
failback/restart was used to hide the event or turn cubes green.

## Validation and remaining window

77focused tests plus2subtests passed, including actual composite PromQL for both
K3S, either/both native, partial failure, conclusive OFF, missing/error/conflict,
stale/future observations and stale duplicate labels. Ansible syntax and Helm
lint passed. Source published through8c9ee2ae (mode bbd74b51, cached observer
fd5f7d45). Physical TV visual acceptance requires reload; API model/query verified.

Remaining: agreed short window to return Moscow via locked failback, verify real
authenticated transfers, then separately test NL and both native together while
HOME0/1 quorum stays healthy. Do NOT equate isolated smoke or this unplanned
transition with a whole-cluster-loss/reboot/restore acceptance. Monitoring itself
still depends on its Kubernetes-hosted backends; native VPN must not depend on it.

Private receipts: host2/4 `/var/lib/homelab-recovery/20261113-vpn-runtime-monitor/`;
host2 `/var/lib/homelab-recovery/20261113-vpn-native-image/`; controller selected
artifacts retained in operator-private Application Support. Temporary escalation
file and fetched private Collector config removed; no credentials/log dumps
published in this evidence.
