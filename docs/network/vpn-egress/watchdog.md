# VPN watchdog: ownership, recovery and operations

Use this runbook for the production client path **client → Moscow relay (`socrat-4`) → NL backend (`socrat-2`) → internet**. Each node can serve its part from Kubernetes or from native systemd units. The two nodes need not be in the same mode. A timer starts a short-lived controller; it is not an in-cluster operator. The design prioritizes keeping a working VPN owner over making a Kubernetes dashboard green.

## Hosts and trust boundaries

| Host | Role | What failure means |
|---|---|---|
| `socrat-2` | K3s server/etcd voter; `x-ui` and `traefik-edge`, or native 3x-ui and Caddy | Losing the backend breaks the public tunnel. Fencing K3s stops other pods on this VPS and removes its etcd vote. |
| `socrat-4` | K3s worker; production `vpn-transit` relay, or native Xray relay | Losing the frontend breaks client access even when NL is healthy. The rehearsal pod is not a production owner. DNS and management relays are separate and must not be restarted as part of VPN recovery. |
| `socrat-0` | Optional external client, not a user-traffic hop | An unreachable client cannot confirm health; this alone is not evidence to stop a working VPN. The host has separate cluster/quorum responsibilities. |
| `socrat-1` | Required shared coordinator for coordinated **returns**; separate from the external client | A busy or unavailable coordinator defers return. Existing traffic does not traverse it. Do not create a second independent lock. |

With voters 0/1/2, two votes are required. If `socrat-2` is native and either home voter is down, native VPN may still serve while Kubernetes cannot make progress. See [K3s HA](../../platform/kubernetes/k3s-ha.md). A healthy API is neither a tunnel test nor proof of datastore recovery.

## From Kubernetes to native service

**Backend.** After boot grace (default 180 s), four consecutive *fencing-eligible* samples and two confirmation checks are required by default. Eligibility requires all of: failure of the workload TCP port (default 32087), failure of the local TLS/WebSocket probe, inactive/failed K3s, and no surviving Kubernetes Xray/x-ui process detected. A TLS timeout alone is recorded but does not count. An active or starting K3s is allowed to repair its pod; a hung but nominally active service can therefore require operator diagnosis. The controller checks recovery assets and the database, persists the native latch, fences K3s and its residual workloads, then starts native 3x-ui and Caddy. Both modes use the same live database: never allow two writers.

**Moscow relay.** After four failed data-path samples the controller tests the upstream path directly from Moscow over the mesh. If upstream or the mesh path also fails, it records the diagnosis rather than fencing the worker. If upstream is healthy and the local path is not, it can stop the worker agent, terminate verified production relay processes, check that the public TCP/UDP ports are free, and start the native relay. Unknown port ownership blocks activation. API loss alone does not qualify. The external witness and shared return lock are not prerequisites for emergency local activation.

## From native service back to Kubernetes

1. **Wait, while serving.** Warm return is opt-in. Healthy native fallback must pass a 30-minute cooldown. On NL the window is tied to the boot and active-marker generation; a deferred preflight may be checked again by the next tick after expiry. Moscow records a retry time before attempting, so a deferred automatic attempt waits another window. `native-primary` on Moscow is an explicit operator mode, not ordinary fallback.
2. **Obtain exclusive ownership of the transition.** Both controllers use a dedicated SSH key with a forced command on `socrat-1`. The coordinator takes a local `flock`, creates and fsyncs `transition.claim`, and only then acknowledges `LOCKED`. Explicit `COMMIT` or `ABORT` releases the durable claim. EOF, crash or an ambiguous disconnect does not. This serializes coordinated returns; it is not a distributed lock around every local health probe or emergency activation.
3. **Prepare without stopping native traffic.** Check load (one-minute load no higher than CPU count), free disk (at least 2 GiB) and available memory (NL 512 MiB, Moscow 256 MiB). NL checks the API and guarded workload specs, starts K3s, waits for node readiness and guarded containers. Moscow checks the upstream path, starts the worker under its same-boot warm-up exception, and verifies the waiting process against the installed relay-gate executable. Catching up etcd can take minutes. A pod can look ready because a host-network probe sees the native listener: readiness alone is not acceptance.
4. **Transfer.** Stop native services, verify release, then publish the local permit. On NL it admits the image entrypoints of 3x-ui and Traefik. On Moscow the gate execs Xray in the serving container. Verify local data path and external confirmation when available. Native units must no longer own the ports. Persist acceptance and release the coordinator claim. If acceptance fails, withdraw permission, fence the cluster runtime and recover native ownership. Do not manually start a second writer to speed this up.

This is **not** live session migration. A client may need to reconnect. Neither a two-second outage bound nor end-to-end UDP acceptance follows from a successful fresh Trojan connection. Probe deadlines are not downtime guarantees.

## Optional external validation

`socrat-0` uses a dedicated 3x-ui identity, `socrat-0-watchdog-trojan`, in group `Socrat`. The forced-command witness starts a private Xray client and requests HTTPS through the public Trojan/TLS/WebSocket tunnel. The deployment used a 90-day expiry and 1 GiB quota: monitor both and renew the technical identity before exhaustion. Never substitute a human subscription. SSH authentication for invoking the witness is separate from its VPN credential and from the coordinator keys.

