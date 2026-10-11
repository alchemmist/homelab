# homelab

Personal homelab automation for Socrat nodes.

This repo starts small: Ansible inventory + roles for shared users and the machine-wide Starship prompt config on `socrat-master` and `socrat-1`.

## Layout

```text
ansible/
  ansible.cfg
  inventory/hosts.yml
  group_vars/
  playbooks/
    users.yml
    starship.yml
    site.yml
  roles/
    users/
    starship/
```

## Current nodes

| Host | Address | Notes |
| --- | --- | --- |
| `socrat-master` | LAN `192.168.0.23:22`, public `ai.alchemmist.xyz:2222` | Public SSH via router port-forward `2222 -> 192.168.0.23:22` |
| `socrat-1` | LAN `192.168.0.24:22`, public `ai.alchemmist.xyz:2223` | Public SSH via router port-forward `2223 -> 192.168.0.24:22` |

## Run

Install Ansible locally, then from `ansible/`:

```bash
ansible-playbook playbooks/starship.yml --ask-become-pass
```

Limit to one node:

```bash
ansible-playbook playbooks/starship.yml --limit socrat-1 --ask-become-pass
```

## Starship prompt

The role deploys a machine-wide Starship config to `/etc/starship/starship.toml` and enables it from global shell rc files (`/etc/zsh/zshrc`, `/etc/bash.bashrc` when present), so it applies to every interactive user, not only `alchemmist`.

The deployed prompt includes a grey host marker on the command line:

```text
(socrat-master) 
(socrat-1) 
```

The marker uses runtime `hostname`, so the same `starship.toml` works on future nodes like `socrat-2`, `socrat-3`, etc.

## Secrets

Do not commit passwords or private keys. Use SSH keys and, later, `ansible-vault` for real secrets.
