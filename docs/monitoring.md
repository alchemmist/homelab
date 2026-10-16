# Socrat monitoring

The first phase installs `kube-prometheus-stack` in `cattle-monitoring-system`: Prometheus, Grafana, Alertmanager, kube-state-metrics and node-exporter. It collects metrics from every current cluster node, including socrat-3. Loki, Alloy, Telegram delivery and telephone alerts are separate phases.

Prometheus, Grafana, Alertmanager and their supporting controllers run on socrat-1. Node-exporter runs on every node. Rancher integration and the separate Grafana ingress share this stack; they do not create another Prometheus installation.

## Storage and availability

All three persistent workloads explicitly select `local-path`, because this cluster also has an NFS storage class. Their volumes remain on socrat-1 and do not depend on the NFS server on socrat-0.

| Workload | PVC request | Retention |
| --- | --- | --- |
| Prometheus | 10 GiB | 7 days or 6 GB of retained blocks, whichever is reached first |
| Grafana | 1 GiB | Persistent database and settings |
| Alertmanager | 1 GiB | Persistent silences and notification state |

Local-path PVC sizes do not enforce filesystem quotas. Prometheus's block retention limit also needs headroom for its WAL, head and temporary compaction files. Keep at least 20 GiB free on socrat-1 and inspect actual usage before increasing retention. Initial installation requires at least 30 GiB available. The initial resource audit found about 39 GiB free and 9.4 GiB available RAM; those are measurements, not permanent capacity guarantees.

This is a single-instance monitoring stack. If socrat-1 fails, metrics collection, dashboards and in-cluster alert evaluation become unavailable until that node and its storage return. This phase does not provide independent external monitoring or protection against losing the whole cluster. Alertmanager's initial receiver discards notifications intentionally; delivery is not configured yet.

## Metrics and access

Standard collectors cover node CPU, memory, filesystem and network use, pod state and restarts, kubelet/container metrics and the Kubernetes API. K3s has a shared metrics registry; separate scheduler/controller-manager endpoints must not be assumed to behave like a kubeadm installation. Etcd collection uses the dedicated authenticated monitoring endpoint on each of its three members, rather than exporting etcd client credentials to Prometheus.

The API collector uses the two control-plane WireGuard addresses and excludes the duplicate legacy socrat-0 LAN endpoint. Home-node kubelet scrapes drop duplicated control-plane metric families while retaining kubelet metrics; cAdvisor and probe collectors remain intact. Kubelet serving certificates are verified against the cluster CA. Exporters listen on private node addresses, and the etcd proxy listens only on WireGuard port 9238 with bearer authentication.

Grafana is available at [grafana.socrat.alchemmist.xyz](https://grafana.socrat.alchemmist.xyz/d/socrat-overview). The username is `admin`; the ingress password and Grafana administrator password use the same generated Secret. Rancher uses the local-cluster monitoring proxy without requiring an additional monitoring stack.

Grafana's internal anonymous Viewer access supports Rancher's authenticated service proxy and embedded dashboards. The public ingress must separately require authentication. The `socrat-grafana-admin` Secret contains `admin-user` and `admin-password`; secrets must not be placed in Git or printed by verification commands. Do not expose the internal anonymous Grafana Service directly through another ingress or NodePort.

To copy the Grafana password into the macOS clipboard without printing it or writing a plaintext password file:

```sh
ssh socrat-0 'kubectl -n cattle-monitoring-system get secret socrat-grafana-admin -o jsonpath="{.data.admin-password}"' | base64 --decode | pbcopy
```

Paste it directly into the login form or a password manager. The clipboard contains a secret until replaced; avoid clipboard-history sharing. Retrieve the username separately with the same command replacing `admin-password` with `admin-user` and omitting `| pbcopy`.

## Socrat Overview

The provisioned **Socrat Overview** dashboard (UID `socrat-overview`) shows Ready nodes, running pods, healthy etcd/API targets, CPU and memory use, root filesystem space, recent pod restarts, scheduler backlog and controller queue depth. Counts use live metrics rather than a fixed three-node assumption. Empty restart/queue panels can mean no recent events; inspect scrape health before interpreting missing data. Changes belong in `charts/monitoring-k3s/templates/socrat-dashboard.yaml` because provisioning replaces UI edits.

## Verification

Run from the repository with working SSH access to socrat-0:

```sh
python3 scripts/check-monitoring.py
```

The checker uses Kubernetes Service proxy requests over SSH, without a public Prometheus endpoint or a local port-forward. It verifies every active scrape target, exporter/kubelet coverage against the current node list, etcd leadership, representative metrics, local persistent volume placement, memory requests/limits and anonymous/authenticated public Grafana access. Admin credentials remain in process memory.

The Grafana URL and SSH alias can be overridden using `--grafana-url` and `--ssh-host`. A failed check exits nonzero and reports its failing condition. The checker waits up to 120 seconds for discovered targets to become healthy; override this with `--wait-seconds`. Real failures still fail the check at the deadline. Immediately after deployment, allow at least two scrape intervals before expecting every series.

For a controlled persistence test, first save a baseline outside the repository:

```sh
python3 scripts/check-monitoring.py --snapshot /tmp/socrat-monitoring-before.json
```

Restart only the monitoring pods, leaving their PVCs and unrelated workloads intact. Wait for them to become Ready and scrape again, then compare:

```sh
python3 scripts/check-monitoring.py --compare /tmp/socrat-monitoring-before.json
```

The comparison verifies unchanged PVC identities and queries the same historical timestamp to demonstrate that Prometheus history survived the restart. It does not by itself prove backup recoverability or filesystem survival after node loss. Separately verify that Grafana dashboards and provisioned data sources remain available after its restart.

## Operations

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/monitoring.yml
```

The playbook uses the existing Kubernetes administration access on socrat-0 and requires no sudo password. Role tags `monitoring_base`, `monitoring_k3s` and `monitoring_rancher` allow scoped updates after the initial full installation.

Keep Helm values and provisioned dashboards in the repository. Apply changes through the Ansible monitoring playbook. Before a chart upgrade, inspect release notes and CRD requirements, capture current Helm values and Kubernetes workload/PVC metadata, and preserve the Grafana database and credentials. Never uninstall or delete persistent claims as a troubleshooting shortcut: the current storage class uses the Delete reclaim policy.

When disk usage grows, first inspect Prometheus series cardinality and retention, container image usage, and other workloads on socrat-1. Reducing retention is preferable to deleting unrelated data. The initial deployment does not authorize additional backup deletion.

## Verified deployment on 2026-10-16

All four nodes and all 30 scrape targets passed the verification script, including three etcd members and both API servers. The Socrat Overview dashboard was loaded by Grafana. Public HTTPS rejected anonymous requests with 401 and accepted the generated credentials; etcd metrics rejected unauthenticated requests and accepted the private token on all three nodes.

Prometheus and Grafana pods were restarted independently. The same historical Prometheus samples and all three PVC identities survived. A temporary annotation written to Grafana's database also survived its restart and was removed after verification. The 87 pre-existing namespace, PVC, Deployment and StatefulSet identities were unchanged.

Measured monitoring pod memory was approximately 1.5 GiB across the cluster, with about 37 GiB disk space remaining on socrat-1. These are post-install observations, not forecasts. Rancher proxy health and generated embedding paths were checked through the Kubernetes service proxy; an authenticated Rancher browser session was not available for visual verification.
