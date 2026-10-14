# VPN workloads after the emergency-runtime cutover

Both VPN configurations run on `socrat-2` in Kubernetes. Keep them separate: their databases contain different ports and client sets, including a client present only in the native configuration. Do not replace either database with the other or with the older `/srv/x-ui/db` snapshot.

| Release / namespace | Application version | Active database directory | Runtime assets |
| --- | --- | --- | --- |
| `x-ui-lab` | 3.10.0, pinned image digest | `/srv/x-ui-lab/db` | Container image |
| `x-ui-legacy` | 3.9.0, pinned image digest | `/etc/x-ui` | `/usr/local/x-ui/bin`, mounted at `/app/bin` |

Both deployments use `hostNetwork`, `dnsPolicy: Default`, a single replica, and `Recreate`. The database directories must already exist. Startup checks the panel listener; readiness checks the corresponding Trojan listener.

## Preserved endpoints

Primary listeners:

- Panel: TCP `18082`.
- Subscriptions: TCP `12096`.
- VLESS: TCP `32053`, `32083`, `32063`, `32084`.
- WireGuard: UDP `32085`.
- AmneziaWG: UDP `32086`.
- Trojan backend: TCP `32087`.

Legacy listeners:

- Panel: `172.18.0.1:16582`.
- Subscriptions: `172.18.0.1:2096`.
- VLESS: TCP `2053`, `2083`, `25763`, `48702`.
- WireGuard: UDP `51822`.
- AmneziaWG: UDP `51821`.
- Trojan backend: `172.18.0.1:10443`.

`caddy-edge` continues to own public TCP `80`/`443` and UDP `443`. Its routes, TLS state, hostname, and subscription paths were not changed. Public Trojan remains on `vpn.alchemmist.xyz:443`.

The legacy loopback address is maintained by `vpn-legacy-loopback.service`, ordered before `k3s-agent`. It does not depend on Docker's bridge. The legacy release has no Kubernetes Service because its panel/subscription endpoints intentionally retain their original loopback binding.

## Deployment

From `ansible/`:

```bash
ansible-playbook playbooks/vpn.yml --ask-become-pass
```

This prepares the loopback address on `socrat-2`, verifies that the existing databases are present, deploys both releases through `socrat-0`, and disables the native VPN and idle host Docker services after successful rollout. It refuses to compete with an active native service or emergency container. It does not perform an initial live cutover automatically.

Both releases are also included in `playbooks/apps.yml`; the legacy release uses `charts/x-ui/values-legacy.yaml`. Avoid changing the pinned image versions during a recovery operation.

## Emergency runtime state

- `x-ui.service`: stopped and disabled.
- `x-ui-lab-emergency`: stopped; Docker restart policy `no`.
- Host Docker service/socket and standalone containerd: stopped/disabled when no other Docker containers are running.
- The original service files, container, application data, and runtime assets are retained for rollback.

## Initial cutover and rollback

Before stopping a working runtime, take consistent SQLite backups using the SQLite backup API, verify `PRAGMA integrity_check`, record the client/configuration tables, and check the current subscription endpoints. Keep these artifacts root-only: databases and subscription responses contain credentials.

The October 14, 2026 cutover backup is stored on `socrat-2` under `/var/backups/homelab-vpn/20261014T144504Z`. Verification artifacts are under `/var/lib/homelab-vpn-cutover`.

For a rollback, first scale the affected Kubernetes deployment to zero and wait for its pod to terminate. Only then start its previous runtime:

- Primary: start host Docker if needed, then `docker start x-ui-lab-emergency`.
- Legacy: `systemctl start x-ui.service`.

Do not run the previous and replacement writers concurrently against the same SQLite database or ports. The rollback runtimes use the same live database directories, so restoring a database snapshot is unnecessary unless the database itself is damaged. Restoring a snapshot discards changes made after that snapshot and requires a separate decision.

## Verification

Check both pods are Ready, retain their pinned images, and have no restarts. Verify all original TCP/UDP listeners and the public subscription endpoint. Compare the client records, inbound configuration, keys, users, and panel settings with the pre-cutover snapshots, excluding traffic counters.

3x-ui selects a Reality `shortId` from the configured accepted set when generating subscriptions, so raw subscription bytes can differ between two consecutive requests. Validate that the accepted server-side `shortIds` are unchanged; compare generated links after excluding only that randomized field. Do not ignore credential, endpoint, transport, or port differences.

The cutover was checked against 15 primary and 16 legacy subscriptions, unchanged configuration tables, and an actual Trojan client request through public TLS and Caddy to an HTTPS destination.

Node-local CRI logs may be needed for diagnosis: during this work the control-plane proxy to `socrat-2:10250` returned HTTP 502 for `kubectl logs`. Pod status, readiness, direct listeners, and data-plane checks remained available. This is a separate management-connectivity issue.
