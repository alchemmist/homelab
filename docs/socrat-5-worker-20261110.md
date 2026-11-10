# socrat-5 headless worker — 10 November 2026

Owner authorized full general-purpose headless worker, alchemmist/password-based
sudo, normal SSH/shell/welcome/manual bottom+tmux, NetBird and telemetry. No GUI,
wallpaper, monitor autostart, second VPN relay or control-plane/etcd enrollment.
Password/hash inputs are private controller files only, never this repository.
This supersedes bootstrap-only boundaries in socrat-5-bootstrap-20261110.md.

## Functional acceptance: no-NFS worker profile

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
  new worker initially remained bootstrap NoSchedule pending acceptance;
  current no-NFS admission is described below.
- Native nft backend failed large kube-proxy/policy transactions with EMSGSIZE
  (known unprivileged user-namespace limitation, k3s issue9769). Inspected evidence,
  archived both backend rules, selected stock iptables/ip6tables legacy on THIS
  node and prefer-bundled-bin=false. No rule-table flush, no policy disable, no
  change on other hosts. Controlled agent restart only on new tainted worker.
- Real busybox Pods ran on0+5; bidirectional Pod HTTP succeeded. Initial cluster
  DNS failed before legacy fix; same existing probes then resolved Kubernetes DNS
  through ServiceIP10.43.0.10. Node Ready alone was not treated as acceptance.


## Owner-approved no-NFS profile — current state

Owner explicitly accepted keeping5 without NFS. No Proxmox privilege expansion
or VM migration is required for this profile. Bootstrap taint was replaced,
with node UID/resourceVersion CAS, by `homelab.io/no-nfs=true:NoSchedule` and
label `homelab.io/nfs=false`. Other nodes/taints and existing NFS PVs unchanged.

This is an **explicit-opt-in stateless/local ephemeral worker**, not unrestricted
placement for every application. New compatible workloads use:

```yaml
nodeSelector:
  kubernetes.io/hostname: socrat-5
tolerations:
  - key: homelab.io/no-nfs
    operator: Equal
    value: "true"
    effect: NoSchedule
```

`emptyDir`, config/secret/projected/downwardAPI, image and existing local hostPath
volumes are accepted. HostPath remains subject to normal namespace security;
this policy grants no privileges. General PVC, direct NFS, inline CSI and other
unclassified persistent backends are rejected for Pods targeting/tolerating5.
The sole named PVC exception is the already bound, local-path, node5-pinned
NetBird identity `netbird-host-peers/machine-socrat-5`; UID/ownership preserved.
Ordinary local PVC support would need separate explicit classification, not a
blanket exception. Broad Exists tolerations plus persistent storage must pin a
different hostname; direct nodeName5 cannot bypass storage validation.

The native ValidatingAdmissionPolicy/binding are owned by
`deploy/admission/socrat5-local-storage.yaml`; audit-only-by-default guarded
reconciler/playbook refuses foreign ownership or drift, creates only absent
objects with preimages and native absent-object CAS. Run
`socrat-5-storage-guard.yml -e socrat5_storage_guard_apply=true` explicitly for
a new installation; the worker play refuses to provision until the exact live
storage boundary audits operations0. No existing app policy
or RBAC was broadened. Existing broad-toleration persistent Pod audit found0
unconstrained candidates. Six live server-side dry-run cases accepted/rejected
as intended, including no-NFS PVC rejection, another node allowed and the
verified system-local identity exception. Unopted scheduler probe stayed Pending
with untolerated taints; the initial assertion expected an overly specific error
string, but retained native conditions/spec established the actual negative case.

### NetworkPolicy: root cause fixed, not a platform exception

The pre-existing NetBird/VXLAN transport-mark interaction was missing its guard
on the new node. Incoming transport mark overlapped kube-router allow bit,
bypassing policy rejection. See `k3s-networkpolicy-overlay-marks.md` for the
previous independently proven mechanism. We applied the existing owned guard
only on5; live deny immediately began rejecting both directions. The worker play
now installs that role before K3s; a5-only systemd dependency and ExecStartPre
ensure the guard is applied/verified on every agent start, failing closed.
No WG, NetBird, K3s or application restart was required for this correction.

Actual isolated-namespace matrix:
- deny-all ingress: cross-node HTTP blocked0->5 and5->0;
- explicit namespace-local label+TCP8080 allow: both directions succeeded;
- wrong-label source on0: blocked to5;
- wrong-label source on5: blocked to5.

An ordinary scheduler-selected (not nodeName-forced) Job on5 succeeded with
UID65534, all capabilities dropped, read-only rootfs, CPU/memory limits,
emptyDir read/write, Kubernetes DNS and cross-node HTTP. First immediate attempt
failed HTTP; retained failed Job/preimages, then a separately named Job with
bounded startup retry passed. The one-off startup timing was not independently
traced; wrong-label negative cases remained blocked. No conntrack
flush or policy bypass. Dedicated test namespace/Jobs/policies removed with
UID/resourceVersion deletion guards. NetBird Git deployment tolerates the
no-NFS taint, remains available and Argo Healthy; direct SSH still works.

Selected58 unittest cases passed, including storage-guard ownership/defaults/
drift and worker safety tests. Existing pytest-based overlay tests could not be
collected in the available interpreter (pytest missing); live guard audit is
operations0 and the real policy matrix above passed.

**Remaining external limitation:** requested30Mbit/s hypervisor cap is not
verified without Proxmox access. No saturation test, guessed guest ingress
limit, physical reboot/HA or NAT-rebinding acceptance claimed.

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
- At the earlier blocked checkpoint:6Ready, bootstrap taints on constrained4 and pending5;
  Moscow relay kubernetes/healthy, native inactive, no fallback marker.
- Selected36 bootstrap/NetBird tests passed. Broader unittest discovery encountered
  missing pytest for one module (135 other cases including4 skips); not a full
  suite pass. No dependency installation or skipped-test masking performed.

## Historical findings — superseded by the no-NFS acceptance above

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

Unrestricted NFS-capable worker acceptance is NOT claimed. The owner-approved
no-NFS profile above is functional and replaces the bootstrap gate; network
policy is now accepted with the guard. Hypervisor bandwidth verification,
physical reboot, general HA/DR and NAT rebinding remain outside the proven scope.
