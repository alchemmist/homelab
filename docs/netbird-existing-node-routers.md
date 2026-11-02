# NetBird peers on the existing nodes

`scripts/netbird-host-router.py` plans peers for **socrat-0** (home) and **socrat-2** (VPS). It does not create VMs, enroll peers, or edit `wg-socrat`, K3s routes, or OpenSSH keys. `check` and `plan` are render-only. `apply` copies the reviewed files into a root you name, and only after the plan has no blockers.

The topology record `62c264f` still stands on the points that matter here: no hypervisor is installed, socrat-2 has **446 MiB** `MemAvailable` (`455948` KiB), and noninteractive sudo failed on every node. Those are installation blockers. They are not a reason to invent router VMs.

```sh
python3 scripts/netbird-host-router.py check
python3 scripts/netbird-host-router.py plan --out /tmp/netbird-host-router-plan
python3 -m unittest discover -s tests -p test_netbird_host_router.py -v
```

`check` exits 2 while blockers remain. `plan` writes `plan.json`, a systemd unit, `table.nft.sh`, the Grafana frontend, and an Ansible playbook whose `netbird_host_router_apply` variable defaults to false. The output directory must be outside the Git worktree.

## Two different jobs

| Host | Failure domain | SSH `10.250.0.2` | Grafana |
| --- | --- | --- | --- |
| socrat-0 | `home-lan` | routing peer, **FORWARD** `nb-host` → `wg-socrat`, SNAT to `10.250.0.1` | overlay destination, **INPUT** TCP 8443 |
| socrat-2 | `vps-176.98.185.59` | destination host, **INPUT** on the existing address; NetBird server routes disabled | overlay destination, **INPUT** TCP 8443 |

A packet for `10.250.0.2` that arrives on socrat-2 is delivered to the local host. The firewall chain is INPUT. Copying socrat-0's FORWARD/SNAT rules onto socrat-2 would claim a path that host cannot take. socrat-2's rendered `table.nft.sh` does not mention `10.250.0.2` and does not accept forwarded traffic. Its unit sets `NB_DISABLE_SERVER_ROUTES=true`.

SSH route HA is false. If socrat-0 is down, NetBird clients lose this path. socrat-2 staying up does not replace it. Grafana is two separate overlay policies (`overlay-peer:socrat-0` and `overlay-peer:socrat-2`), each on TCP 8443. That is two listeners, not one routed prefix with two routers.

## SSH port

On 2026-11-02 a TCP connect to `10.250.0.2` from the operator machine got a connection on **2222** and `ECONNREFUSED` on **22** and **2224**. That probe did not log in and did not read host keys. The default plan therefore routes TCP 2222 only. Port 22 remains a legal explicit choice when `ssh_probe` is omitted; it is rejected while this probe is attached. The public relay port 2224 is not a target. OpenSSH `authorized_keys` and `sshd_config` are not in the rendered files. NetBird's own SSH server is off (`--allow-server-ssh=false` and the root, SFTP, and port-forward flags false).

Return traffic uses SNAT to socrat-0's existing mesh address `10.250.0.1`. No WireGuard config, AllowedIPs, or K3s route is added. The existing `/32` is the address socrat-2 already has.

## Grafana frontend

The shared listener `10.250.0.3:443` stays out of the NetBird policy. It still answers several names, which the topology report recorded. Each peer instead listens on its NetBird address, TCP 8443, interface `nb-host`:

- The process refuses `0.0.0.0`, public addresses, and every `10.250.0.0/24` or LAN address.
- The owned nft table drops TCP 8443 on every interface other than `nb-host`.
- The TLS callback rejects any SNI other than `grafana.socrat.alchemmist.xyz`.
- The HTTP `Host` must be that same name. ALPN is HTTP/1.1.
- The upstream socket is exactly `10.250.0.3:443` with `server_hostname` set to the Grafana name, `CERT_REQUIRED`, and hostname checks left on.

The operator supplies `/etc/netbird-host-router/frontend.crt` and `frontend.key` on the host. The plan does not generate or commit them. The setup key file `/etc/netbird-host-router/setup.key` is also host-local, mode `0400` or `0600`, and is never rendered.

## Client, firewall, and blockers

The client image is the pinned lock entry `netbirdio/netbird:0.82.0` with digest `sha256:eca5b274c635bfbb04ec6724a0712d1146190dd450eea199eeb83916fdd94965`. The Docker unit drops all capabilities, adds `NET_ADMIN`, `NET_RAW`, and `BPF`, sets `no-new-privileges`, a 64-pid limit, a read-only root, and `--memory=96m` with swap capped at the same size. It uses host networking so the one SSH forward can see `wg-socrat`, and it does not mount the Docker socket, `/etc/ssh`, or `/etc/wireguard`. A host-process unit is rendered when `runtime` is `host`: its capability bounding set is those three capabilities because `NoNewPrivileges=true` would drop the ambient set NetBird needs for the tun device.

The firewall script owns only `table ip netbird_host_router`. It runs `nft -c -f` before `nft -f` and exits while the overlay address is still the `__NB_OVERLAY_IP__` token. socrat-0 also gets `/etc/sysctl.d/99-netbird-host-router.conf` containing `net.ipv4.ip_forward=1`. socrat-2 does not get that file. Rollback is:

```sh
systemctl disable --now netbird-host-router.service netbird-grafana-frontend.service
nft delete table ip netbird_host_router
rm -f /etc/sysctl.d/99-netbird-host-router.conf
```

Removing the sysctl file does not turn forwarding off on a live node. Docker and K3s may already depend on it.

Current blockers stored in the default facts:

- `netbird.socrat.alchemmist.xyz` was NXDOMAIN in the topology report, so `management_url` is empty.
- Noninteractive sudo is unavailable on socrat-0 and socrat-2, so neither the unit nor the nft table can be loaded from this account.
- `docker info` failed on socrat-0. socrat-2 has Docker 29.6.2, which still needs root to start the unit.
- 446 MiB free on the VPS fits a 96 MiB client and a 32 MiB frontend with 256 MiB left for the node. A 256 MiB client cap is rejected. It does not fit a second Linux VM, which matches `62c264f`.

`apply --overlay-ip` accepts only an address inside the CGNAT overlay (`100.96.0.0/16` by default) and refuses public, mesh, and unspecified addresses. The Ansible file in the plan is the same copy set; leave `netbird_host_router_apply` false until that file has been reviewed.
