# Linux, SSH, kubeconfig and Kubernetes RBAC

> Ordinary network access is **NetBird**; SSH separately via public key.
> The Linux `tim` account was not renamed together with the Authentik login
> `antropophag`.
> Standalone WG is recovery-only; public HTTPS does not expose SSH to the Internet.

Part of the [general reference](../architecture/identity.md). Authentik SSO does not
replace these perimeters and does not grant SSH/root/kubectl automatically. Do
not change the WireGuard/NetBird topology here. Network entry and the full
new-administrator scenario: [NetBird](../../network/netbird/README.md).

## 1. Sources

- `ansible/roles/users/tasks/main.yml`, `files/verify.py` — restricted personal users.
- `ansible/playbooks/ssh-user.yml`, role `ssh_user` — manual username + one public
  key, adding without removing the other keys:
  [short instruction](ssh-user.md).
- `ansible/playbooks/users.yml` — exact declarative key set from inventory.
- `ansible/playbooks/identity-hosts.yml` — owner kubeconfig protection + users playbook.
- [Registry of personal SSH accounts](../../../ansible/inventory/group_vars/Socrat/users.yml):
  `homelab_owner_account` — the protected sudo owner; `homelab_users` — real public
  keys and assignments.
- `deploy/identity/access-policy.yaml` — role intent, not self-standing enforcement.
- [Optional Authentik public-key import](identity-ssh-keys.md) — a separate
  read-only plan/export and a guarded Ansible play; currently empty/switched off,
  without a Tim migration. Immutable UUID binding, explicit active/revoked hosts;
  not SSO/CA.
- `deploy/identity/observer-role.yaml`, `identity-rbac.yml` — the unbound observer definition.
- The K3s install/HA config templates also preserve the kubeconfig mode/group.

Owner/root/automation identities are not managed by the restricted-user path.
The role forbids `root`, `alchemmist`, `ghactions`; changing them is a separate
privileged procedure.

## 2. What the users role does

Before changes it validates the username, state, absence of sudo intent/dangerous
supplementary groups and the format of all public keys. Reviewed OpenSSH keys are
allowed (ed25519/RSA/supported ECDSA/security-key variants), not private keys.
Usernames are unique. `authorized_keys` must be a list, not a single string.

For an assigned user it:

- creates/preserves the home, account and shell;
- blocks password authentication (`password_lock`);
- sets the **exact** supplementary group set (`append: false`);
- `.ssh` 0700, `authorized_keys` 0600, owner remains the user;
- **replaces** rather than appends the key set: a key removed from the list
  actually disappears;
- removes a legacy direct `/etc/sudoers.d/<name>` grant;
- runs the privileged verifier for SSH/PAM/sudo/kubeconfig isolation.

The role does not grant sudo and rejects root-equivalent groups:
sudo/wheel/admin/docker/disk/lxd/incus/kvm/libvirt. But it does not guess
foreign sudoers rules: the effective verifier exists precisely because
privilege can arrive from more than one file/group.

## 3. How to add Linux access

**Ordinary manual scenario:** [username + `.pub` → `ssh-user.yml`](ssh-user.md).
No Authentik or workflow needed. That separate play adds one key, checks every
selected node and does not remove other keys. Below is a different, declarative
path via `homelab_users` with a **full replacement** of the key set. Do not
confuse the semantics of the two playbooks. If the account is already in the
inventory, the new public key must first be approved and added there — the
manual play checks this.

First separately agree on **which hosts**, why a shell, the duration and the
specific public keys. Confirm identity/key fingerprint through an independent
channel. The person existing in Authentik is not such an agreement.

In the existing inventory source, add a `homelab_users` entry following the
current scheme. Mandatory decisions: `name`, explicit `hosts`, the
`authorized_keys` list, `state: present`, no sudo/privileged groups. Take the
public key from the person themselves; do not generate their private key and do
not ask them to send private material.

**If `hosts` is not specified, the role applies the user to all hosts of the
corresponding play.** Do not leave the field accidentally empty when access to
only one node is intended. Check the merged group_vars/host_vars and inventory
aliases before apply.

Check syntax, diff, then apply to the agreed hosts with a safe sudo prompt. An
example of the existing full hardening play, not a universal grant to everyone:

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml \
  playbooks/identity-hosts.yml --ask-become-pass
