# Socrat cluster notes

Compact operational notes for the `Socrat` homelab Kubernetes cluster. This file captures current architecture, key decisions, and non-obvious operational details. Do not put secrets here.

## Identity and source of truth

- Cluster name: `Socrat`.
- Node names stay lowercase:
  - `socrat-0`
  - `socrat-1`
  - `socrat-2`
- Public repo/source of truth: <https://github.com/alchemmist/homelab>.
- Main local repo path: `~/code/homelab`.
- Infrastructure is managed mostly by Ansible + Helm charts from this repo.
- Rancher/UI edits are considered temporary unless reflected in repo values/scripts.
- Do not commit secrets, kubeconfigs, private WireGuard keys, password hashes, bot tokens, or GHCR tokens.

## Nodes

| Node | Role | Notes |
|---|---|---|
| `socrat-0` | k3s control plane + etcd, home ingress, NFS server | First home API server and etcd voter; NFS shared storage remains local. |
| `socrat-1` | k3s control plane + etcd, home ingress | Second home API server and etcd voter; MDB backup folder stays paused. |
| `socrat-2` | k3s etcd-only server + agent / VPS edge | Third etcd voter, no local Kubernetes API; runs edge workloads. |

Current important addresses:

```text
socrat-0 LAN: 192.168.0.23
socrat-1 LAN: 192.168.0.24
socrat-2 public: 176.98.185.59
home public: 109.173.40.247
```

## Home node boot and desktop recovery

`ansible/playbooks/desktop.yml` now defines automatic local tty1 login as `alchemmist` and direct Hyprland startup for `socrat-0` and `socrat-1`. The `node_boot` role keeps existing networking, SSH, WireGuard, and k3s services enabled independently of desktop login, orders k3s after WireGuard, and retries WireGuard startup failures. User lingering remains enabled.

On `socrat-1`, the managed setup archives the old session selector and installed Sway configuration paths, removes Sway and unused helpers, and removes the Hypridle listener that powered the laptop off after 30 minutes. Hyprland, swaync, fzf, and dimming/locking remain. The underlying logind policy ignores lid closure on external power or while docked; its battery policy is unchanged. User configuration backups live in `~/.local/state/homelab/desktop-backups/<timestamp>/`.

Applied on both home nodes on 2026-10-14. The repeat Ansible run completed with `changed=0` and no failures on both nodes; all 20 local tests passed. Existing Hyprland process IDs remained unchanged, all three Kubernetes nodes stayed `Ready`, and `socrat-1` retained 19 GiB free with `DiskPressure=False` and its backup folder paused. These changes did not restart the active desktop or logind. The user subsequently rebooted `socrat-1` and confirmed automatic login and Hyprland startup; fresh SSH access and uptime were verified. The user also completed a physical AC power restoration experiment on `socrat-0`: the machine powered on automatically; subsequent SSH access, Hyprland startup, and all three Kubernetes nodes `Ready` were verified. Automatic AC recovery therefore works on this ASUS PRIME X299-A II; Ansible does not manage its firmware setting. Equivalent AC-attach startup support on the HONOR BRN-HXX laptop is unconfirmed; its battery also means cutting smart-socket power does not switch it off.

`socrat-1` now opts into `homelab_desktop_caffeine_default: true`: each Hyprland session invokes `~/scripts/caffeine-manager.sh --enable` instead of starting Hypridle. This enables the existing Waybar caffeine mode by default: Hypridle stops and `caffeine-lid-inhibit.service` starts. Idle dimming/locking is inactive, and lid closure is inhibited even on battery while the mode is on. The Waybar toggle remains available; disabling caffeine resumes Hypridle, and a new graphical session enables caffeine again. Explicit `--enable` and `--disable` commands allow setting the mode without toggling.

