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
| `socrat-0` | k3s control-plane, home ingress, NFS server | Main home node, Traefik pinned here, NFS shared storage lives here. |
| `socrat-1` | k3s worker | Home node, Arch Linux, now back online. Syncthing receives MDB backups. |
| `socrat-2` | k3s worker / VPS edge | Former `laba`, public VPS. Runs public/edge workloads needing VPS reachability. |

Current important addresses:

```text
socrat-0 LAN: 192.168.0.23
socrat-1 LAN: 192.168.0.24
socrat-2 public: 176.98.185.59
home public: 109.173.40.247
```

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

Relevant playbook:

```text
ansible/playbooks/k3s.yml
```

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
- Traefik is pinned to `socrat-0` for stable home ingress.
- Avoid host-level Caddy on home Socrat nodes.
- `vpn.alchemmist.xyz` edge routing is now handled by Kubernetes release `caddy-edge` on `socrat-2`, not host Docker Caddy.

Rancher:

```text
https://rancher.socrat.alchemmist.xyz
```

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
- GUI port: `8384`
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
sync-0.alchemmist.xyz -> 10.250.0.1:8384
sync-1.alchemmist.xyz -> 10.250.0.3:8384
sync-2.alchemmist.xyz -> 10.250.0.2:8384
```

These are behind Traefik/basic auth publicly. Direct node-local checks use WG IPs.

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
- `socrat-1`: receive-only copy; has enough disk for current full set with limited spare.
- `socrat-2`: folder is paused because VPS disk is too small.
- Mac participates as backup source/peer.
- Phone should not be treated as a meaningful peer on `socrat-1`/`socrat-2` unless a shared folder actually involves it.

Current `socrat-1` Syncthing device ID:

```text
OD2HKB5-475B6AK-IWP4H5S-UUMQTMX-3LCMY66-AVY3YME-HRHKCAL-VGW7BAP
```

Old `socrat-1` ID removed from configs:

```text
DYWEDAX-RDGBCC3-4AUXREZ-WGQLZJU-TT3HWIQ-2CSUQSE-WF2WVVH-4VV2IAP
```

## Uptime Kuma

Uptime Kuma is deployed as a single replica. Do not scale to 3 active replicas: it uses SQLite and is not safe as an active-active app.

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
Syncthing sync-0: HEAD http://10.250.0.1:8384/
Syncthing sync-1: HEAD http://10.250.0.3:8384/
Syncthing sync-2: HEAD http://10.250.0.2:8384/
```

Using HEAD + 30s timeout avoids false timeouts from downloading the whole Syncthing UI while nodes are busy syncing large backups.

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
x-ui-lab
```

Main deploy command:

```bash
cd ~/code/homelab/ansible
ansible-playbook playbooks/apps.yml -e ansible_become_password=...
```

`cats` currently has a temporary exclusion from `socrat-2` because it was used as a workaround while pod overlay to `socrat-2` was broken. Since flannel over WG is fixed, this exclusion can be reconsidered later.

## Edge/VPS workloads on `socrat-2`

Use `socrat-2` for workloads that need public/VPS reachability:

- `x-ui-lab` / containerized 3x-ui/xray
- `caddy-edge` / Kubernetes-managed Caddy for `vpn.alchemmist.xyz:80/443`
- `remark42`
- `uptime-kuma`

These often use:

```yaml
hostNetwork: true
dnsPolicy: Default
```

This pattern fixed DNS problems for hostNetwork pods.

`caddy-edge` replaced the former Docker Caddy container. It runs as a hostNetwork pod on `socrat-2` and proxies `vpn.alchemmist.xyz` traffic to the Kubernetes-managed x-ui/xray listeners on localhost/new ports.

## 3x-ui / VPN

Current state:

- Containerized 3x-ui runs in Kubernetes on `socrat-2`.
- Production subscription/Caddy routes point to Kubernetes-managed x-ui.
- Native host `x-ui.service` has been stopped/disabled after users updated subscriptions.
- Docker Caddy has been removed; `caddy-edge` now owns public 80/443 in Kubernetes.

Important paths on `socrat-2`:

```text
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

- Decide whether to remove `cats` temporary exclusion from `socrat-2`.
- Monitor `socrat-1` MDB backup sync and disk free space.
- Decide whether `phone` should be removed from `socrat-1`/`socrat-2` Syncthing configs unless it shares a real folder with them.
- Add backup strategy for `/srv/k8s-nfs`.
- Consider object storage/restic as canonical long-term backup sink for MDB backups.
- Consider retrying Longhorn or another CSI storage backend later.
- Long-term: replace host-level NFS server with a more Kubernetes-native replicated storage backend if true HA is needed.
- Implement `socrat_cluster_bot` later.
