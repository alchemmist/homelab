# socrat-5 headless worker — 10 November 2026

Owner authorized full general-purpose headless worker, alchemmist/password-based
sudo, normal SSH/shell/welcome/manual bottom+tmux, NetBird and telemetry. No GUI,
wallpaper, monitor autostart, second VPN relay or control-plane/etcd enrollment.
Password/hash inputs are private controller files only, never this repository.
This supersedes bootstrap-only boundaries in socrat-5-bootstrap-20261110.md.

## Accepted so far (general workload admission BLOCKED)

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

## Additional acceptance — owner continuation

- NetBird5 machine enrollment is ready, one-off key retired; agent identity and
  original Deployment/PVC survived key-free operational Pod restart. LXC uses
  kernel WireGuard without the ungranted userspace TUN device or additional host
  privileges. Daemon-only command prevents Docker entrypoint interactive-SSO race.
- First enrollment failed before authentication: old setup key revoked/used0,
  peer5 absent, fresh NeedsLogin, original node/Deployment/PVC UIDs intact. Only
  after those independent checks, private preimage/CAS/receipt cleared the failed
  enrolling entry. Other bindings retained; no blind retry or identity rotation.
- NetBird installed its own .41 route on Mac; real `ssh socrat-5` works directly
  as alchemmist. All ordinary aliases now have no SSH jumps. Public0/1/2/4 entries
  remain independent of mesh/Kubernetes; private3/5 use NetBird. No manual Mac
  DNS/routes/tunnel changes. Private bootstrap recovery inventory is separate.
- Both root/alchemmist have owner-requested password, verified privately against
  native hashes; real password-required sudo succeeded. Root SSH remains key-only.
  Interactive zsh and bottom0.14.9 accepted; no GUI/display monitoring installed.
- Native OTel metrics accepted through Grafana: up1 and uname nodename socrat-5,
  canonical instance10.250.0.41:9100. Loki native mTLS count query observed329
  host records/10min without fetching log bodies. Collector/exporter/credentials
  timer active; independent leaf, fsync/durable queues/privacy retained. This is
  new-host delivery acceptance, not revalidation/reset of historical storage.
- Corrected exact HOME host routes .23/.24 through their existing WG peers on5
  for advertised API/NFS addresses; persistent preimage/CAS, no WG restart.
- Controlled failure: only5 outbound UDP to Moscow WG endpoint temporarily
  dropped with independent timed rollback. Moscow .40 unreachable while direct
  pings to0/1/2/3 succeeded, k3s agent remained active and direct management
  survived. Test rule removed. Not proof of physical outage/reboot/NAT rebinding.
- Bidirectional real Pod HTTP and Kubernetes ServiceIP DNS passed again.
  Dedicated owned fixtures and policies removed with UID/resourceVersion guards.
  Temporary binary-only socrat5-otel-transfer HTTP service expired after10min;
  its own failed transient state cleared. It is not a telemetry pipeline.
- Final:6Ready, bootstrap taints preserved only on constrained4 and pending5;
  Moscow relay kubernetes/healthy, native inactive, no fallback marker.
- Selected36 bootstrap/NetBird tests passed. Broader unittest discovery encountered
  missing pytest for one module (135 other cases including4 skips); not a full
  suite pass. No dependency installation or skipped-test masking performed.

## Real blockers — do not remove bootstrap NoSchedule

1. **NFS mount denied by LXC user namespace.** Native read-only NFSv4 mount returned
   Operation not permitted; NFS server192.168.0.23:2049 is TCP-reachable. UID map
   is0->100000/65536, AppArmor unconfined. This is not a missing network route.
   Existing cluster NFS PVs have no node affinity excluding5, so normal admission
   could place workloads that cannot mount their storage. No data was read/written.
   Do not suggest nesting alone as a proven fix or grant a privileged container as
   a workaround. A VM is the recommended full-worker platform; provider/host
   decision is needed. No VM migration/reinstallation authorized or attempted.
2. **Negative NetworkPolicy acceptance failed.** In isolated fixture namespace,
   deny-all Ingress did not prevent cross-node HTTP, including longer retry window.
   Both policies removed; positive HTTP restored/retained. Cause not established;
   do not attribute to LXC without further evidence, and do not claim enforcement.
   Policy configuration was not disabled to hide the failure.
3. **30Mbit/s Proxmox cap not verified.** Owner received UI instruction rate3.75MB/s
   on CT net0; no Proxmox-host access is configured here. Guest link speed does not
   prove the hypervisor cap. No saturation test or fake guest-only ingress guarantee.

Full worker acceptance remains BLOCKED, not complete. Need Proxmox/provider
platform decision, network-policy acceptance and verified bandwidth cap before
lifting bootstrap taint. Physical reboot, general HA/DR and NAT rebinding survival
also remain outside the proven scope.
