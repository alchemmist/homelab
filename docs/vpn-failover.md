# Independent VPN recovery on socrat-2

The optional `vpn_failover` role prepares native systemd recovery for the primary 3x-ui configuration and the retained legacy fallback plus Caddy on `socrat-2`. The normal runtime is the Kubernetes `x-ui` Deployment in namespace `x-ui` with only the `primary` container. A short Python process runs from a systemd timer every 30 seconds after the previous check finishes; no additional daemon or container runs while the VPN is healthy.

Install from `ansible/`:

```bash
ansible-playbook playbooks/vpn-failover.yml --ask-become-pass
```

Installation preserves the pinned primary and legacy image filesystems under `/opt/homelab-vpn-failover`, renders dormant native services, installs Kubernetes server and agent startup guards, verifies current VPN health and enables `homelab-vpn-watchdog.timer`. Before enabling the timer, it starts the native runtimes in an isolated network namespace using private SQLite backups and copied runtime assets, checks them, and removes the test resources. It does not stop healthy Kubernetes workloads. The dedicated playbook is not imported into the normal VPN deployment. For independent VPS access, add `-e ansible_host=176.98.185.59 -e ansible_port=22`. Set `-e vpn_failover_arm=false` to prepare without enabling monitoring. Use `-e vpn_failover_verify_native=false` only when intentionally skipping the isolated smoke test.

## Detection and recovery

The watchdog checks the configured primary and legacy TCP VPN listeners and performs a certificate-validated TLS/WebSocket upgrade through local port 443 using the public VPN hostname and exact Trojan route. This detects missing listeners and a broken public Trojan ingress. It does not perform an authenticated VPN request or validate UDP tunnels end to end. Panel availability, the status page and Kubernetes API connectivity are not failure triggers.

Four consecutive unhealthy checks trigger recovery. A healthy check resets the counter. There is a 180-second grace period after VPS boot; check durations add to the nominal two-minute detection window. An unavailable home control plane alone does not trigger recovery while the VPN keeps working.

Before switching, the watchdog verifies required local files and checks both live SQLite databases read-only. It durably writes `/var/lib/homelab-vpn-failover/active`, stops both `k3s.service` and `k3s-agent.service`, and terminates remaining Kubernetes and k3s service cgroup processes. **This stops all Kubernetes pods on the VPS**, including Traefik and the status page. Home nodes are not stopped. It does not run `k3s-killall.sh` or flush network rules.

Only after checking that Kubernetes processes are gone and VPN ports are free does it start:

- `homelab-vpn-primary.service`
- `homelab-vpn-legacy.service`
- `homelab-vpn-caddy.service`

Both 3x-ui services execute directly under systemd with `RootDirectory` pointing to their preserved image filesystem. No Docker or Kubernetes runtime is required to start them. Bind mounts preserve the same live databases: `/srv/x-ui-lab/db` for primary and `/etc/x-ui` for legacy. Legacy also uses `/usr/local/x-ui/bin`. Database snapshots are not restored, merged or interchanged.

Caddy uses the retained certificate storage at `/srv/caddy/data/caddy` and can renew through ACME independently of cert-manager and the home control plane. Certificate issuance or renewal still needs working DNS, public challenge reachability and an ACME service. Existing subscription, panel and Trojan routes are retained.

The active marker survives reboot and blocks both Kubernetes server and agent startup. The timer retries starting native units that are inactive or failed, and each native unit has its own restart policy. A failure during recovery keeps the marker in place. If native VPN health fails four consecutive checks, the watchdog stops and restarts all three native services after verifying that their ports are released. A healthy check resets this separate recovery counter.

The native image digests come from `charts/x-ui/values.yaml`: `instances.primary` supplies the primary service and `instances.compatibility` supplies `homelab-vpn-legacy.service`. Recovery does not depend on the former `x-ui-lab` and `x-ui-legacy` namespace names.

## Interaction with the HA datastore

