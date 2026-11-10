# socrat-5 headless worker — 10 November 2026

Owner authorized full general-purpose headless worker, alchemmist/password-based
sudo, normal SSH/shell/welcome/manual bottom+tmux, NetBird and telemetry. No GUI,
wallpaper, monitor autostart, second VPN relay or control-plane/etcd enrollment.
Password/hash inputs are private controller files only, never this repository.
This supersedes bootstrap-only boundaries in socrat-5-bootstrap-20261110.md.

## Accepted so far (setup still in progress)

- Owner account with agreed private password, additive public key, zsh/Starship;
  hostname socrat-5. Official project-pinned bottom0.14.9 .deb checksum verified,
  manual tmux config; no desktop role. Debian apt has no bottom package.
- SSH22 preserved; standard2222 migrated with fresh strict-pinned connection.
  Rancher-metadata SSH animation configured after Kubernetes registration, not
  before (early shell-role metadata lookup correctly failed while node absent).
- Direct WireGuard handshake+ping from.41 to all peers0/1/2/3/4. Existing peer
  mappings and service start times preserved; no wg-socrat restart on old hosts.
  Gateway bootstrap pre-DNAT isolation retired only after direct links verified;
  retired guard service disabled and WG dependency archived. No default route,
  corporate Mac tunnel/DNS/routes edits or public VPN changes.3 endpoint observed
  NAT tuple is a current hint, NOT a forever-stable endpoint guarantee.
- LXC namespace, writable cgroups v2, tmpfs/overlay mounts verified without changing
  PVE privileges. Existing all-capabilities/unconfined provider configuration not
  expanded by us. /dev/kmsg missing: pinned kubelet native KubeletInUserNamespace
  feature gate, no fake kmsg device and no host kernel log exposure.
- K3s exact existing version v1.36.5+k3s1 joined as agent only. LXC skips module
  loading (shared PVE kernel), preserves swap, fail-swap-on=false. Six nodes Ready;
  new worker remains bootstrap NoSchedule until all acceptance completes.
- Native nft backend failed large kube-proxy/policy transactions with EMSGSIZE
  (known unprivileged user-namespace limitation, k3s issue9769). Inspected evidence,
  archived both backend rules, selected stock iptables/ip6tables legacy on THIS
  node and prefer-bundled-bin=false. No rule-table flush, no policy disable, no
  change on other hosts. Controlled agent restart only on new tainted worker.
- Real busybox Pods ran on0+5; bidirectional Pod HTTP succeeded. Initial cluster
  DNS failed before legacy fix; same existing probes then resolved Kubernetes DNS
  through ServiceIP10.43.0.10. Node Ready alone was not treated as acceptance.

## Source/ownership

Inventory hosts.yml, group_vars/Socrat.yml, host_vars/socrat-5.yml; worker templates
have opt-in usernamespace and bundled-bin/module-loading controls (other nodes'
defaults preserved). Separate socrat-5-headless/terminal-tools/ssh/netfilter/worker
plays. One-time netfilter preparation refuses an existing transition directory;
do not replay bootstrap or existing peer admission scripts.

Source NetBird adds only5, leaves constrained4 explicitly unenrolled (matching its
previous absent Git machine resources). Argo owns peer Deployment/PVC; Ansible
controller reconciles scoped machine identity, never human setup keys or MFA.
Telemetry must use independent leaf only, native durable queues/fsync/privacy,
canonical nodename/instance, no existing CA/leaf rotation or history reset.

## Pending (do not claim full completion yet)

NetBird reconciliation/actual machine access, native telemetry+Grafana/Loki,
private owner sudo/ordinary local ssh alias, deeper pod-policy/NFS checks, bounded
no-Moscow path proof, removal of5 bootstrap taint, cleanup owned fixtures, final
regression/health and private backups. Physical reboot, general HA/DR and NAT
rebinding survival remain separate even when functional setup is complete.