```

For a single node, use the reviewed `--limit` / the proper users playbook and
inventory, understanding that the first play of `identity-hosts` targets only
socrat-0. Do not store the become password in source. On socrat-3 a verified
sudo method is used; do not replace it with the previously broken privileged
path.

After apply: the owner checks the actual key fingerprints/effective policy, and
the person themselves performs a real SSH login from their own device. The
owner checking authorized_keys does not prove the person has the correct
private key. Tim's intended keys/PAM/public-key/sudo isolation were verified on
the four nodes, but his own network private-key acceptance remains a separate
step.

## 4. SSH revocation

`state: disabled` preserves the account/home, sets nologin and clears
authorized_keys. This is preferable to unsanctioned deletion of user data.
Existing processes/SSH sessions are not guaranteed to end: separately handle
active connections/jobs and approved termination/credential rotation.

**Removing the user from vars or removing a host from `hosts` does not by
itself clean the account on the former machine.** The role manages only current
assignments and deliberately does not delete other accounts. To revoke, first
explicitly apply the disabled state on the former node (reviewed per-host
override/a separate pass), verify key/privilege cleanup, then remove the
assignment. Do not run a global destructive cleanup.

`password_lock` is not equivalent to a safe SSH policy on every OS. Account for
sshd `PubkeyAuthentication`, PAM, account checks and the shell; the verifier
distinguishes these. Arch tooling can emit OSC/JSON noise, so use the reviewed
parser, not an arbitrary grep/first line of terminal output.

## 5. The admin kubeconfig incident

On socrat-0 `/etc/rancher/k3s/k3s.yaml` was **0644**. Fixed immediately to
**0640 root:alchemmist**; the K3s config keeps `write-kubeconfig-mode: "0640"`
and `write-kubeconfig-group: alchemmist`. The install/HA templates were fixed
too, so a fresh install does not bring back a world-readable credential.

Before changing the group, the play checks primary + supplementary membership:
only the owner, no unexpected users. Then it verifies that Tim cannot read the
file while the owner still gets `yes` on `kubectl auth can-i '*' '*'
--all-namespaces`. Handing the admin kubeconfig to an observer does not make it
read-only: it is a cluster-admin authority, not an ordinary connection setting.

**Chmod does not revoke a copied certificate/key.** The historical exposure and
a supported credential/CA rotation are a separate task. Do not claim there was
definitely no leak if such forensics/audit was not performed; do not restart
the whole K3s or change the CA as a side effect of a CSS/SSO rollout.

## 6. Why a sudo exit code is not enough

`sudo -l -U tim` can finish with rc0 while simultaneously printing that Tim is
not allowed to run sudo. The verifier uses the C locale and parses the real
policy result; it does not treat a single exit code as proof of a grant or
denial. An error/unparsed result requires review, not an assumption of safety.

## 7. Kubernetes/Rancher rights

`homelab-project-observer` allows get/list/watch for
pods/services/endpoints/PVC/events, deployments/replicasets/statefulsets/
daemonsets, jobs/cronjobs, ingresses/networkpolicies. **No Secrets, pods/exec,
pods/log and nodes**. The definition itself is installed; human bindings were
not created.

To grant access to one namespace, separately define the real authentication
subject/principal and a namespace `RoleBinding` to a reviewed role. Do not
create a `ClusterRoleBinding` where a namespace one suffices. Check
`kubectl auth can-i` for allowed and forbidden resources under the appropriate
identity; do not hand another person the owner kubeconfig for such a test.

For Rancher additionally look at the exact OIDC principal and real project/
cluster grants: its existing users/principal IDs are not the same strings as
IdP groups. Auth configs/subject mappings do not fix broad old RBAC bindings by
themselves.

A node root can read/modify node workloads and secrets. A Pod creator/exec in
a namespace can potentially also get namespace secrets. A limited app role does
not remove these host/workload trust boundaries. One cannot promise the owner of
an external root host “no access to data” while trusted workloads run there.

## Working transport after November 6

The nodes' ordinary SSH aliases use only `10.250.0.1/.3/.2/.5:2222` with pinned
host keys, no public fallback/ProxyJump. The Mac's NetBird is the primary
transport; the owner's standalone WG `.4` is a separately verified recovery,
usually off; do not change the mandatory Tunnelblick. The existence of public
human HTTPS entrances does not move SSH onto the public A records. The internal
TV peer `.8` is revoked; Mac/phone/node identities were not affected. Current
VPS address, DNS lifecycle and acceptance boundaries: [network-access.md](../../network/README.md).
