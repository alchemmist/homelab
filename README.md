# homelab

Personal homelab automation for Socrat nodes.

Ansible manages the common host baseline: persistent SSH access, hostnames, shared users, the machine-wide Starship prompt, and host workload policies. Kubernetes, networking, storage, and applications have separate playbooks.

## Layout

```text
ansible/
  ansible.cfg
  inventory/hosts.yml
  group_vars/
  playbooks/
    base.yml
    users.yml
    starship.yml
    k3s.yml
    rancher.yml
    site.yml
  roles/
    base/
    users/
    starship/
charts/
  socrat-home/
```

## Public SSH access

All primary aliases connect to `socrat.alchemmist.xyz`. External port numbers are `2222 + node index` and are generated from inventory:

| Alias | Public endpoint | Current destination |
| --- | --- | --- |
| `socrat-0` / `socrat-master` | `socrat.alchemmist.xyz:2222` | `192.168.0.23:22` |
| `socrat-1` | `socrat.alchemmist.xyz:2223` | `192.168.0.24:2222` |
| `socrat-2` | `socrat.alchemmist.xyz:2224` | Relay on `socrat-0` through WireGuard to `10.250.0.2:22` |

The home router owns persistent static mappings. `homelab_ssh_router_mapping_mode: static` disables the former UPnP reconciliation timer while preserving the SSH relay. TCP 22 remains enabled alongside 2222 for recovery. The relay preserves SSH encryption and uses each destination's own host key and authorized keys. `socrat-2-direct` retains the independent VPS endpoint for recovery when the home gateway is unavailable.

From `ansible/`:

```bash
ansible-playbook playbooks/ssh-gateway.yml
ansible-playbook playbooks/ssh-client.yml
```

The first playbook configures the gateway on `socrat-0`; the second manages local aliases in `~/.ssh/config.d/homelab.conf`. See [node provisioning and SSH migration](docs/node-bootstrap.md) for initial setup, recovery, and adding nodes.

## Private administrative access

The Mac joins `wg-socrat` with one WireGuard profile and a direct peer for each
node. Private DNS names `0.socrat.alchemmist.xyz`, `1.socrat.alchemmist.xyz`, and
`2.socrat.alchemmist.xyz` resolve to the individual WireGuard addresses; every
node accepts private SSH on TCP 2222. DNS runs on all three hosts outside
Kubernetes. The Mac peer is restricted to SSH, DNS, and the private HTTPS interfaces.

Server configuration is managed by `playbooks/wireguard-admin-access.yml`;
`playbooks/wireguard-admin-client.yml` preserves the local private key and
renders the Mac profile and split DNS configuration. Profile import and macOS
VPN approval use the official WireGuard application.

```bash
ssh -i ~/.ssh/socrat-master -p 2222 alchemmist@0.socrat.alchemmist.xyz
ssh -i ~/.ssh/socrat-1 -p 2222 alchemmist@1.socrat.alchemmist.xyz
ssh -i ~/.ssh/personal_server -p 2222 alchemmist@2.socrat.alchemmist.xyz
```