See [the boot and recovery runbook](node-bootstrap.md#automatic-boot-and-local-desktop) for application, validation, and rollback. The later [HA migration](k3s-ha.md) adds a second control plane and redundant home ingress. NFS and the public SSH relay remain dependent on `socrat-0`.

Caffeine was enabled live on `socrat-1` on 2026-10-14. The first activation exposed a lifecycle bug: Hypridle had launched Hyprlock inside its own service cgroup, so stopping Hypridle also terminated the active locker and triggered Hyprland's crashed-lockscreen screen. The desktop was recovered without restarting Hyprland. The managed `lock_cmd` now launches Hyprlock via `systemd-run --user --collect --unit=homelab-hyprlock`, keeping its lifecycle independent of Hypridle. Caffeine remains enabled at graphical startup and can still be toggled from Waybar.

## Shared desktop configuration refactor

The desktop roles now separate console login (`desktop_session`), Hyprland and idle/caffeine behavior (`desktop_environment`), Waybar (`desktop_panel`), and the monitor terminal (`desktop_terminal`). Common templates use desktop/laptop profiles with monitor layouts, extra rules, and startup applications in `ansible/inventory/host_vars/socrat-0.yml` and `socrat-1.yml`. Local Hyprland overrides belong in `~/.config/hypr/local.conf`.

Homelab configuration is now isolated from personal dotfiles. `node_config_isolation` runs before desktop roles, including tagged runs, and materializes linked Hyprland, Waybar, Alacritty, managed script, tmux/login, and caffeine-unit paths as node-local files. Backups and their manifest are retained under `~/.local/state/homelab/config-isolation/`. The initial rollout's edits through symlinks were corrected: 15 dotfiles source files were restored from exact pre-change backups (seven on `socrat-0`, eight on `socrat-1`), while unrelated original modifications were retained. No claim is made that these personal worktrees are clean; homelab does not deploy or push them.

`desktop_environment` owns the caffeine manager, inhibitor unit, and Hypridle configuration instead of patching the previous files. Laptop caffeine still defaults on, with manual Waybar toggling and an independent Hyprlock service. Common Waybar JSON/CSS preserves the host-specific modules; the Flameshot tray icon is hidden only on `socrat-0`. Existing personal application shortcuts and optional external helpers remain dependencies outside the managed baseline.

`desktop_terminal` installs Alacritty, tmux, and zsh and uses bottom 0.14.9 or newer at `/usr/bin/btm`, installing the distribution package when that binary is absent. Its tables sort temperature, process CPU usage, and used disk space in descending order. `/usr/local/bin/homelab-monitor-terminal` opens the `tmp` tmux session with a monitor window running zsh and `btm`. Existing tmux configuration is retained, with optional popup-table unbind commands changed to quiet mode to avoid missing-table errors.

`wallpaper_asset` delivers the image from `socrat-0` to `/usr/local/share/wallpapers/homelab/default.png` on all three nodes through `base.yml`, `site.yml`, and `desktop.yml`. Home desktop and lockscreen configuration uses this asset; the VPS receives no GUI setup. The roles assume an installed graphical environment, including Hyprland, `start-hyprland`, and `awww`; they do not install every application referenced by personal shortcuts.

The shared desktop refactor was applied on 2026-10-14. Both Hyprland configs passed native validation and report no live config errors. The same wallpaper asset exists on all three nodes and is active on the two graphical nodes. Both have one tmp session/window running btm; socrat-0 Flameshot is running with its tray icon disabled. Live screenshots were checked, Hyprland processes remained running, and all three Kubernetes nodes are Ready. The repository test suite passed all 48 tests. No reboot was performed for this cosmetic rollout.

The latest workspace configuration clears persistent flags for workspaces 1–10, and Waybar uses an empty persistent-workspace map with `all-outputs:false`. It shows occupied/current workspaces per output; Win+1 through Win+0 creates or selects workspaces as needed. Workspace 1 remains assigned to the external display on `socrat-1`. Browser, Telegram, and Obsidian autostart entries were removed so new sessions open only the monitor application window, alongside normal desktop background services. Already open windows are left untouched.

Configuration isolation is applied on both home nodes. Native Hyprland validation still passes; live workspace creation/removal and unchanged restored Dotfiles sources have been verified. No reboot was performed for these changes.

## socrat-0 shutdown delay investigation

The latest inspected shutdown journal (boot ID beginning `f7347a2`) records power-off starting at uptime 109.845 seconds, NFS stopping at 110.511 seconds, and k3s stopping at 112.09 seconds. The LMS Uvicorn process (PID 10058, container ID beginning `6727384`) received SIGKILL at 199.942 seconds but was still present around 290.192 seconds. The journal ends at 290.443 seconds; the user's additional observed waiting time is not captured there.

LMS uses SQLite under `/data`, backed by a hard-mounted NFS volume served by the same node. Effective kubelet settings were `shutdownGracePeriod=0` and `shutdownGracePeriodCriticalPods=0`, with no kubelet shutdown inhibitor. NFS stopping before pod cleanup is a strong explanation for the stall, but no kernel stack from the blocked process was captured, so the specific blocking syscall is not established.

The applied `node_shutdown` role and `ansible/playbooks/node-shutdown.yml` configure `socrat-0` with a 60-second kubelet shutdown window, including 10 seconds for critical pods, in `80-homelab-shutdown.conf`. A k3s systemd drop-in adds `Wants=nfs-server.service` and `After=nfs-server.service` to preserve local NFS until k3s stops. Applied on 2026-10-14 with a k3s service restart. Effective config reports `shutdownGracePeriod=1m0s` and `shutdownGracePeriodCriticalPods=10s`; logind has a kubelet shutdown delay inhibitor and `InhibitDelayMaxUSec=60000000`. All three nodes are `Ready`, LMS is running, and Hyprland remained running. A controlled shutdown/reboot test of the fix remains outstanding.

## WireGuard management mesh

System WireGuard interface: `wg-socrat`.

Purpose:

- Kubernetes/node management network.
- k3s/flannel transport.
- Node-to-node service access.
- Separate from 3x-ui user VPN.

Addresses:

```text
socrat-0: 10.250.0.1
socrat-2: 10.250.0.2
socrat-1: 10.250.0.3
```

Ansible now manages the public topology and per-node config rendering:

```text
ansible/playbooks/wireguard.yml
ansible/roles/wireguard_socrat/
ansible/inventory/group_vars/Socrat.yml
```

Private keys are kept on nodes and are not committed. The role preserves existing private keys, generates a new one only if absent, renders `/etc/wireguard/wg-socrat.conf`, starts/enables `wg-quick@wg-socrat`, applies peer changes with `wg syncconf`, and verifies public keys against inventory.

Run:

```bash
cd ~/code/homelab/ansible
ansible-playbook playbooks/wireguard.yml -e ansible_become_password=...
```

## k3s and flannel

Important decision: flannel must run over `wg-socrat`.

Root cause fixed earlier: `socrat-0` and `socrat-2` had asymmetric flannel interface selection, breaking pod overlay traffic to `socrat-2`. Now k3s server and agents use:

```bash
--flannel-iface wg-socrat
```

For already-installed agents, `ansible/playbooks/k3s-agent-network.yml` manages `/etc/rancher/k3s/config.yaml.d/20-homelab-network.yaml` and restarts the agent only when needed. The main k3s playbook runs the same role before agent installation, so its `creates: /usr/local/bin/k3s` shortcut no longer skips network configuration on existing nodes. This corrected `socrat-1` advertising its Wi-Fi address as the VXLAN endpoint instead of `10.250.0.3`.

The canonical existing-cluster playbook is now `ansible/playbooks/k3s-ha.yml`; `k3s.yml` refuses the legacy topology while `k3s_ha_enabled` is true. All nodes use `v1.36.5+k3s1`. The VPS has direct WireGuard routes to both home node LAN addresses for etcd peer reachability. See [HA operations and recovery](k3s-ha.md).

Expected flannel local endpoints:

```text
socrat-0 flannel.1 local 10.250.0.1 dev wg-socrat
socrat-1 flannel.1 local 10.250.0.3 dev wg-socrat
socrat-2 flannel.1 local 10.250.0.2 dev wg-socrat
```

For future nodes: bring up `wg-socrat` first, then join k3s with WG node IP and `--flannel-iface wg-socrat`.

## Ingress, TLS, and public exposure

- Use default k3s Traefik, not ingress-nginx.
- Use cert-manager HTTP-01 for TLS.
- Home ingress is being configured with two Traefik replicas and a keepalived VIP (`192.168.0.250`) on `socrat-0`/`socrat-1`; router cutover and failure verification are tracked in [the HA runbook](k3s-ha.md).
- Avoid host-level Caddy on home Socrat nodes.
- `vpn.alchemmist.xyz` edge routing is handled by Kubernetes Ingress and the `traefik-edge` controller on `socrat-2`; the Caddy release has been removed.

Rancher:

```text
https://rancher.socrat.alchemmist.xyz
```

Rancher has two replicas, one each on `socrat-0` and `socrat-1`, managed by `ansible/playbooks/rancher-placement.yml`. Required hostname anti-affinity keeps them separate; the VPS is excluded. Both home nodes now run Kubernetes API servers, backed by three etcd voters including the VPS. Home ingress redundancy requires the VIP and router cutover described in [the HA runbook](k3s-ha.md).

Uptime Kuma / status:

```text
https://status.alchemmist.xyz/
https://status.alchemmist.xyz/dashboard
https://status.alchemmist.xyz/status/socrat
```

The root status URL is implemented via Uptime Kuma `status_page_cname` mapping for `status.alchemmist.xyz`.

## Storage

### NFS shared storage

Current default StorageClass:

```text
nfs-shared
```

Backed by `socrat-0`:

```text
/srv/k8s-nfs
```

Relevant playbook:

```text
ansible/playbooks/storage-nfs.yml
```

Notes:

- `nfs-shared` is default for new PVCs.
- `local-path` is no longer default.
- This fixes local-path node affinity for recreated stateful apps.
- It is not fully HA: `socrat-0` remains storage SPOF.

Longhorn was tried and removed due readiness/CSI problems, especially around `socrat-2`/kubelet/proxy conditions. Can be retried later after network/storage stabilization.

### App state

Do not use Syncthing as live Kubernetes storage for databases/PVCs. Use PVC/NFS now, and maybe Longhorn/Ceph later.

## Syncthing

Syncthing is Kubernetes-managed as a DaemonSet: one pod per Socrat node.

Chart:

```text
charts/syncthing
```

Preparation role/playbook:

```text
ansible/roles/syncthing_node
ansible/playbooks/syncthing-nodes.yml
```

The role disables legacy host/user Syncthing services so they do not collide with Kubernetes-managed Syncthing on ports `8384`, `22000`, `21027`, and ensures `/srv/syncthing` exists.

DaemonSet details:

- `hostNetwork: true`
- `dnsPolicy: Default`
- hostPath: `/srv/syncthing`
- GUI backend: `127.0.0.1:8384`; private HTTPS is delivered on WireGuard TCP 443.
- sync TCP/QUIC port: `22000`
- discovery UDP port: `21027`

Important config decision:

- Syncthing listen addresses are forced to:

```text
tcp://0.0.0.0:22000
quic://0.0.0.0:22000
dynamic+https://relays.syncthing.net/endpoint
```

This fixed the case where `socrat-1` listened on random `44315`, so peers saw it as disconnected.

Node GUI endpoints:

```text
https://0.socrat.alchemmist.xyz/sync/ -> socrat-0 local Syncthing
https://1.socrat.alchemmist.xyz/sync/ -> socrat-1 local Syncthing
https://2.socrat.alchemmist.xyz/sync/ -> socrat-2 local Syncthing
```

These interfaces are private to the WireGuard mesh and retain the existing BasicAuth credentials. Public `sync-*` ingresses are removed. A node-local nginx sidecar proxies to loopback; Ansible owns narrowly scoped WireGuard HTTPS routing. See [the private UI runbook](syncthing-private-ui.md) for deployment, certificate renewal and recovery. Device identities and folder pause states were retained during migration.

### Syncthing philosophy

Syncthing is acceptable for homelab utility sync:

- encrypted backup archives
- notes/knowledge base
- static artifacts
- node-local convenience files

It is not a Kubernetes ReadWriteMany storage layer and should not be used for live DB directories or active app state.

Good: syncing encrypted MDB backup archives.
Bad: syncing live SQLite/Postgres data dirs.

### MDB backups folder

Configurator:

```text
ansible/files/configure_syncthing_pg_backups.py
ansible/playbooks/syncthing-backups.yml
```

Folder:

```text
id: pg-mdb-backups
label: pg-mdb-encrypted-backups
path inside container: /var/syncthing/pg_mdb_encrypted_backups
host path: /srv/syncthing/pg_mdb_encrypted_backups
```

Current intent:

- `socrat-0`: full copy/source/peer.
- `socrat-1`: existing receive-only copy is preserved, but `pg-mdb-backups` is paused to preserve system disk reserve. Other Syncthing folders remain enabled.
- `socrat-2`: folder is paused because VPS disk is too small.
- Mac participates as backup source/peer.
- Phone should not be treated as a meaningful peer on `socrat-1`/`socrat-2` unless a shared folder actually involves it.

### socrat-1 disk reserve

`ansible/playbooks/node-disk-reserve.yml` pauses only `pg-mdb-backups` and applies the node-specific kubelet settings from inventory. It does not delete backup archives. The hard free-space threshold is 10 GiB; the soft threshold is 15 GiB with a two-minute grace period. Image garbage collection uses high/low usage thresholds of 96%/95%. Memory and inode safeguards remain configured.

The managed kubelet drop-in is `/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/99-homelab-disk-reserve.conf`. The helper backs up existing configuration before changing it and restarts the configured Kubernetes service (`k3s.service` after HA promotion) only when the kubelet configuration changes. `site.yml` includes this policy for nodes that define it. The general backup-folder configurator also keeps this folder paused on `socrat-1`, so a later Ansible run does not resume downloads accidentally.

Before HA migration, seven duplicate encrypted MDB archives were removed only on `socrat-1`, after verifying copies on the Mac and `socrat-0`. This freed 37.95 GiB; the HA preflight retained over 40 GiB free. No Mac archives were deleted.

Current `socrat-1` Syncthing device ID:

```text
OD2HKB5-475B6AK-IWP4H5S-UUMQTMX-3LCMY66-AVY3YME-HRHKCAL-VGW7BAP
```

Old `socrat-1` ID removed from configs:

```text
DYWEDAX-RDGBCC3-4AUXREZ-WGQLZJU-TT3HWIQ-2CSUQSE-WF2WVVH-4VV2IAP
```

## Uptime Kuma

Uptime Kuma remains one active replica on `socrat-2`, with its complete data directory at `/srv/uptime-kuma`. Do not scale it to multiple active replicas against the same SQLite database. The attempted move to `socrat-1` was rolled back after disk pressure and the requirement changed to multi-site availability. An inactive data copy remains on `socrat-1`; it is not served or shared with the active database. `ansible/playbooks/uptime-kuma-placement.yml` is an explicit migration tool with stopped-writer transfer, archive SHA256 and SQLite table-count verification; it is not included in normal deployment. The Syncthing monitor maintenance play continues to target `socrat-2`.

Chart:

```text
charts/uptime-kuma
```

Data:

```text
/srv/uptime-kuma/kuma.db
```

Status page source files:

```text
charts/uptime-kuma/status-page/socrat-status.css
charts/uptime-kuma/status-page/prototype-openai-minimal.css
charts/uptime-kuma/status-page/socrat-avatar.png
scripts/apply-uptime-kuma-status-page.py
scripts/update-uptime-kuma-syncthing-group.py
```

Design:

- minimalist OpenAI-like status page
- avatar/title lockup
- flat rows
- uptime bars
- no footer/powered-by
- no accordion/folded cards
- hover effects disabled on mini uptime bars
- root URL serves public page via CNAME mapping

Current status groups:

```text
Socrat core
Socrat apps
Syncthing
VPN and edge
GitHub Pages projects
```

Syncthing monitors are direct WG checks, not public ingress checks:

```text
Syncthing sync-0: GET http://10.250.0.1:18444/healthz
Syncthing sync-1: GET http://10.250.0.3:18444/healthz
Syncthing sync-2: GET http://10.250.0.2:18444/healthz
```

The private health listener proxies Syncthing `/rest/noauth/health` and accepts only HTTP 200. Other paths return 404; the GUI/API itself is not exposed through that listener. The monitor migration backs up Kuma locally and preserves unrelated monitor configuration.

## GHCR images

Local app images were moved to GHCR to avoid `ErrImageNeverPull` during failover.

Images:

```text
ghcr.io/alchemmist/homelab-blog:latest
ghcr.io/alchemmist/homelab-socrat-home:latest
ghcr.io/alchemmist/homelab-lms:latest
ghcr.io/alchemmist/homelab-format-quorum:latest
ghcr.io/alchemmist/homelab-monori-front:latest
ghcr.io/alchemmist/homelab-monori-back:latest
ghcr.io/alchemmist/homelab-monori-sync:latest
```

Pull secret:

```text
ghcr-pull
```

Namespaces:

```text
blog
socrat-home
lms
format-quorum
monori
```

Token is not committed.

## Apps and placement

Apps migrated/managed with Helm through Ansible:

```text
blog
cats
img-proxy
lms
format-quorum
syncthing
remark42
umami
monori
uptime-kuma
x-ui
```

Main deploy command:

```bash
cd ~/code/homelab/ansible
ansible-playbook playbooks/apps.yml -e ansible_become_password=...
```

`cats` currently has a temporary exclusion from `socrat-2` because it was used as a workaround while pod overlay to `socrat-2` was broken. Since flannel over WG is fixed, this exclusion can be reconsidered later.

## Edge/VPS workloads on `socrat-2`

Use `socrat-2` for workloads that need public/VPS reachability:

- `x-ui` / one Deployment containing primary and compatibility 3x-ui/Xray runtimes
- `traefik-edge` / Kubernetes Ingress for `vpn.alchemmist.xyz:80/443`
- `remark42`

Uptime Kuma remains on `socrat-2` with local data while multi-site status availability is being designed.

These often use:

```yaml
hostNetwork: true
dnsPolicy: Default
```

This pattern fixed DNS problems for hostNetwork pods.

`traefik-edge` replaced Caddy on 2026-10-14. It runs as a hostNetwork pod on `socrat-2`, routes Kubernetes Ingress to local x-ui/xray endpoints over the node WireGuard address, and uses cert-manager for TLS. Home Traefik watches only class `traefik`; the VPS controller watches class `traefik-edge`. The VPS controller now reaches the API through the standard k3s agent load balancer at `https://127.0.0.1:6444`, which has both home API servers as backends. See [the migration and verification notes](vpn-cutover.md#traefik-vps-ingress-migration).

`traefik-edge` and `storage` are infrastructure namespaces. `playbooks/rancher-namespaces.yml` marks them with `management.cattle.io/system-namespace=true` to exclude them from Rancher’s **Only User Namespaces** view. Their workloads, project membership and RBAC stay in place.

## 3x-ui / VPN

Managed configuration:

- Kubernetes release, namespace and Deployment `x-ui` run on `socrat-2` with two containers. `primary` uses the pinned 3.10.0 image and `/srv/x-ui-lab/db`.
- `compatibility` preserves legacy ports and clients with the pinned 3.9.0 image, `/etc/x-ui`, and the existing Xray assets. The two databases stay separate. The old directory names are intentionally retained.
- `playbooks/vpn-consolidate.yml` migrates the former `x-ui-lab` and `x-ui-legacy` releases with watchdog inhibition, private backups, configuration/subscription comparison, an authenticated tunnel probe and rollback of workload settings on failure. The 2026-10-15 migration preserved all 31 subscriptions and 155 normalized links and passed authenticated VPN probes before and after cutover. Both former namespaces were removed; see the migration record for the private backup location.
- Production subscription/Traefik routes point to Kubernetes-managed x-ui.
- Native host `x-ui.service` is stopped/disabled. The emergency Docker container is stopped with restart policy `no`. The cutover preserved client settings, ports, and subscription URLs; no subscription update is required.
- Deployment, retained legacy ports, backups, and rollback are documented in [vpn-cutover.md](vpn-cutover.md).
- Both Docker Caddy and the `caddy-edge` Helm release have been removed. `traefik-edge` owns public TCP 80/443 and UDP 443 in Kubernetes.

Important paths on `socrat-2`:

```text
/etc/x-ui
/srv/x-ui/db
/srv/x-ui/cert
/srv/x-ui/acme
/srv/x-ui-lab/db
/srv/x-ui-lab/cert
/srv/x-ui-lab/acme
/srv/caddy/data
/srv/caddy/config
```

Containerized ports:

```text
panel:        18082
subscription: 12096
vless main:   32053
vless xhttp:  32083
vless plain:  32063
vless grpc:   32084
wireguard:    32085/udp
amneziawg:    32086/udp
trojan:       32087
```

Recommended user profile: Trojan over 443 via `vpn.alchemmist.xyz`, because high ports can fail on client networks.

## Remark42

- Runs on `socrat-2`.
- `hostNetwork: true`, `dnsPolicy: Default`.
- Data path: `/srv/remark42`.
- Telegram/blog notification bot is `@alchemmist_notify_bot`.
- That bot is only for Remark42/blog notifications, not cluster ops.
- Token lives only in Kubernetes Secret.

## Future cluster bot

Future bot:

```text
socrat_cluster_bot
https://t.me/socrat_cluster_bot
```

Intended use:

- Uptime Kuma webhooks
- cluster alerts
- admin actions
- VPN broadcast groups

Do not reuse `@alchemmist_notify_bot` for ops.

## Important operational lessons

- Do not delete `/home/www/.ssh`-style SSH state blindly; previous incident broke SSH.
- Do not partially patch sensitive Kubernetes Secrets; recreate fully when removing keys.
- For hostNetwork pods, prefer `dnsPolicy: Default` unless there is a strong reason not to.
- For k3s/flannel, WG interface selection is critical.
- Uptime Kuma `stats` vs `status` typo previously broke cert issuance; correct domain is `status.alchemmist.xyz`.
- Longhorn was attempted and removed; do not assume it is currently available.
- NFS needed inotify sysctl fix:

```text
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches = 1048576
```

## Host Docker policy

Docker is installed on every node as an emergency/manual tool, but it is not a workload runtime for Socrat services.

Expected default state on every node:

```text
docker.service: inactive/disabled
docker.socket: inactive/disabled
containerd.service: inactive/disabled
```

Kubernetes uses k3s-managed containerd internally. Application workloads should run through Kubernetes, not host Docker. If Docker is started manually for an experiment, stop it afterwards and do not leave containers running on the host.

## Cleanup done on `socrat-1`

`socrat-1` disk was cleaned to make room for MDB backups:

- Docker storage cleaned by user.
- ROCm removed through pacman.
- LM Studio package removed through pacman.
- Pacman orphan packages removed.

After cleanup, there was enough space for the current MDB backup mirror, but remaining free space after full sync is expected to be limited. Monitor disk pressure.

## Useful commands

Nodes:

```bash
ssh socrat-0
ssh socrat-1
ssh socrat-2
```

Cluster:

```bash
ssh socrat-0 'sudo k3s kubectl get nodes -o wide'
ssh socrat-0 'sudo k3s kubectl get pods -A -o wide'
```

WireGuard:

```bash
ssh socrat-0 'sudo wg show wg-socrat'
ssh socrat-1 'sudo wg show wg-socrat'
ssh socrat-2 'sudo wg show wg-socrat'
```

Syncthing:

```bash
ssh socrat-0 'sudo k3s kubectl -n syncthing get ds,pod,svc,endpoints,ingress -o wide'
ssh socrat-1 'du -sh /srv/syncthing/pg_mdb_encrypted_backups; df -h /'
```

Uptime Kuma DB status example:

```bash
ssh socrat-2 "sqlite3 -header -column /srv/uptime-kuma/kuma.db \"select m.name,m.method,m.timeout,h.status,h.msg,h.time from monitor m left join heartbeat h on h.id=(select id from heartbeat where monitor_id=m.id order by time desc limit 1) where m.name like 'Syncthing sync-%' order by m.name;\""
```

Apply status page styling:

```bash
sudo python3 scripts/apply-uptime-kuma-status-page.py \
  --db /srv/uptime-kuma/kuma.db \
  --css charts/uptime-kuma/status-page/socrat-status.css \
  --icon charts/uptime-kuma/status-page/socrat-avatar.png
```

## Open items

- Perform a controlled shutdown test of the applied `socrat-0` graceful shutdown configuration. Automatic AC power restoration already works on `socrat-0`; equivalent firmware behavior on `socrat-1` remains unverified.

- Decide whether to remove `cats` temporary exclusion from `socrat-2`.
- Monitor `socrat-1` MDB backup sync and disk free space.
- Decide whether `phone` should be removed from `socrat-1`/`socrat-2` Syncthing configs unless it shares a real folder with them.
- Add backup strategy for `/srv/k8s-nfs`.
- Consider object storage/restic as canonical long-term backup sink for MDB backups.
- Consider retrying Longhorn or another CSI storage backend later.
- Long-term: replace host-level NFS server with a more Kubernetes-native replicated storage backend if true HA is needed.
- Implement `socrat_cluster_bot` later.

Dynamic workspace verification passed on both home nodes: selecting an unused workspace created it and returning removed the empty workspace. Repeated scoped Ansible check reported `changed=0` and no errors. Seventeen Ansible backup artifacts were moved out of the remote Dotfiles checkouts into the node-local isolation archive.
