# socrat-2: VPN watchdog fencing and controlled recovery, 2026-11-07

## Findings and evidence scope

Times below are MSK (UTC+03); persistent journal export uses UTC. socrat-2 stayed
SSH-reachable but Kubernetes reported NotReady. k3s exited 0/SUCCESS after an
explicit systemd stop, not a demonstrated crash. Current memory/disk availability
was not evidence of conditions before the event.

- 20:01:52: last healthy Kubernetes-mode watchdog check.
- 20:02:22, 20:02:54, 20:03:24: three consecutive failed public TLS/WebSocket probes.
  No TCP-listener failures were reported by these checks.
- 20:03:56: fourth failure entered `activate()`, persisted the active latch,
  stopped k3s and fenced its remaining processes. Both the journal sequence and
  installed source identify `homelab-vpn-watchdog`, not a guessed operator action.
- Native fallback initially failed the same generic WebSocket check and restarted
  its services; later checks became healthy. Native startup checks also briefly
  reported missing listeners. These do not prove that the initial Kubernetes
  failure had the same cause as fallback warm-up.
- No automatic failback exists by design. The persistent active latch therefore
  kept Kubernetes off after native VPN became healthy.

## What cannot be reconstructed

The original helper collapsed OSError/ValueError into one generic message,
without phase, exception class, TLS verification code or HTTP status. Exact cause
of the original handshake failures **is not established**. Timeout, certificate
verification, rejected upgrade or transient resource/network failures must not be
presented as proven. Four real probe failures do not prove every VPN path was
broken, nor prove a false positive.

Original x-ui log contained no restart/error at the incident time; retained
Traefik logs ended before the event and did not provide per-request evidence.
The checked kernel journal interval did not show OOM/I/O-error signatures.
The Kubernetes leaf certificate is valid 2026-10-14 through 2027-01-12: expiration
of that leaf is not supported by evidence. This alone does not prove the complete
certificate chain actually served at the incident time. etcd logged slow applies
before the event (including about 3.2 seconds), but causation of the probe failures
was not demonstrated. The 3-second probe timeout alone is not a diagnosis.

## Confirmed additional recovery defects

1. Live config dated 2026-10-24 still selected `k3s-agent.service`, despite the
   current etcd-server role. Inventory already selects `k3s.service`; this was live
   configuration drift. Fixed only `agent_unit`, retaining other config values.
2. The helper gave all systemctl commands 40 seconds. First controlled failback
   started the server, waited for etcd/API registration, then hit that deadline;
   exception handling fenced it again. A second attempt with a dedicated
   180-second Kubernetes-start deadline completed successfully. Other operations
   keep their 40-second deadline; failure thresholds and TLS verification were
   **not weakened**. The server unit itself has an unlimited systemd start timeout.
3. The first incident orchestration's rollback module loader could not import an
   extensionless helper. The enabled watchdog recovered native VPN; the retry
   used `runpy.run_path` and retained explicit rollback. This orchestration bug was
   not the original incident and is not hidden as a successful first attempt.

## Applied repair and acceptance

Before switching, saved root-private config/helper/state/journal receipts and an
SQLite backup using the backup API plus read-only quick_check. No DB was reset,
restored or edited. Prepared automatic fenced native rollback; paused only the
watchdog timer during cutover and restored it afterward. Used existing Docker
administrative access for short-lived diagnostics and systemd control; diagnostic
containers were `--rm`, unprivileged/cap-drop, with scoped mounts. No debug pod,
permanent debug daemon or API credential was installed.

- Live agent target is `k3s.service`.
- Added sanitized failure diagnostics: probe phase, exception class, numeric HTTP
  status/TLS verification code/errno where available. No exception text, private
  WebSocket paths, response bodies, passwords or share URLs are logged.
- All four nodes returned Ready. New x-ui and Traefik Pods are 1/1 Running on
  socrat-2; original Pods were replaced after fencing, not claimed unchanged.
- k3s active, native primary/Caddy inactive, watchdog timer active.
- Watchdog Kubernetes-mode probe healthy; an authenticated public Trojan
  TLS/WebSocket connection successfully fetched HTTPS200 from example.com.
- Six successive post-grace watchdog checks reported Kubernetes mode, healthy,
  failures0; all inspected current Pods on socrat-2 were 1/1 Running.
- Focused regression: 54 tests +2 subtests; current public-entry checker82/82.
  These are this checkout's current checks, not a rerun of the old134-check suite.
- API readiness reports etcd healthy. No etcd member deletion, reset, restore or
  blanket workload sync/prune was used.

Private host receipts: `/var/lib/homelab-vpn-failover/incidents/2026-11-07/`.
Additional local receipts: `/tmp/vpn-incident-private/`. Never commit or print
these files; a local SQLite receipt is not an off-node disaster-recovery backup.
A successful Trojan/HTTPS check is not acceptance of every TCP/UDP VPN profile.

## References and follow-up

- [systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html):
  restart policy does not override an explicit service-stop operation.
- [K3s embedded etcd HA](https://docs.k3s.io/datastore/ha-embedded): quorum and
  embedded-datastore requirements; slow storage can affect etcd, but was not
  established as this event's root cause.
- [Local failover protocol](vpn-failover.md): native fencing and manual failback.

Observe new diagnostics before changing automatic fencing policy. A design review
of whether a single public-route probe should fence the whole VPS is warranted,
but silently suppressing the alert or disabling recovery is not this repair.
