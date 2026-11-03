# Manual personal SSH account reconciliation

Human runbook: [SSH user](../llm-wiki/ssh-user.md).

## Interface and ownership

`ansible/playbooks/ssh-user.yml` uses the focused `ssh_user` role. Required inputs:
`ssh_username` and controller-local `ssh_public_key_file`. Target is `Socrat`
(including all default inventory overlays); explicit `--limit` narrows acceptance.
No Authentik API, tokens, attributes, n8n, Kubernetes resources or Argo deployment
are involved. This is normal host configuration through Ansible.

The existing `users` role is intentionally unchanged: it replaces inventory-
managed exact key sets and supports disable/revocation. Reusing it for a single
public-key addition would silently remove other approved keys. The focused role
uses `ansible.posix.authorized_key` with `exclusive: false`, and skips key writes
when the exact fingerprint already exists, preserving existing per-key options.
Inventory-managed users must have the requested key/host/present state declared
first, so the next baseline cannot silently undo the operation. New users outside
that inventory list are not implicitly deleted by the existing baseline.

## Safety and limitations

The public file is parsed locally by real `ssh-keygen` before host writes; private
material, options, certificates, malformed wire data, multiple keys/control chars
and unsafe/protected usernames are rejected. Original input is no_log. The
remote checker emits metadata/fingerprints only, never hashes, sudo output or keys.

A linear all-selected-host preflight runs before user changes. It rejects owner/
transport/system/privileged accounts, non-local identities, disabled shells,
unexpected homes, unbound existing home directories, symlinks/hardlinks, SSH paths
owned by another identity, dangerous groups,
sudo grants, readable admin kubeconfig and existing Authentik enrollment markers.
It does not take over those accounts, strip grants or rewrite sshd to pass a test.
Sudo denial is accepted by explicit English denial text for exit 0 **or** 1:
Debian's root `sudo -l -U` query returns 0 even for a denied user.

New accounts are password-locked with a login shell and no supplementary groups.
Existing safe shell/groups are preserved. A second account inspection precedes
key insertion, catching default privilege inheritance after account creation.
SSH directory/key writes run **as the target non-root user**, not root. Even a
parent-path swap between preflight and write cannot make the key-writing module
write a root-owned path. Other/root-owned existing SSH paths require review rather
than automatic ownership takeover. After apply it checks the requested fingerprint, key-file ownership/modes,
password lock and privilege isolation. Local `--check` validation and remote
read-only preflight run, but account/key updates and mutation-dependent postflight
are skipped. New users are never created to make a check-mode run succeed.

The SSH policy probe checks standard sshd config with a representative client
context, not every possible address/Match rule, firewall, AllowUsers/AllowGroups
policy or alternate daemon CLI configuration. It requires the managed key path
be an effective source and pubkey/PAM support, without changing daemon policy.
It cannot prove that a human owns the private key or can reach a node. Actual
human login from the intended client/network is still required.

Ansible is not transactional. All-host preflight reduces early partial writes,
but late errors can leave a created account or subset of keys applied. Repeat
same inputs after diagnosis; no destructive rollback or global user cleanup.
Do not run concurrent user/key writers. This play is additive, not key rotation,
revocation, session termination or Kubernetes admin authorization.

## Verification performed

- Syntax and list-hosts against normal inventory: all four cluster nodes, no
  connection-only NetBird controller alias.
- Python unit/regression tests include native OpenSSH parsing, invalid/private
  inputs, protected names, play scope and unchanged legacy users/import behavior.
- Real Ansible + Linux + OpenSSH acceptance on **two disposable containers** in
  the already running local engine: check mode leaves accounts/keys untouched;
  create and real strict-host-key login; repeated apply has changed=0 on both;
  second key preserves first; existing options retained; missing key and missing
  account on one node repaired; sudo group/direct grants, symlink and inventory
  conflicts block key writes across selected nodes.
- Containers use no host mounts/published ports and `--network=none`; only fixture
  keys are generated, then removed with temporary files/containers. No real node
  accounts, Tim/owner keys, sudo, SSH policy or network configuration were changed.

No real person's username/key was supplied for a production apply, so this is
not personal login acceptance on the four physical nodes.

```sh
python3 -m pytest -q tests/test_manual_ssh_user.py tests/test_identity.py tests/test_identity_ssh.py
cd ansible && ansible-playbook playbooks/ssh-user.yml --syntax-check
# Opt-in real Linux acceptance; existing engine + community.docker required:
cd .. && python3 tests/integration/ssh-user/verify.py
```