See the [administrative access runbook](docs/wireguard-admin-access-plan.md#reapply-the-deployed-configuration)
for Ansible commands, router mappings, provisioning and remaining acceptance checks.

## Private Syncthing UI

Each node runs one Syncthing pod with its own local data and identity. With
WireGuard connected, open `https://0.socrat.alchemmist.xyz/sync/` and the
corresponding node 1 or 2 name. The existing BasicAuth credentials are retained;
public `sync-*` ingresses and direct network access to the raw GUI are closed.

Apply `playbooks/syncthing-private-ui.yml` using the direct maintenance
inventory. See the [Syncthing runbook](docs/syncthing-private-ui.md) for the
traffic model, certificate renewal, monitoring, provisioning and recovery.

## Local LLM inference

`ansible/playbooks/llm.yml` deploys the NVIDIA device plugin and one vLLM engine on the RTX 3090 in `socrat-0`. Qwen3.8-27B INT4 is the only installed model (128K context). The internal gateway serializes requests. The authenticated public API is `https://llm.alchemmist.xyz/v1`; Open WebUI at `https://chat.alchemmist.xyz` uses its own LiteLLM key. See [model serving](docs/model-switching.md) for profiles, limits and validation.

Inference is running. The earlier Qwen3-8B deployment passed API, concurrency, and pod-recreation checks. An earlier kernel panic did not recur in the controlled retry; its underlying kernel/driver/hardware cause remains unresolved. See the runbook for evidence and the limits of this validation.

See the [local inference runbook](docs/local-llm.md) for deployment, SSH access, smoke checks, resource limits, and registry access requirements.

Open WebUI requires a user login at [chat.alchemmist.xyz](https://chat.alchemmist.xyz). LiteLLM provides the authenticated API and admin UI at [llm.alchemmist.xyz](https://llm.alchemmist.xyz/ui/). Both use cert-manager-managed HTTPS certificates.

## Run

Install Ansible locally, then from `ansible/`:

```bash
ansible-playbook playbooks/starship.yml --ask-become-pass
```

Limit to one node:

```bash
ansible-playbook playbooks/starship.yml --limit socrat-1 --ask-become-pass
```

## Desktop session

`socrat-0` and `socrat-1` opt into automatic local login as `alchemmist` on tty1 and direct Hyprland startup. SSH, sudo, and account passwords stay configured. SSH, networking, WireGuard, and k3s start as system services independently of graphical login.

From `ansible/`:

```bash
ansible-playbook playbooks/desktop.yml --ask-become-pass
```

The desktop configuration is split into `desktop_session` (console login), `desktop_environment` (Hyprland, idle policy, caffeine, and wallpaper startup), `desktop_panel` (Waybar), and `desktop_terminal` (Alacritty, tmux, and the `btm` monitor). Shared templates use host profiles in `ansible/inventory/host_vars/socrat-0.yml` and `socrat-1.yml`; personal Hyprland additions belong in `~/.config/hypr/local.conf`.

Homelab settings are separate from personal dotfiles. Before desktop roles run, including tagged runs, `node_config_isolation` materializes node-local copies of linked desktop configs, managed scripts, tmux/login files, and the caffeine unit. Backups and a manifest live in `~/.local/state/homelab/config-isolation/`. Homelab does not deploy or push changes to the personal dotfiles repository.

Workspaces are created as needed with Win+1 through Win+0; Waybar shows occupied/current workspaces on each output without a fixed empty 1–10 list. New sessions open the monitor terminal without automatically opening browsers, Telegram, or Obsidian. Existing windows remain open. On `socrat-1`, workspace 1 stays assigned to the external display.

`wallpaper_asset` distributes the same image from `socrat-0` to `/usr/local/share/wallpapers/homelab/default.png` on all three nodes through `base.yml`, `site.yml`, or `desktop.yml`. The VPS receives only the image, with no graphical environment. Use `--limit socrat-0,socrat-1` to apply only to the home nodes. This is not a complete GUI installer: Hyprland, `start-hyprland`, `awww`, and other graphical tools must already exist, and `bottom` is installed from distribution repositories when `btm` is absent (a trusted package must be supplied separately if the repository lacks it). Existing personal application shortcuts retain their external dependencies.

The shared desktop configuration is applied on both home nodes. Wallpaper, tmux/btm, and the hidden Flameshot tray icon were verified in the running sessions; the asset is also installed on the VPS. Startup after reboot/power restoration was verified before this cosmetic rollout; the new terminal startup command has been exercised live without rebooting. See the [boot and recovery runbook](docs/node-bootstrap.md#automatic-boot-and-local-desktop) for settings, backups, prerequisites, and outstanding shutdown verification.

## Starship prompt

The role deploys a machine-wide Starship config to `/etc/starship/starship.toml` and enables it from global shell rc files (`/etc/zsh/zshrc`, `/etc/bash.bashrc` when present), so it applies to every interactive user, not only `alchemmist`.

The deployed prompt includes a grey host marker on the command line:

```text
(socrat-0) 
(socrat-1) 
```

The marker uses runtime `hostname`, so the same `starship.toml` works on future nodes like `socrat-2`, `socrat-3`, etc.

## k3s

The default k3s stack is used for ingress:

- Traefik: ingress controller
- ServiceLB/klipper-lb: exposes Traefik `LoadBalancer` on node ports 80/443
- cert-manager: Helm-managed, issues Let's Encrypt certificates via HTTP-01

Run:

```bash
cd ansible
ansible-playbook playbooks/k3s.yml --ask-become-pass
```

Current public router forwards expected by the cluster:

```text
80  -> 192.168.0.23:80
443 -> 192.168.0.23:443
```

Caddy is stopped/disabled by the k3s playbook so Traefik can own HTTP/HTTPS. The VPS VPN now uses the separate `traefik-edge` ingress controller on `socrat-2`; the former Caddy Helm release was removed. See [VPN ingress deployment and verification](docs/vpn-cutover.md#traefik-vps-ingress-migration).

Rancher is installed as the Kubernetes management UI:

```text
URL:          https://rancher.socrat.alchemmist.xyz
Namespace:    cattle-system
Cluster name: Socrat (Rancher local cluster display name)
Replicas:     1
Placement:    pinned to socrat-0
Logo:         assets/rancher/socrat-logo.png, applied to Rancher light/dark UI logo settings
TLS:          Rancher Helm chart + cert-manager Let's Encrypt
```

Cluster applications are Helm-managed where appropriate. Resource requests/limits are configured for our managed workloads:

```text
socrat-home nginx:      requests 10m/32Mi, limits memory 128Mi
Rancher server:         requests 250m/1Gi, limits memory 3Gi
Rancher webhook:        requests 20m/64Mi, limits memory 256Mi
system-upgrade-controller: requests 10m/64Mi, limits memory 256Mi
cert-manager:          requests 50m/128Mi, limits memory 512Mi
cert-manager webhook:  requests 20m/64Mi, limits memory 256Mi
cert-manager cainjector: requests 50m/128Mi, limits memory 512Mi
Traefik:               requests 100m/128Mi, limits memory 512Mi
```

Cluster applications are Helm-managed where appropriate:

```text
cert-manager  -> Helm release cert-manager in cert-manager
Rancher       -> Helm release rancher in cattle-system
socrat-home   -> local Helm chart charts/socrat-home
Traefik       -> k3s-managed Helm release in kube-system
```

The current homepage is served by a dedicated Kubernetes container:

```text
Helm:      release socrat-home from charts/socrat-home
Deployment: socrat-home, 2 replicas, one per node via pod anti-affinity/topology spread
Image:      localhost/socrat-home:latest, built from /var/www/socrat and imported into k3s containerd on every node
Service:    socrat-home:8080 -> container:80
Ingress:    socrat.alchemmist.xyz -> socrat-home:8080
TLS:        cert-manager / letsencrypt-http01
```

## Secrets

Do not commit passwords or private keys. Use SSH keys and, later, `ansible-vault` for real secrets.

LiteLLM API gateway: [deployment and access](docs/litellm.md).

Open Terminal workspace on socrat-1: [deployment and connection](docs/open-terminal.md).