`socrat-2` now runs an etcd-only k3s server together with its workload agent. Native VPN recovery deliberately stops its etcd vote as well as every VPS pod. The two healthy home voters retain quorum. If either home voter is also unavailable, native recovery on the VPS leaves only one of three voters: Kubernetes loses quorum even though native VPN can keep serving. This prioritizes independent VPN recovery; it does not promise cluster availability through two simultaneous failures. Return to Kubernetes only after checking the surviving datastore and connectivity. See [the HA recovery runbook](k3s-ha.md).

## Inspection and maintenance

Run on `socrat-2`:

```bash
sudo /usr/local/sbin/homelab-vpn-failover check
sudo /usr/local/sbin/homelab-vpn-failover status
sudo systemctl status homelab-vpn-watchdog.timer
sudo journalctl -u homelab-vpn-watchdog.service -n 50
```

`check` and `status` do not modify the runtime. They print JSON and return a nonzero exit code if health checks fail. Configuration is in `/etc/homelab-vpn-failover/config.json`; the state directory also contains `failures.json` and the serialization lock.

For the one-time Kubernetes workload consolidation, use `ansible-playbook playbooks/vpn-consolidate.yml --ask-become-pass` from `ansible/`. It pauses monitoring under the serialization lock, backs up and compares both configurations and subscriptions, probes an authenticated tunnel, and restores the old workload configuration on failure before removing its maintenance hold. See [the consolidation procedure](vpn-cutover.md#consolidating-the-former-releases). This is a planned workload migration, not an outage or native failover test.

To pause automatic actions for planned maintenance:

```bash
sudo touch /var/lib/homelab-vpn-failover/inhibit
```

The inhibit marker affects subsequent checks; it does not cancel a check already in progress, stop native services or remove the Kubernetes startup fence. For maintenance requiring a fully stopped monitor, also stop the timer and wait for the running check to finish:

```bash
sudo systemctl stop homelab-vpn-watchdog.timer
sudo systemctl status homelab-vpn-watchdog.service
```

Resume checks after maintenance:

```bash
sudo rm /var/lib/homelab-vpn-failover/inhibit
sudo systemctl start homelab-vpn-watchdog.timer
```

## Return to Kubernetes

There is deliberately no automatic failback when the home control plane returns. The native VPN continues serving, preventing two runtimes from competing for the live SQLite files and listener ports.

When the control plane and VPS connectivity are healthy, schedule a brief VPN interruption and run:

```bash
sudo /usr/local/sbin/homelab-vpn-failover failback
```

This serializes against watchdog checks, verifies the Kubernetes fence, stops native services, verifies that their ports are released, resets the failure counter and grace period, removes the active marker and starts the configured primary Kubernetes service (`k3s.service` after HA promotion). If native services do not release their ports, the marker stays in place. If Kubernetes startup fails, the marker is restored and both service variants are fenced again. Verify `check`, Kubernetes workload readiness and an actual VPN client connection after failback. Do not remove the active marker by hand while native services own the databases.

Normal `vpn.yml` deployment and host workload cleanup refuse to proceed on `socrat-2` while recovery is active. Updating recovery assets also requires returning to Kubernetes first.

## Validation limits

Unit tests cover failure thresholds, grace periods, persistent fencing on errors, port conflicts, partial recovery retries, maintenance inhibit and manual failback. Installing and inspecting the dormant services does not demonstrate a real outage recovery. No home-node shutdown, live VPN cutover or VPS reboot test is part of this setup; those require a separate maintenance window. An authenticated VPN connection and both TCP/UDP client paths should be checked during that future exercise.

Historical watchdog installation validation on 2026-10-15, before workload consolidation: all 92 repository unit tests passed, including 17 watchdog tests. Both native 3x-ui instances and Caddy passed the isolated listener/TLS/WebSocket check. The production container IDs remained unchanged. The enabled timer reported Kubernetes mode, healthy VPN and zero failures; all fallback units remained inactive. A normal check consumed approximately 150 ms of CPU, with no watchdog process resident between checks. Host-side pre-start checks with `RootDirectoryStartOnly=yes` were also exercised using a harmless transient service.