A successful invocation is extra evidence. A missing probe executable or SSH transport exit 255 is recorded as unavailable, not interpreted as a failed VPN tunnel. A reachable witness reporting tunnel failure rejects acceptance. Other errors (including timeouts) are not blanket-ignored. Check SSH identity, certificate validity, client expiry/quota, public ingress and the HTTPS destination before blaming one node. The public test traverses both nodes and cannot by itself localize a fault.

## Read-only inspection

Run the matching commands on each host; use the explicit Kubernetes context from an operator workstation:

```sh
# socrat-2
sudo homelab-watchdog server status
systemctl is-active k3s homelab-vpn-primary homelab-vpn-caddy
systemctl list-timers homelab-vpn-watchdog.timer
journalctl -u homelab-vpn-watchdog.service -n 30 --no-pager

# socrat-4
sudo homelab-watchdog relay status
systemctl is-active k3s-agent homelab-vpn-transit-native
systemctl list-timers homelab-vpn-transit-watchdog.timer
journalctl -u homelab-vpn-transit-watchdog.service -n 30 --no-pager

# Either controller: fresh, authenticated data-path check; exit 0 means success.
sudo /usr/local/sbin/homelab-vpn-external-probe

# Operator workstation
kubectl --context Socrat get nodes socrat-2 socrat-4
kubectl --context Socrat -n x-ui get pods -o wide
kubectl --context Socrat -n traefik-edge get pods -o wide
kubectl --context Socrat -n vpn-transit get pods -o wide
```

A oneshot service normally becomes inactive after success: inspect `systemctl show UNIT.service -p Result` and the **timer**, not just whether the oneshot is running. `tick`, `activate`, `failback` and starting the watchdog oneshot are **not** read-only checks.

| Evidence | Backend (`socrat-2`) | Moscow (`socrat-4`) |
|---|---|---|
| Configuration | `/etc/homelab-vpn-failover/config.json` | `/etc/homelab-vpn-transit/failover.json` |
| Local state | `/var/lib/homelab-vpn-failover/`: `active`, `warming`, `return-window.json`, `last_failure.json` | `/var/lib/homelab-vpn-transit/relay-failover/`: `state.json`, `fallback.active`, timestamped receipts |
| Cluster permission | `/var/lib/homelab-vpn-owner/cluster` | `/var/lib/homelab-vpn-transit/port-owner/cluster` |
| Restart scope | `k3s.service` on the VPS; not a worker-only agent | `k3s-agent.service` on Moscow; not the DNS or management units |

## When recovery does not finish

- **Working native service, node NotReady:** first verify the tunnel, then the latch, cooldown, resources, upstream/API, guarded pod spec and coordinator. Do not reboot or delete the latch just to clear NotReady.
- **Persistent claim on `socrat-1`:** `/var/lib/homelab-vpn-witness/transition.claim` is a safety hold, not a stale PID file. Identify the owner and inspect **both** nodes' timers, running transactions, markers, actual listeners, serving runtime and tunnel. Exclude any in-flight transfer and collect receipts before operator reconciliation. Never automate claim deletion by age or switch to the obsolete EOF-only protocol.
- **Interrupted warm-up:** preserve the serving path. Check the local transaction state and watchdog journal before retrying. If the pod, native service and port evidence disagree, stop making ownership changes. Preserve the database, backups, WG routes and operator access.
- **Maintenance:** stop only the relevant timer and wait for its in-flight service/transaction to finish; stopping a timer does not cancel an executing oneshot. Restore that timer after maintenance. The backend `inhibit` marker is not a general two-node maintenance lock. The backend's legacy manual `failback` stops native services **before** starting K3s; it is not a shortcut to exercise the coordinated warm return.

## Source, installation and acceptance

The canonical standalone distribution is [tools/watchdog](../../../tools/watchdog/README.md): `runtime/server.py`, `relay.py`, `witness.py`, `coordinator.py`, the SSH wrapper, Go relay gate and systemd drop-ins. Follow its detached install/test instructions. No checkout or Ansible is needed to execute the installed CLI. `make install` alone does not provision keys, VPN assets, gates, timer policy or host configuration. Do not run two schedulers. Ansible compatibility paths are not independent implementations. Check effective units with `systemctl cat` and the installed entrypoint with `readlink -f /usr/local/bin/homelab-watchdog`; a Git merge is not a live upgrade.

For a planned change: preserve configs and state privately; verify a single owner and a baseline tunnel; test both controllers and the detached CLI; roll out compatible coordinator/clients together; verify actual gated workloads before enabling automated returns. After handoff require the expected mode, correct single owner, working timer, released global claim and fresh end-to-end tunnel. See [backend recovery assets and historical evidence](vpn-failover.md), [Moscow incident](../../records/incidents/moscow-relay-recovery-20261112.md) and [transport topology](vpn-hardening.md). Historical live transitions demonstrated new connections in each mode, not continuity of existing sessions, automatic timing under all faults or full-site disaster recovery.
