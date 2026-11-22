# Give a person SSH on the nodes

> Ordinary network access is **NetBird**, SSH separately by public key.
> The Linux `tim` was not renamed together with the Authentik login `antropophag`.
> Standalone WG — recovery only; public HTTPS does not open SSH to the Internet.

Ansible is enough for this. Authentik, attributes and n8n are not needed.
The playbook creates **an ordinary Linux user without sudo**, blocks the password and
adds their public SSH key to all nodes of the `Socrat` group from the inventory.
This does not grant Kubernetes roles, application access or access via NetBird.
The full new-admin scenario: [Authentik/MFA → NetBird → separate rights](../../network/netbird/README.md#how-to-add-a-new-administrator).

## What to prepare

Ask the person for their **public** key — a single line `ssh-ed25519 …` from a
`.pub` file. The private key stays with the person. Reconcile the fingerprint with the owner:

```sh
ssh-keygen -lf "$HOME/Downloads/ivan.pub" -E sha256
```

Choose a free Linux name, for example `ivan`. Run from a current `homelab`
checkout, with your already-working administrative SSH access to the nodes.
You need Ansible, Python 3, `ssh-keygen`, the `ansible.posix` collection and the sudo
right for Ansible on the target machines. Do not write passwords into Git or command arguments.

## Check first, then apply

```sh
cd homelab/ansible

# Shows the nodes; without --limit this is the whole Socrat group, currently four nodes.
ansible-playbook playbooks/ssh-user.yml --list-hosts

# Checks the name, key, account state and rights. Does not change accounts/keys.
ansible-playbook playbooks/ssh-user.yml \
  -e ssh_username=ivan \
  -e "ssh_public_key_file=$HOME/Downloads/ivan.pub" \
  --check --ask-become-pass

# Creates what is missing and adds the key.
ansible-playbook playbooks/ssh-user.yml \
  -e ssh_username=ivan \
  -e "ssh_public_key_file=$HOME/Downloads/ivan.pub" \
  --ask-become-pass
```

`ssh_public_key_file` is a path **on your computer**, not on the nodes. To add a single
machine, add `--limit socrat-2`; this deliberately will not check the other nodes.
After the apply, the person themselves verifies the login from their device: for example,
`ssh -l ivan socrat-1`, if they already have trusted SSH aliases and
network access configured. Do not disable host-key verification for a successful login.

## How it works

- Checks each selected node, not merely the presence of a username.
- Creates a missing account; does not recreate an existing secure account.
- Adds a missing key. **Does not remove other keys**, does not weaken the options of an
  already-present key. A second key is added by the same run with another `.pub`.
- Checks the password lock, `.ssh` 0700, `authorized_keys` 0600 and the files' owner.
- Does not add sudo and does not rewrite others' groups/SSH configuration. Owner,
  transport/system accounts, privileged or disabled accounts, an unexpected home and a
  symlink block the operation instead of an automatic takeover.
- A repeat run on a matching state changes nothing.

If a node is unavailable or the check did not pass, this is **not a general success**. Ansible is not
transactional: a late error may leave a partial result. Fix the cause
and repeat the same run; do not delete accounts/homes for a green report.

## Important about the old users.yml and revocation

`users.yml` remains the declarative management of **the exact set of keys** from
`homelab_users`. If the chosen person is already described there, first add the new
key to their inventory record and check `hosts`/`state`: the new playbook does not bypass
this policy, otherwise the next baseline would delete the added key.
For a new person outside `homelab_users`, the existing baseline does not delete them.
If you later move them into the inventory, list all approved keys.

This playbook **only adds**. Replacing the `.pub`, removing the person from Authentik
or from vars does not revoke the old key. For a revocation, use a separate reviewed
change of the full key set / `state: disabled` through
[the existing users.yml](identity-host-access.md#4-ssh-revocation).
Already-open SSH sessions do not terminate by themselves when a key is removed.

## Transport (6 November 2026)

Ordinary SSH stays internal-only on the four node `/32`, port 2222, with pinned keys and without a public fallback. On the owner Mac the main transport is NetBird, a separate WG — recovery; public DNS/Grafana SSO does not grant a shell and does not change this path. Do not install the old Mac DNS overrides for SSH. [The network summary and boundaries](../../network/README.md).
