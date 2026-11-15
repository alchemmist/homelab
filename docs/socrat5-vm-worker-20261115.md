# socrat-5 native VM worker — 15 November 2026

> **22:29MSK15Nov UPDATE:** Rancher alone returned to **socrat-1**, one non-HA
> replica, to restore native OIDC. Earlier Rancher-on5 acceptance was incomplete
> (health/API checks did not exercise login). Other accepted node5 workloads stay.
> [Recovery evidence](rancher-login-recovery-20261115.md).

## Current runtime acceptance

Owner authorized completing VM105 as the replacement worker, prioritizing direct
WireGuard SSH so RuDesktop is no longer needed for guest administration.

- VM105: Debian13, kernel6.12.116+deb13-amd64,10vCPU/40GiB,100GiB root and
  independently mounted2TiB ext4 `/mnt/files`; Proxmox rate3.576 (~30Mbit/s).
- Hostname socrat-5. Existing Node UID
  `bb08e55e-04aa-4049-8348-6572b80b771e` retained, Ready and uncordoned.
  K3s v1.36.5+k3s1/containerd2.3.4; no second node registration/deletion.
- WireGuard10.250.0.41 and original key; SSH22/2222, original host keys and owner
  authorized keys. Direct `ssh socrat-5` from Mac verified with strict host checks.
  Mac routes, DNS, VPN and SSH aliases unchanged.
- NetBird original PVC/state/machine identity retained, address100.100.9.130,
  management/signal connected. Existing approved peer map preserved, not expanded
  into an all-node NetBird mesh. NetBird's built-in SSH remains disabled.
- zsh login shell, Starship, manual tmux and bottom0.14.9 configured and checked.
  bottom binary matches existing socrat-0 `/usr/bin/btm`, SHA256
  `63eeec5488af29c068fef45bc57ef3d22d1d5903ac3cec22c4ce097748a972e6`.
  Original alchemmist password hash restored privately; sudo still requires a
  password. No NOPASSWD, root-password reset or daemon password-policy change.
- No LXC KubeletInUserNamespace workaround; native overlay/br_netfilter module
  loading enabled. Verified legacy iptables retained; no backend migration.
- Owner subsequently explicitly authorized full NFS admission: label
  `homelab.io/nfs=true`, no no-NFS taint; legacy local-only admission policy/binding
  retired with ownership/spec checks and UID/resourceVersion delete preconditions.
  New nfs-shared PVC tested from two nonroot Pods on5: write/fsync/read, then new
  Pod mount/read/own-test-file deletion. Native statfs magic0x6969 confirmed NFS.
- WG, K3s, overlay-mark guard, native exporter/collector and credential timer
  persistently enabled. No failed systemd units and clean dpkg audit at check.

At initial worker acceptance n8n/PR Agent remained on1. Subsequently the owner
explicitly authorized application handoff: n8n/PR Agent now Ready on5, Rancher
initially Ready2 on1/5, then explicitly reduced by owner to Ready1 ONLY5 (no HA).
Final quiesced node1 n8n dataset—not CT's old DB—was consistently
transferred and verified before activation. **VM105 n8n DB is now authoritative**;
node1 retained recovery dataset is stale. See [current handoff/rollback boundary](socrat5-app-handoff-20261115.md).

## Preservation and source-state recovery

On first re-entry Proxmox CT104 configuration and guest were already absent.
This assistant did not delete CT104; actor/timing of its removal are unverified.
The retained full cold backup was SHA256 rechecked before extracting any state:
see [cold backup receipt](socrat5-vm-migration-20261114.md).

The previous filtered final tar had inherited GNU sparse PAX metadata that Python
could not decode. It was not blindly extracted into the guest. Used native GNU
tar on the verified full vzdump into an isolated private host directory, then
repacked a small worker-only archive. It contains final node password/token,
agent certificates, NetBird PVC, telemetry state/queue and reference account data;
never a containerd runtime copy. n8n excluded from the deployed dataset.

Worker-only archive1813890bytes, SHA256
`b12ccbf7507d570f3c7b27d05be1122257b12035205beec666e7a386edac099e`.
All transfer hashes verified; physical Proxmox capacity checked before/after.
Cold original, intermediate attempts and preimages retained privately, not pruned.
Physical capacity after finalization: crutial~151GiB/files~4.8TiB; guest root~83GiB,
/mnt/files~2TiB free. QCOW2 virtual capacity is not reserved physical space.

Native telemetry recovered17399808bytes of durable state/queue, original cursor
IDs/fsync/retry/privacy settings and cert identity. Collector validation passed;
queues0, sent metrics/logs increasing, refused0 at check. Original log source
files remain in the full backup; no broad log replay was performed. Journald was
restarted after adopting the original machine-id; no old journal deletion.

Expired named otel-host-socrat-5 token was reissued through TokenRequest to the
SAME existing ServiceAccount. No roles/grants/CA private-key reads changed.
Credential refresher then succeeded and checked the unchanged leaf certificate.

