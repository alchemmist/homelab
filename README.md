# homelab

Personal homelab automation for Socrat nodes.

This repo starts small: Ansible inventory + a `starship` role that deploys the shared prompt config to `socrat-master` and `socrat-1`.

## Layout

```text
ansible/
  ansible.cfg
  inventory/hosts.yml
  group_vars/
  playbooks/
    starship.yml
    site.yml
  roles/
    starship/
```

## Current nodes

| Host | Address | Notes |
| --- | --- | --- |
| `socrat-master` | `ai.alchemmist.xyz:2222` | Public SSH via router port-forward |
| `socrat-1` | `192.168.0.24:2222` | LAN SSH, sshd also keeps port 22 as fallback |

## Run

Install Ansible locally, then from `ansible/`:

```bash
ansible-playbook playbooks/starship.yml
```

Limit to one node:

```bash
ansible-playbook playbooks/starship.yml --limit socrat-1
```

## Starship prompt

The deployed prompt includes a grey host marker on the command line:

```text
(socrat-master) 
(socrat-1) 
```

The marker uses runtime `hostname`, so the same `starship.toml` works on future nodes like `socrat-2`, `socrat-3`, etc.

## Secrets

Do not commit passwords or private keys. Use SSH keys and, later, `ansible-vault` for real secrets.
