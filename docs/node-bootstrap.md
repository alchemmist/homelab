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

The role preserves both the actual connection port and configured server ports until it verifies a fresh connection to the desired server port. Only then does it remove ports absent from `homelab_ssh_preserve_ports`. The deployed `[22]` setting retains recovery SSH. A conflicting configuration is restored to its transitional state and reported. Public endpoint numbers remain unchanged; static router mappings are managed separately.

For the VPS direct recovery alias, also allow incoming TCP `2222` in the provider/host firewall and update `homelab_ssh_direct_port` to `2222` after migration. Regenerate the client config.

Do not pass `-e ansible_port=...` to the SSH server migration playbook: extra variables override its temporary connection-port changes. Use `homelab_ssh_bootstrap_port` for the initial client endpoint if needed.

## Add a node

1. Install Debian, Ubuntu, or Arch Linux with Python 3, working SSH, an administrator account with sudo, and your public SSH key. Verify its host key through a trusted channel.
2. Add `socrat-N` under `Socrat` in `inventory/hosts.yml`, setting `homelab_ssh_private_host` to its LAN or WireGuard address and `ansible_ssh_private_key_file` to the controller's private key path. Set `ansible_user` if needed. External port `2222 + N` is computed automatically.
3. For a remote node, configure WireGuard first and set `homelab_ssh_relay: true`. For a home node, reserve its LAN address and add it to `inventory/lan.yml` for direct provisioning.
4. Add the persistent router forward or relay required by the new node, then rerun `ssh-gateway.yml` and `ssh-client.yml`. In static mode the gateway playbook manages relay sockets but does not create router forwards. Verify the destination host key and test `ssh socrat-N`.
5. Apply the host baseline with `ansible-playbook playbooks/site.yml --limit socrat-N --ask-become-pass`. A new home node initially on server port `22` should first be migrated through a LAN overlay using `ssh.yml` and `homelab_ssh_bootstrap_port=22`.

`site.yml` configures host settings, shared users, Starship, Syncthing host policy, and workload policy. It does not allocate VPN addresses or automatically join Kubernetes. Update the host aliases in the base role, `wg_socrat_nodes`, and the topology in the `k3s_ha` role, then run the corresponding networking and Kubernetes playbooks. Review storage and application placement for the new node separately.

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