Fresh umask0077-created exporter namespace parents were nontraversable for
UID65534. Corrected only owned textfile namespace directories to0755, no service
restart needed; native node_textfile_scrape_error became0. Source now declares
parent directory modes explicitly to prevent recurrence on fresh hosts.

## Mesh and NetworkPolicy acceptance

Runtime initial Ready was insufficient: Pod DNS failed through CoreDNS on3.
WireGuard peers2/3 had no fresh handshakes after the VM's NAT mapping changed.

- Only worker5's NL endpoint changed from direct NL to the existing
  Moscow91.189.82.238:51832 relay already used by HOME0 and3. Persisted in guest
  WG configuration and owning inventory; no relay/VPN production reconfiguration.
- Existing peer5 on3 still pointed at CT's old public NAT port43426. Read-only
  endpoint diagnostics independently observed VM's current public port53673 via
  Moscow. Changed ONLY peer5 runtime Endpoint on3 to94.29.124.139:53673, UpdateOnly;
  no key, AllowedIPs, peer replacement, firewall or restart. Handshake recovered,
  subsequent ping3~8–16ms. Port is observed roaming state, NOT a new hardcoded
  permanent public endpoint in inventory. NAT rebinding/remote-host reboot remains
  an untested edge case; this is not guaranteed future symmetric-NAT traversal.
- A temporary attempt to reach3's WG through its NetBird address was abandoned
  and reverted: existing NetBird ACL intentionally does not provide that mesh.
- A temporary hosts pin for NetBird management bootstrap on5 broke the dependency
  on partially failing cluster DNS. Removed after WG/DNS recovered; no static
  hostname pin or DNS-policy override remains in the production Pod.

Temporary nonroot Pod probes on5 verified both CoreDNS Pod IPs and kube-dns
ClusterIP resolve kubernetes.default.svc.cluster.local. Untrusted namespace and
forged app=rustfs-gateway both DENIED to RustFS Pod IP/ClusterIP ports9000/9001:
8/8 negative checks. Existing nft prerouting mark guard remains active.
This does not claim exhaustive NetworkPolicy acceptance for every application.

Temporary endpoint tools emitted only public keys/endpoints/handshake metadata,
not private keys; copied into existing peer Pods then removed. A bounded ephemeral
hostNetwork/NET_ADMIN diagnostic Pod on4 read endpoints only; production VPN was
not restarted or modified. All diagnostic Pods/namespace and tools cleaned after
saving private evidence; failed early probes retained in the private receipt.

## Remaining gates / temporary access

- Proxmox onboot1 and agent enabled1 configured; stale VM description replaced.
  qemu-guest-agent package is installed. Guest agent device is not yet present in
  the running QEMU instance; full VM stop/start and guest-agent response remain
  PENDING an approved brief outage. In-guest reboot alone may not instantiate a
  newly configured QEMU channel. Other guests/global networking unchanged.
- Physical boot/SSH/WG/K3s/NetBird/telemetry/data mount acceptance not performed.
- Regular VM backup-job inclusion and independent full-VM restore not verified.
- NFS gate CLOSED successfully by subsequent explicit owner authorization:
  dynamic RWX PVC, write/fsync/read and remount/read tests passed on5. Persistent
  K3s config and inventory both nfs=true/no no-NFS taint; no K3s restart needed.
  Only exact owned historical policy+binding removed; unrelated policies untouched.
  Test Pods/PVC/PV/namespace removed. Existing NFS Retain semantics preserved;
  empty backing test directory left under `/srv/k8s-nfs/` (no user data in it).
  Private receipt `~/Library/Application Support/homelab/vm105-nfs-20261115`.
  At that NFS acceptance step n8n/PR Agent were still on1. Subsequently migrated
  by the separately authorized consistent handoff above; original PVC IDs kept.
- Root migration keys are temporary: original desktop key expiry16Nov23:59:59Z,
  added restricted direct Mac migration key expiry17Nov23:59:59Z. Remove after the
  remaining acceptance; do not leave permanent passwordless sudo to replace them.
- CT restart rollback no longer exists as a guest because104 was externally
  removed; recovery uses preserved full backup, with strict single-identity fencing.
  Do not restore/start it alongside105 or activate its historical n8n DB.

Private guest preimages: `/root/homelab-vm105-network-activation-20261114`,
`/root/homelab-vm105-shell-20261115`,
`/root/homelab-vm105-worker-restore-20261115-v2`.
Private controller receipts:
`~/Library/Application Support/homelab/vm105-worker-20261115`.

Initial source checks:19 worker/bootstrap/storage tests +6 n8n rendering/retention
checks passed; worker playbook syntax and git diff whitespace checks passed.
Subsequent NFS activation:20 worker/bootstrap/storage tests +6 n8n tests passed,
plus worker and historical-guard playbook syntax; includes native full-admission
and guard-recreation refusal contracts.
First test invocation used the wrong Python without Jinja2 and syntax invocation
omitted ANSIBLE_ROLES_PATH; corrected using installed Ansible Python/roles path.
No full repository test-suite or reboot/HA claim.
