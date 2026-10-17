# Uptime Kuma private service checks

Kuma runs with host networking and resolves names through the Socrat WireGuard DNS servers at `10.250.0.2`, `10.250.0.1` and `10.250.0.3`. These servers resolve private services to WireGuard addresses and forward other DNS queries. The public status page displays the resulting health checks; visitors do not need access to the private services.

The existing Rancher monitor checks `https://rancher.socrat.alchemmist.xyz/ping` using the HTTP keyword monitor type. Success requires HTTP 200, a valid TLS certificate and a response containing `pong`. Redirects are disabled. Its monitor ID, history, status-page groups, interval and notification configuration are preserved.

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/uptime-kuma-private-monitoring.yml --ask-become-pass
```

The playbook discovers Kuma's current node and host-path database rather than assuming a fixed placement. It validates private DNS and HTTPS from the existing container, stops the single SQLite writer only when a change is required, makes a private SQLite backup, updates the existing monitor and patches only the Deployment DNS settings. An `always` block starts Kuma again after maintenance. The chart carries the same DNS defaults for subsequent Helm deployments, including a template fallback for releases upgraded with older values.

Backups are stored under the active data directory's `backups/` folder as `rancher-monitor-*.db`, readable only by root. The migration helper must only be applied while Kuma is stopped; `--check` is safe against the running database. It refuses missing or ambiguous Rancher monitors instead of creating a second monitor. Rerunning the playbook with matching settings does not restart Kuma or create another backup. A recent successful Rancher heartbeat is required before the playbook succeeds.

The DNS change applies to all monitors. Before the initial deployment, all 17 monitored domain names were checked against every private resolver. Rancher and Wiki changed to private addresses; all other domain answers and literal-IP checks were unchanged. Keep this in mind when adding future public-versus-private reachability checks. A public access-denied landing page is not a Rancher health check.

Verification:

```sh
python3 -m unittest discover -s tests -p test_kuma_private_monitor.py
```

The tests cover preservation of monitor identity, history and groups, unrelated configuration, backup permissions, read-only inspection, idempotence and refusal of ambiguous or missing targets.
