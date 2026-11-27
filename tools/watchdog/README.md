# Standalone VPN watchdog

This directory is the source distribution. Copy it alone to a Linux host. No repository checkout, Ansible, pip dependencies or Kubernetes client library is needed to launch the CLI. The Python runtime requires Python 3.10+; running the host controllers requires root, systemd, k3s and the provisioned VPN assets. It is not a VPN installer.

```
make check
sudo make install
homelab-watchdog server status   # socrat-2
homelab-watchdog relay status    # socrat-4
```

Run from source with `./watchdog` instead. `server tick` and `relay tick` each run **one** supervision cycle and may switch the production runtime. For continuous supervision, use the existing node-specific systemd timer; do not start a second timer. To adopt this entrypoint, override the existing oneshot unit's ExecStart with `/usr/local/bin/homelab-watchdog server tick` or `relay tick` (reset ExecStart first), preserving all other unit settings. Installation alone does not enable, restart or change any services.

| Component | Canonical source | Host prerequisites |
|---|---|---|
| Server controller | `runtime/server.py` | `/etc/homelab-vpn-failover/config.json`, native systemd units, gated workloads |
| Relay controller | `runtime/relay.py` | `/etc/homelab-vpn-transit/failover.json`, relay systemd units and gated container |
| Independent tunnel check | `runtime/witness.py`, `runtime/external-probe` | Xray, curl, dedicated `Socrat` group identity on socrat-0, restricted SSH client config on each controller |
| Durable transition lock | `runtime/coordinator.py` | Forced SSH command `homelab-watchdog coordinator socrat-2` or `socrat-4` selected by authorized key on socrat-1; protected writable state directory |
| Relay container gate | `gate/main.go` | Build `make gate` on Linux or cross-build for the target; hostPath mounts supplied by the deployment |

Provisioning helpers are in `provision/`; `compat/` contains the obsolete lock protocol, not an alternative coordinator. Keep credentials, database snapshots and ownership/lock state outside this tree. Existing Ansible source paths are compatibility symlinks, not additional implementations. Helm and Ansible remain deployment integrations, not runtime dependencies.
