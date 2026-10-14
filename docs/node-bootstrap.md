# Node provisioning and public SSH access

## Public endpoint convention

Every primary alias uses `socrat.alchemmist.xyz`, with external port `2222 + node index`: `socrat-0` uses `2222`, `socrat-1` uses `2223`, and `socrat-2` uses `2224`. `ansible_port` is computed from this convention in `inventory/group_vars/Socrat.yml`.

The server listening port is a separate setting, `homelab_ssh_port`, which defaults to `2222`. The deployed gateway accepts legacy server port `22` during migration. Currently `socrat-0` and `socrat-2` still use server port `22`; `socrat-1` supports `2222`.

## Gateway and client configuration

Run from `ansible/`:

```bash
ansible-playbook playbooks/ssh-gateway.yml
ansible-playbook playbooks/ssh-client.yml
```

The gateway role runs as `alchemmist` on `socrat-0`. It requires Python 3, `miniupnpc`, and `socat`, already installed on this node. On a fresh Debian gateway, install them with `sudo apt install python3 miniupnpc socat` before applying the role. UPnP must be enabled on the home router. Keep DHCP reservations for home node addresses.

The role enables user lingering and installs:

- `homelab-ssh-gateway.timer`: reconciles mappings after boot and every 30 seconds after the previous run, including after a router restart or network outage.
- `homelab-ssh-gateway.service`: probes SSH backends and restores missing mappings. It prefers backend `2222`, falls back to `22`, and refuses to replace a conflicting mapping owned by another application.
- A socket and per-connection relay service for each node with `homelab_ssh_relay: true`. The VPS uses port `2224` on `socrat-0` and connects through WireGuard to `10.250.0.2`. Each new connection selects an available backend SSH port.

Configuration is stored in `~/.config/homelab/ssh-gateway.json`, generated from inventory. The configured router description URL and static public IP are defaults of the `ssh_gateway` role; update those defaults if the router or public address changes.

The client playbook writes `~/.ssh/config.d/homelab.conf` and includes it before other host definitions in `~/.ssh/config`. It does not disable host key verification. For a newly exposed endpoint, verify the host key against the node through an already trusted connection before accepting it.

The public route to `socrat-2` depends on the home gateway and WireGuard. `ssh socrat-2-direct` remains available independently via `176.98.185.59:22`. If the VPS server port changes, update `homelab_ssh_direct_port` and regenerate the client config.

## Initial gateway recovery

If public mappings are missing, apply the gateway role through the current LAN SSH port:

```bash
ansible-playbook playbooks/ssh-gateway.yml \
  -e ansible_host=192.168.0.23 -e ansible_port=22
```

Use port `2222` instead if the gateway's SSH server has already been migrated. This recovery playbook does not change server ports.

## Migrate existing SSH servers to 2222

The `ssh` role is included in `base.yml` and `site.yml`. It supports Debian, Ubuntu, and Arch Linux, persists the server port in `/etc/ssh/sshd_config.d/10-homelab-ports.conf`, disables socket activation where present, and enables the SSH service at boot. Existing authentication settings and authorized keys are preserved.

Migrate home nodes directly through the LAN overlay:

```bash
ansible-playbook -i inventory/hosts.yml -i inventory/lan.yml \
  playbooks/ssh.yml --limit socrat-0 \
  -e homelab_ssh_bootstrap_port=22 --ask-become-pass

ansible-playbook -i inventory/hosts.yml -i inventory/lan.yml \
  playbooks/ssh.yml --limit socrat-1 --ask-become-pass
```

Migrate the VPS through its existing public relay endpoint:

```bash
ansible-playbook playbooks/ssh.yml --limit socrat-2 --ask-become-pass
```

The role preserves both the actual connection port and configured server ports until it verifies a fresh connection to the desired server port. Only then does it remove the old port. A conflicting configuration is restored to its transitional state and reported. The gateway timer follows backend changes automatically; public endpoint numbers remain unchanged.

For the VPS direct recovery alias, also allow incoming TCP `2222` in the provider/host firewall and update `homelab_ssh_direct_port` to `2222` after migration. Regenerate the client config.

Do not pass `-e ansible_port=...` to the SSH server migration playbook: extra variables override its temporary connection-port changes. Use `homelab_ssh_bootstrap_port` for the initial client endpoint if needed.

## Add a node

1. Install Debian, Ubuntu, or Arch Linux with Python 3, working SSH, an administrator account with sudo, and your public SSH key. Verify its host key through a trusted channel.
2. Add `socrat-N` under `Socrat` in `inventory/hosts.yml`, setting `homelab_ssh_private_host` to its LAN or WireGuard address and `ansible_ssh_private_key_file` to the controller's private key path. Set `ansible_user` if needed. External port `2222 + N` is computed automatically.
3. For a remote node, configure WireGuard first and set `homelab_ssh_relay: true`. For a home node, reserve its LAN address and add it to `inventory/lan.yml` for direct provisioning.
4. Rerun `ssh-gateway.yml` and `ssh-client.yml`. Verify the destination host key and test `ssh socrat-N`.
5. Apply the host baseline with `ansible-playbook playbooks/site.yml --limit socrat-N --ask-become-pass`. A new home node initially on server port `22` should first be migrated through a LAN overlay using `ssh.yml` and `homelab_ssh_bootstrap_port=22`.

`site.yml` configures host settings, shared users, Starship, Syncthing host policy, and workload policy. It does not allocate VPN addresses or automatically join Kubernetes. Update the host aliases in the base role, `wg_socrat_nodes`, and the node IP map in `k3s.yml`, then run the corresponding networking and Kubernetes playbooks. Review storage and application placement for the new node separately.

Removing a node also requires removing its router mapping and any relay socket explicitly; reconciliation never deletes unrelated mappings or infers removals from an unreachable node.

## Verify

On the controller:

```bash
ssh -G socrat-0
ssh socrat-0 hostname
ssh socrat-1 hostname
ssh socrat-2 hostname
```

On `socrat-0`:

```bash
systemctl --user status homelab-ssh-gateway.timer
journalctl --user -u homelab-ssh-gateway.service -n 30
loginctl show-user alchemmist -p Linger
upnpc -l
```

Expect public TCP mappings `2222`, `2223`, and `2224`, an active timer, and `Linger=yes`. A missing mapping should return during the next successful reconciliation. Test public endpoints from an external network as well as from the LAN.

For SSH server persistence, rerun `ssh.yml` without a bootstrap override, check `sudo sshd -T`, and verify the service is enabled (`ssh.service` on Debian, `sshd.service` on Arch). At a suitable maintenance time, reboot the node and verify fresh SSH access.
