# homelab

Personal homelab automation for Socrat nodes.

Ansible manages the common host baseline: persistent SSH access, hostnames, shared users, the machine-wide Starship prompt, and host workload policies. Kubernetes, networking, storage, and applications have separate playbooks.

## Layout

```text
ansible/
  ansible.cfg
  inventory/hosts.yml
  group_vars/
  playbooks/
    base.yml
    users.yml
    starship.yml
    k3s.yml
    rancher.yml
    site.yml
  roles/
    base/
    users/
    starship/
charts/
  socrat-home/
```

## Current nodes

| Host | Address | Notes |
| --- | --- | --- |
| `socrat-0` / `socrat-master` | LAN `192.168.0.23:22`, public `socrat.alchemmist.xyz:2222` | `socrat-0` is the primary name; `socrat-master` remains a compatibility alias; public SSH via router port-forward `2222 -> 192.168.0.23:22` |
| `socrat-1` | LAN `192.168.0.24:22`, public `socrat.alchemmist.xyz:2223` | Public SSH via router port-forward `2223 -> 192.168.0.24:22` |

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
(socrat-0) 
(socrat-1) 
```

The marker uses runtime `hostname`, so the same `starship.toml` works on future nodes like `socrat-2`, `socrat-3`, etc.

## k3s

The default k3s stack is used for ingress:

- Traefik: ingress controller
- ServiceLB/klipper-lb: exposes Traefik `LoadBalancer` on node ports 80/443
- cert-manager: Helm-managed, issues Let's Encrypt certificates via HTTP-01

Run:

```bash
cd ansible
ansible-playbook playbooks/k3s.yml --ask-become-pass
```

Current public router forwards expected by the cluster:

```text
80  -> 192.168.0.23:80
443 -> 192.168.0.23:443
```

Caddy is stopped/disabled by the k3s playbook so Traefik can own HTTP/HTTPS.

Rancher is installed as the Kubernetes management UI:

```text
URL:          https://rancher.socrat.alchemmist.xyz
Namespace:    cattle-system
Cluster name: Socrat (Rancher local cluster display name)
Replicas:     1
Placement:    pinned to socrat-0
Logo:         assets/rancher/socrat-logo.png, applied to Rancher light/dark UI logo settings
TLS:          Rancher Helm chart + cert-manager Let's Encrypt
```

Cluster applications are Helm-managed where appropriate. Resource requests/limits are configured for our managed workloads:

```text
socrat-home nginx:      requests 10m/32Mi, limits memory 128Mi
Rancher server:         requests 250m/1Gi, limits memory 3Gi
Rancher webhook:        requests 20m/64Mi, limits memory 256Mi
system-upgrade-controller: requests 10m/64Mi, limits memory 256Mi
cert-manager:          requests 50m/128Mi, limits memory 512Mi
cert-manager webhook:  requests 20m/64Mi, limits memory 256Mi
cert-manager cainjector: requests 50m/128Mi, limits memory 512Mi
Traefik:               requests 100m/128Mi, limits memory 512Mi
```

Cluster applications are Helm-managed where appropriate:

```text
cert-manager  -> Helm release cert-manager in cert-manager
Rancher       -> Helm release rancher in cattle-system
socrat-home   -> local Helm chart charts/socrat-home
Traefik       -> k3s-managed Helm release in kube-system
```

The current homepage is served by a dedicated Kubernetes container:

```text
Helm:      release socrat-home from charts/socrat-home
Deployment: socrat-home, 2 replicas, one per node via pod anti-affinity/topology spread
Image:      localhost/socrat-home:latest, built from /var/www/socrat and imported into k3s containerd on every node
Service:    socrat-home:8080 -> container:80
Ingress:    socrat.alchemmist.xyz -> socrat-home:8080
TLS:        cert-manager / letsencrypt-http01
```

## Secrets

Do not commit passwords or private keys. Use SSH keys and, later, `ansible-vault` for real secrets.