In the deployed static mode, expect public TCP mappings `2222`, `2223`, and `2224` in the router configuration, a disabled gateway timer, an active relay socket, and `Linger=yes`. Ansible does not recreate missing static router mappings. See [router desired state](router-static-mappings.md) and the [private administrative access runbook](wireguard-admin-access-plan.md#reapply-the-deployed-configuration). Test public endpoints from an external network as well as from the LAN.

For SSH server persistence, rerun `ssh.yml` without a bootstrap override, check `sudo sshd -T`, and verify the service is enabled (`ssh.service` on Debian, `sshd.service` on Arch). At a suitable maintenance time, reboot the node and verify fresh SSH access.

## Independent laptop-to-VPS transport

The HA topology requires the `wireguard_tcp_transport` services on `socrat-1` and `socrat-2` while their direct WAN UDP path is unreliable. Apply `playbooks/wireguard-tcp-transport.yml` through the canonical networking/HA workflow and verify its client, relay and health timer after reboot. Preserve the private mode-`0600` authentication material and pinned TLS trust configuration; do not copy secrets into inventory or logs. This transport does not depend on `socrat-0`. Deployment and validation status are recorded in [the HA runbook](k3s-ha.md#home-laptop-to-vps-transport).

## Automatic boot and local desktop

`playbooks/desktop.yml` distributes the common wallpaper to all nodes and manages OS startup and desktop configuration for the opted-in home nodes. Run from `ansible/`:

```bash
ansible-playbook playbooks/desktop.yml --ask-become-pass
```

The same roles are included in `site.yml`; `base.yml` also distributes the wallpaper asset. Use `--limit socrat-0,socrat-1` if the VPS image should not be updated. The VPS receives no GUI configuration. Use the dedicated desktop playbook when changing only boot and desktop settings. It does not install a complete graphical environment or join a new node to Kubernetes: the account, `/usr/bin/start-hyprland`, Hyprland, `awww`, `awww-daemon`, Waybar, Hypridle, and listed infrastructure services must already exist. `desktop_terminal` installs Alacritty, tmux, and zsh. The monitor uses `homelab_monitor_binary` (`/usr/bin/btm` by default) and requires bottom 0.14.9 or newer for table sorting. If that binary is absent, the role installs the distribution `bottom` package; when unavailable, provision a trusted package first. Older personal Cargo binaries are preserved and do not override the monitor launcher.

Desktop-specific variables live in `ansible/inventory/host_vars/socrat-0.yml` and `socrat-1.yml`. Shared templates provide the common behavior; host variables select monitor layouts, desktop/laptop profiles, and additional startup applications. Keep local Hyprland additions in `~/.config/hypr/local.conf`, which Ansible creates only if missing and sources after the managed configuration.

The `node_config_isolation` role runs before desktop roles, with the `always` tag so it also runs during tagged deployments. It materializes `~/.config/hypr`, `~/.config/waybar`, `~/.config/alacritty`, managed scripts, tmux/login files, and the caffeine service unit as node-local files when they link into personal dotfiles. Backups of the original paths and a `manifest.json` are stored under `~/.local/state/homelab/config-isolation/<timestamp>/`. Subsequent homelab changes modify these local copies, not the dotfiles checkout. Do not deploy or push personal dotfiles as part of homelab configuration.

Inventory settings:

| Setting | Purpose |
| --- | --- |
| `homelab_desktop_autologin: true` | Enable tty1 autologin and direct Hyprland startup. |
| `homelab_desktop_login_file` | Startup file; defaults to `.zprofile`, while `socrat-1` uses `.zshrc`. |
| `homelab_desktop_environment` | Preserve host-specific environment variables in the root-owned launcher. |
| `homelab_desktop_remove_sway: true` | Archive old selector/configuration paths and remove unused Sway packages on Arch. |
| `homelab_desktop_caffeine_default: true` | Start each Hyprland session with Waybar caffeine mode enabled. |
| `homelab_desktop_profile` / `homelab_waybar_profile` | Select the shared desktop or laptop behavior and panel modules. |
| `homelab_hypr_monitors` / `homelab_hypr_autostart` | Set host-specific monitor layouts and additional startup commands. |
| `homelab_hide_flameshot_tray: true` | Hide only the Flameshot tray icon; enabled on `socrat-0`. |
| `homelab_wallpaper_path` | Shared wallpaper destination, defaulting to `/usr/local/share/wallpapers/homelab/default.png`. |
| `homelab_boot_services` | Existing network, SSH, WireGuard, and k3s services to enable and start. |
| `homelab_boot_k3s_service` | `k3s.service` on all current HA nodes; legacy workers use `k3s-agent.service`. |
| `homelab_boot_wifi_uuid` | Optional existing Wi-Fi profile to verify for login-independent autoconnect. |
| `homelab_ignore_lid_on_ac: true` | Ignore laptop lid closure on external power or while docked. |

The `node_boot` role orders k3s after the WireGuard service, retries failed WireGuard startup, and enables user lingering. The Wi-Fi check requires an existing system-wide autoconnect profile with a stored secret; it does not collect or change Wi-Fi credentials. On `socrat-0`, Ethernet remains managed by the existing ifupdown configuration. Services and pods do not require a graphical login, although workloads still depend on the cluster network, control plane, and storage.

The `desktop_session` role installs `/usr/local/bin/start-socrat-hyprland` and a `getty@tty1.service` autologin drop-in. Only an interactive local tty1 shell starts Hyprland; SSH sessions, tty2, and shells inside an existing desktop do not. Account passwords, sudo, SSH authentication, and desktop locking remain configured. Local tty1 grants the account's session automatically, so physical access grants access to that desktop.

On `socrat-1`, obsolete `wlinitrc`, `tdm.sh`, and installed Sway configuration paths are archived under `~/.local/state/homelab/desktop-backups/<timestamp>/`. The earlier migration also backed up modified shell and Hypridle files there. Managed desktop templates and scripts now use Ansible backups when replacing existing files. The initial deployment followed profile symlinks and modified their dotfiles targets; this was corrected by materializing node-local configurations before further changes. Fifteen source files were restored from exact pre-change backups (seven on `socrat-0`, eight on `socrat-1`), preserving unrelated pre-existing modifications. This does not imply that the personal dotfiles worktrees are clean. Archived selector symlinks do not remove their source files. Sway, swaybg, and swaylock are removed with unused dependencies; Hyprland's swaync notification service and fzf stay installed. Hypridle dimming and locking listeners remain, but the old 30-minute power-off listener is removed.

The playbook reloads systemd definitions without restarting getty or logind. Autologin and the lid policy take effect on the next boot; current graphical sessions remain running. The user rebooted `socrat-1` successfully and confirmed automatic Hyprland startup; fresh SSH access and uptime were verified. The user also tested physical AC power restoration on `socrat-0`: the machine powered on automatically, SSH and Hyprland recovered, and all three Kubernetes nodes were verified `Ready`.

The `desktop_environment` role now owns the shared Hyprland template, Hypridle configuration, caffeine script, and inhibitor unit, replacing the earlier patch-based caffeine setup. On `socrat-1`, `homelab_desktop_caffeine_default: true` selects `~/scripts/caffeine-manager.sh --enable` at graphical startup. Caffeine mode stops Hypridle and starts `caffeine-lid-inhibit.service`, so idle dimming/locking is inactive and lid closure is inhibited, including on battery. The existing Waybar button still toggles the mode; turning it off restores Hypridle. The explicit `--enable` and `--disable` commands set a known state without toggling it. Each new Hyprland session starts with caffeine enabled again.

The `desktop_panel` role delivers common Waybar JSON/CSS with desktop/laptop module profiles and supporting helpers. It hides the Flameshot tray icon only on `socrat-0`, preserving screenshot functionality. Existing personal shortcuts and optional integrations, including WireGuard controls, wallpaper selectors, screenshot/theme scripts, hyprshade, and personal applications, retain dependencies outside these roles; they are not a complete application installer.

The `desktop_terminal` role starts `/usr/local/bin/homelab-monitor-terminal` on workspace 1: Alacritty attaches to tmux session `tmp`, whose monitor window runs zsh and `btm`. Existing tmux configuration is preserved; optional popup-table unbind commands are migrated to `unbind -q` so a missing popup table does not generate startup errors. A base tmux configuration is created only when absent.

The `wallpaper_asset` role delivers the image selected from `socrat-0` to all three nodes. Home desktops use `/usr/local/bin/homelab-wallpaper` with `awww`; `~/Pictures/wallpapers/current-wallpaper` points to the same asset for desktop and lockscreen use. No desktop services are added to `socrat-2`.

The shared desktop refactor was applied on 2026-10-14. Both installed Hyprland binaries validated the generated configuration, and running sessions report no configuration errors. All three nodes received the wallpaper; both home nodes run btm in a single-window tmp session. Flameshot remains running on socrat-0 with no registered tray item. The rollout preserved both Hyprland processes and all Kubernetes nodes remain Ready. The new startup commands were exercised live; no reboot was performed for this cosmetic rollout.

### Hardware power restoration

OS startup begins only after firmware powers the machine on:

- `socrat-0`: ASUS PRIME X299-A II, BIOS 2001. Automatic power-on after AC restoration was confirmed by a physical test, followed by verified SSH access, Hyprland startup, and all three Kubernetes nodes `Ready`. The relevant firmware option is **Restore AC Power Loss → Power On**; Ansible does not manage this setting.
- `socrat-1`: HONOR BRN-HXX, BIOS 1.13. Automatic power-on when AC is attached has not been confirmed for this model. Check available firmware settings locally. While the battery supplies power, switching off the smart socket does not shut down the laptop.

The managed logind override changes only external-power and docked lid handling. While caffeine mode is enabled, its separate lid inhibitor also applies on battery; disabling caffeine restores the underlying logind policy.

### Controlled verification and recovery

First inspect the prepared configuration without interrupting the session:

```bash
systemctl show getty@tty1.service --property=ExecStart
systemctl is-enabled wg-quick@wg-socrat.service
loginctl show-user alchemmist --property=Linger
```

Check `ssh.service` and `k3s.service` on `socrat-0`, or `sshd.service` and `k3s.service` on `socrat-1`, with both `systemctl is-enabled` and `systemctl is-active`. For the laptop also check `NetworkManager.service`. The effective getty command must contain `--autologin alchemmist`, and user lingering must be `yes`.

After agreeing on a maintenance test, reboot one home node at a time. Start with `socrat-1`, verify fresh SSH access through the normal alias, local Hyprland startup without a selector, WireGuard connectivity, Kubernetes `Ready`, and absence of `DiskPressure`. Confirm the `socrat-1` backup folder stays paused. Rebooting `socrat-0` still interrupts NFS and the public SSH relay. The [HA migration](k3s-ha.md) adds a second home API server, a third etcd voter on the VPS, and redundant ingress; verify the router cutover and two remaining healthy voters before planning that test. A reboot test does not verify firmware behavior after loss of mains power; that needs a separate controlled test.

If the graphical session fails, use SSH or log into tty2 with the normal account password. Inspect `journalctl -b -u getty@tty1.service` and the managed launcher/profile. To disable automatic local login, remove `/etc/systemd/system/getty@tty1.service.d/50-homelab-autologin.conf` and run `sudo systemctl daemon-reload`; leave the active getty alone until a planned restart. Set `homelab_desktop_autologin: false` in inventory before rerunning Ansible to avoid reinstalling the drop-in; this flag skips the role and does not remove an existing configuration by itself. Restore individual profile contents into the node-local files from the timestamped backup if necessary; do not reconnect managed paths to personal dotfiles. The isolation manifest records original paths for inspection. Reinstall removed Sway packages only if deliberately reverting to the previous desktop setup.

The caffeine setup runs Hyprlock in a separate transient user service (`homelab-hyprlock`) so stopping Hypridle cannot terminate an active lockscreen. Avoid launching the locker as an unmanaged child of `hypridle.service`.


### Graceful shutdown with local NFS

The `node_shutdown` role and `playbooks/node-shutdown.yml` configure graceful Kubernetes shutdown for opted-in nodes. On `socrat-0`, the settings give kubelet a 60-second total shutdown window, including 10 seconds reserved for critical pods. They are written to `/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/80-homelab-shutdown.conf`. The k3s service also gains `Wants=nfs-server.service` and `After=nfs-server.service` so local NFS remains available until k3s stops. Kubelet's shutdown handling is needed in addition to service ordering to terminate pods while storage is still available.

This addresses a likely storage teardown race observed during shutdown: local NFS stopped before k3s, while the LMS Uvicorn process using SQLite on a hard-mounted NFS volume remained present after SIGKILL. The old kernel stack was not captured, so the exact blocked syscall is unconfirmed. The configuration was applied on 2026-10-14 and verified through kubelet configz and the active logind shutdown inhibitor; all three nodes returned `Ready`. No shutdown or reboot test has been performed for this fix.

Apply from `ansible/` during an agreed maintenance window:

```bash
ansible-playbook playbooks/node-shutdown.yml --limit socrat-0 --ask-become-pass
```

A changed configuration restarts k3s. After application, inspect kubelet's effective configuration for `shutdownGracePeriod: 60s` and `shutdownGracePeriodCriticalPods: 10s`, verify a kubelet shutdown delay inhibitor is registered with logind, and check `systemctl show k3s.service --property=After --property=Wants`. Confirm cluster recovery before arranging a separate shutdown test. During that test, record pod termination, NFS stop ordering, and total shutdown duration; application and idempotence checks alone cannot establish that the shutdown stall is fixed.

The monitor launcher sets all btm graph windows and retention to `homelab_monitor_window_seconds` (600 seconds by default). The role preserves bottom appearance/layout settings while setting descending sorts: temperature by `Temperature`, processes by `CPU%`, and disks by `Used` (occupied bytes, not percentage). Changed monitor settings restart only panes currently running btm in the managed tmux session; shells and other panes are left running. Reapply with `ansible-playbook playbooks/desktop.yml --tags monitor --limit socrat-0,socrat-1 --ask-become-pass`.

On `socrat-1`, workspace 1 (the monitoring terminal) is bound to the external `HDMI-A-1` display and is its default workspace. This keeps the monitor visible when the laptop lid is closed.

`desktop_terminal` sets `[window] opacity = 0.0` in Alacritty by default on all desktop nodes, including newly added ones. Override `homelab_alacritty_opacity` in host variables if needed. Font size, theme imports, and key bindings are preserved in node-local configuration; links into personal dotfiles are materialized before editing. The font family is managed as described below.

Alacritty also has `window.blur = false`; the shared Hyprland template explicitly disables compositor blur for Alacritty and `homelab-monitor` windows.


### Workspaces and application startup

The shared Hyprland configuration explicitly sets `persistent:false` for workspaces 1–10 to clear persistence left by the earlier live configuration. Win+1 through Win+0 selects or creates the corresponding workspace. Waybar uses an empty `persistent-workspaces` map and `all-outputs:false`, showing occupied/current workspaces for each output rather than a fixed list of empty workspaces. On `socrat-1`, workspace 1 remains assigned to external `HDMI-A-1`.

Personal browsers, Telegram, and Obsidian were removed from automatic startup; the monitor terminal is the only application window opened by the managed baseline. Desktop background services still start normally. Existing application windows are not closed by this change. Isolation has been applied on both home nodes, and the new Hyprland configuration passes native validation; live workspace creation/removal and unchanged restored Dotfiles sources have been verified, without a reboot.

### Terminal font availability

`desktop_terminal` explicitly configures `FiraCode Nerd Font Propo` for normal, bold, italic, and bold-italic faces. It checks fontconfig as the desktop user so an existing per-user installation is recognized. When missing, it installs the pinned Nerd Fonts 3.5.1 FiraCode archive with SHA-256 verification under `/usr/local/share/fonts/homelab-firacode-nerd`, refreshes the font cache, and rejects fallback to a different family. Existing working font installations are retained.

Apply with `ansible-playbook playbooks/desktop.yml --tags alacritty --limit socrat-0,socrat-1 --ask-become-pass`. An Alacritty process started before a missing font was installed may need to be reopened; attaching its existing tmux session preserves running shells and monitors. On socrat-1 the original missing Nerd Font caused fontconfig to substitute proportional Noto Sans, which produced uneven spacing in terminal cells.
