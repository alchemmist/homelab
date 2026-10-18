# Socrat monitoring

The first phase installs `kube-prometheus-stack` in `cattle-monitoring-system`: Prometheus, Grafana, Alertmanager, kube-state-metrics and node-exporter. It collects metrics from every current cluster node, including socrat-3. Loki, Alloy, Telegram delivery and telephone alerts are separate phases.

Prometheus, Grafana, Alertmanager and their supporting controllers run on socrat-1. Node-exporter runs on every node. Rancher integration and the private Grafana gateway share this stack; they do not create another Prometheus installation.

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

Grafana is available at [grafana.socrat.alchemmist.xyz](https://grafana.socrat.alchemmist.xyz/d/socrat-overview) only through the `socrat-wg` WireGuard network. Viewing dashboards requires no login. Home LAN membership alone does not grant access. There is no permanent public Grafana Ingress. Requests sent explicitly to the public ingress address receive its default HTTP 404 response, including requests with forged WireGuard or LAN `X-Forwarded-For` headers.

Private DNS resolves the Grafana hostname to `10.250.0.3`. The private HTTPS gateway on socrat-1 forwards WireGuard traffic to Grafana; no public Grafana route is installed. Clients need both the WireGuard connection and private DNS resolution. The checker bypasses DNS explicitly while preserving the hostname and validating TLS, so its private probe verifies the gateway separately from client DNS configuration.

`monitoring-private-dns.yml` publishes the record on all three existing private DNS servers. The macOS `wireguard_admin_client` role installs one suffix resolver `/etc/resolver/socrat.alchemmist.xyz` pointing to `10.250.0.2`, `10.250.0.3` and `10.250.0.1`. It covers Grafana and future service names without per-domain client changes. Installing it requires macOS administrator access once. Ordinary clients can instead include these DNS servers in their WireGuard profiles; existing imported profiles need a one-time update. Connect the existing `socrat-wg` tunnel before opening Grafana; the private hostname record exists in our private DNS. Public wildcard DNS can still return an address for this name, as it does for the node hostnames; that is not a dedicated public Grafana record and does not provide a Grafana route. Removing Grafana’s ingress does not imply public NXDOMAIN.

Grafana's anonymous Viewer access supports private viewing and Rancher's authenticated service proxy and embedded dashboards. Administrative operations still require Grafana's `admin` account. The `socrat-grafana-admin` Secret contains `admin-user` and `admin-password`; secrets must not be placed in Git or printed by verification commands. Do not expose the anonymous Grafana Service through an unrestricted ingress or NodePort, and do not trust arbitrary forwarded headers as proof of WireGuard access.

To copy the Grafana password into the macOS clipboard without printing it or writing a plaintext password file:

```sh
ssh socrat-0 'kubectl -n cattle-monitoring-system get secret socrat-grafana-admin -o jsonpath="{.data.admin-password}"' | base64 --decode | pbcopy
```

Paste it directly into the login form or a password manager. The clipboard contains a secret until replaced; avoid clipboard-history sharing. Retrieve the username separately with the same command replacing `admin-password` with `admin-user` and omitting `| pbcopy`.

## Socrat Overview

The default home is **Overview**, with a dark default theme and navigation to **Nodes** and **Services**. Together with **LLM**, these are the four dashboards at the root; generated templates are grouped into **Rancher** and **Kubernetes Diagnostics** folders. Introductory logo/title/description panels are omitted so metrics appear immediately. The supplied brand asset remains versioned in `deploy/monitoring/branding/socrat-cover.png` but is not displayed on these dashboards.

The primary dashboards are versioned as JSON in `charts/monitoring-k3s/dashboards/` and published by the chart. **Overview** (UID `socrat-overview`, retained for existing links) summarizes readiness, key services, per-node resources, active alerts, control-plane redundancy and restarts. **Nodes** (`socrat-nodes`) compares CPU, load, memory, swap, filesystems, disk I/O, interfaces, temperature and uptime, with a node selector. Temperatures are available only where sensors exist. **Services** (`socrat-services`) combines replica readiness, resources and troubleshooting for application workloads, with a service selector. Kubernetes readiness does not imply end-to-end VPN/HTTP availability; external probes and notification delivery are not yet configured.

Overview's **Cluster health** section uses compact colored stat cards backed by Prometheus `ALERTS`: firing critical instances, firing warnings, pending instances and distinct unready pods. Values refer to the end of the selected time range. Clicking a card preserves that range and opens its detail table; hidden alert-name/state/severity variables filter the shared alert table. The Unready pods card filters that same table to KubePodNotReady instances, with namespace, pod and state; clicking a pod name opens that exact pod in Rancher. Job-owned and scheduling-gated pods are excluded by the upstream rule, and firing begins after 15 minutes; pending instances are visible sooner. Watchdog and InfoInhibitor are hidden. Zero fallback requires a successful Prometheus self-scrape. Native Grafana Alerting pages remain available for full rule details and annotations, including the existing Rancher resource links.

The 12 dashboards retained for Rancher integration use plain titles without a prefix and live in the **Rancher** folder. Their UIDs, variables and embedding paths are preserved. The unused `rancher-home-1` template is excluded by the Helm post-renderer, including its ConfigMap, so upgrades do not restore it. Overview now includes host CPU, memory and local-filesystem utilization gauges with used/total values, plus capacity-weighted cluster CPU and memory trends. Host totals are not Kubernetes allocatable resources; local filesystems are deduplicated per node and device. Other Rancher templates and kube-prometheus-stack defaults remain available in **Kubernetes Diagnostics**. Grafana sidecar folder annotations and filesystem folder provisioning keep this organization across upgrades.

The `monitoring_rancher` Helm post-renderer normalizes titles and groups Rancher dashboards. Rancher supplies node addresses with its default exporter port `9796`, while our exporter uses `9100`. The Node and Node Detail dashboards retain that URL parameter and resolve the actual exporter instance by node IP using a hidden query variable. Their Node selector displays `nodename` (socrat-0/1/2/3) while retaining the exporter address as its query value through Grafana named text/value captures. All panels use the resolved instance, preserving existing metrics and history. The monitoring checker exercises this path for every node. Both embedded node dashboards also show CPU temperature in °C, with individual core labels where supplied by hardware. The query selects only CPU chips (`coretemp`, `k10temp`, `zenpower`), excluding disk/GPU sensors; unlabeled CPU sensors retain their sensor ID. socrat-0 exposes per-core readings, socrat-1/3 expose a shared CPU sensor, and socrat-2 exposes none. Missing sensor data is not converted to zero. For the embedded Cluster Nodes dashboard it joins original queries with `node_uname_info{job="node-exporter"}` on `instance` and uses `nodename` in legends. It preserves metric values and existing Prometheus labels/history. Apply chart changes through `playbooks/monitoring.yml --tags monitoring_base,monitoring_k3s,monitoring_rancher` so upgrades keep the customization; the renderer requires Python PyYAML on socrat-0.

The **LLM** dashboard adds GPU temperature/utilization, vLLM and LiteLLM request metrics, and the separate switcher queue. Collection and rollout details are in [LLM monitoring](monitoring-llm.md).

Node and GPU graphs aggregate away exporter pod identity so a node-exporter rollout does not create duplicate legend entries over historical time ranges. Node gauges retain the node name; disk and network graphs also retain the device, GPU graphs retain GPU identity, and CPU temperature graphs retain chip and sensor identity. Gauges are averaged rather than summed across exporter identities. The base monitoring Helm post-renderer applies the same normalization to the five bundled Node Exporter dashboards, including their recording-rule queries. This changes dashboard queries only; stored metrics and scrape labels remain intact.

Every data panel has an English description available from the information icon beside its title. Descriptions explain the measurement, units, time window and relevant missing-data behavior. The four primary dashboards store descriptions in their JSON sources. Template dashboards use the versioned catalog in `deploy/monitoring/dashboard-descriptions/`, applied by both Helm post-renderers through `ansible/files/dashboard_descriptions.py`. Rendering fails if a new template panel has no catalog entry, so chart upgrades cannot silently introduce undocumented panels. Row headings and static text panels are excluded. Known display-unit corrections for Grafana latency, CoreDNS cache entries and Node Exporter network drops/disk I/O saturation are applied with the descriptions; metric queries remain unchanged.

## Verification

Run from the repository with working SSH access to socrat-0:

```sh
python3 scripts/check-monitoring.py
python3 scripts/check-dashboard-descriptions.py
```

The checker uses Kubernetes Service proxy requests over SSH, without a public Prometheus endpoint or a local port-forward. It verifies every active scrape target, exporter/kubelet coverage against the current node list, etcd leadership, representative metrics, local persistent volume placement, memory requests/limits and anonymous WireGuard Grafana access, internal Viewer access, absence of a permanent Grafana Ingress, and the ingress default HTTP 404 body from an external VPS both with and without forged WireGuard and LAN forwarding headers. It does not retrieve administrator credentials.

The description checker reads every provisioned dashboard and requires complete panel coverage and exact agreement with the repository descriptions.

The Grafana URL and SSH aliases can be overridden using `--grafana-url`, `--ssh-host` and `--external-ssh-host`. Defaults are `socrat-0` for the WireGuard and LAN probes and `socrat-2-direct` for the external probe. Address overrides are `--grafana-private-address` (default `10.250.0.3`), `--grafana-private-source` (default `10.250.0.1`) and `--grafana-public-address` (default `109.173.40.247`). The private probe binds to the WireGuard source interface; public probes explicitly use the public address so private DNS cannot accidentally turn them into private-access tests. TLS verification is strict for private Grafana access. Only the negative public probes allow the ingress default certificate, since that endpoint no longer has a Grafana hostname certificate; they require the default 404 body and do not accept Grafana content. Temporary cert-manager HTTP-01 challenge paths are allowed during private certificate renewal, but no application route is allowed. A failed check exits nonzero and reports its failing condition. The checker waits up to 120 seconds for discovered targets to become healthy; override this with `--wait-seconds`. Real failures still fail the check at the deadline. Immediately after deployment, allow at least two scrape intervals before expecting every series.

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
ansible-playbook playbooks/monitoring.yml --ask-become-pass
```

Kubernetes deployment uses the existing administration access on socrat-0. The private DNS play uses sudo on the DNS nodes. Tags `monitoring_base`, `monitoring_k3s`, `monitoring_rancher`, `monitoring_access` and `monitoring_dns` allow scoped updates. The private gateway role preserves existing Syncthing Helm values and authentication, adding only the Grafana virtual host and its certificate.

After the external-quorum rebalance, etcd metrics are collected from socrat-0/2/3 and API metrics from socrat-0/1/3. During a known node outage, `-e '{"monitoring_wait_for_daemonsets":false,"monitoring_k3s_wait":false}'` allows configuration updates without waiting for DaemonSet pods on that unavailable node. Deployment and StatefulSet rollout checks remain enabled. Verify the online targets separately; these options do not make missing targets healthy, and the full monitoring checker still requires all nodes to recover.

Keep Helm values and provisioned dashboards in the repository. Apply changes through the Ansible monitoring playbook. Before a chart upgrade, inspect release notes and CRD requirements, capture current Helm values and Kubernetes workload/PVC metadata, and preserve the Grafana database and credentials. Never uninstall or delete persistent claims as a troubleshooting shortcut: the current storage class uses the Delete reclaim policy.

When disk usage grows, first inspect Prometheus series cardinality and retention, container image usage, and other workloads on socrat-1. Reducing retention is preferable to deleting unrelated data. The initial deployment does not authorize additional backup deletion.

## Verified deployment on 2026-10-16

All four nodes and all 30 scrape targets passed the verification script, including three etcd members and both API servers. The Socrat Overview dashboard was loaded by Grafana. At initial installation, public HTTPS used Basic authentication; it was subsequently replaced with WireGuard-only anonymous viewing. The current access checks are described above; etcd metrics rejected unauthenticated requests and accepted the private token on all three nodes.

Prometheus and Grafana pods were restarted independently. The same historical Prometheus samples and all three PVC identities survived. A temporary annotation written to Grafana's database also survived its restart and was removed after verification. The 87 pre-existing namespace, PVC, Deployment and StatefulSet identities were unchanged.

Measured monitoring pod memory was approximately 1.5 GiB across the cluster, with about 37 GiB disk space remaining on socrat-1. These are post-install observations, not forecasts. Rancher proxy health and generated embedding paths were checked through the Kubernetes service proxy; an authenticated Rancher browser session was not available for visual verification.

## WireGuard-only access verification

After removing the ingress password layer, the private gateway returned 200 without credentials from the socrat-wg network. It also ignored stale Basic credentials sent by a browser. The earlier implementation retained a public ingress that returned 403. That ingress, its Helm release and its public TLS Secret were removed from the cluster and deployment source. Live checks confirmed no application route, strict-TLS private access, and the same default public 404 response as 0.socrat.alchemmist.xyz, including requests with forged forwarding headers. All three private DNS servers returned `10.250.0.3` for the Grafana hostname. The full monitoring checker remained green, and Syncthing device identities, folder paths and pause states matched the pre-change snapshot.

Client setup is separate from server verification: install the macOS resolver and enable socrat-wg before opening the page. Ordinary home LAN access does not substitute for the WireGuard connection.


## Selected-node diagnostics

Nodes shows one selected node by name. Its Node alerts section uses compact colored tiles backed by Prometheus alerts. The original six cover Ready, MemoryPressure, DiskPressure, PIDPressure, scheduling disabled and node-exporter freshness. Normal is green, Pending amber, Firing red; a firing cordon alert is blue because maintenance may be intentional. Each tile links to the exact Rancher node. A missing Kubernetes-state scrape or stale rule evaluation shows No telemetry instead of a healthy zero.

KubeNodeNotReady (15m) and KubeNodePressure (5m) are owned by monitoring-k3s and disabled in the base chart to avoid duplicate rules. Both still evaluate cordoned nodes. SocratNodeSchedulingDisabled fires at info severity after 15m. SocratNodeMetricsStale detects samples older than 2m or no recorded sample in 24h, with a further 1m pending period. Its timestamp recording survives exporter target removal; deleted Kubernetes nodes are excluded. These rules populate the existing alerting stack; this change does not add notification delivery.

Kubernetes workload panels show Running and Unready pods, selected-period container restarts, and the top CPU/memory pods with direct Rancher links. Resource reservations compare container usage, declared regular-container requests and limits, and Kubernetes allocatable capacity. Effective scheduler requests (including init-container maxima and overhead) are not currently exported, so the panels explicitly label the available container-level totals. Bottleneck panels show CPU iowait/steal and Linux PSI for CPU, memory and I/O. PSI is time spent stalled, not resource utilization; absent PSI measurements are not replaced with zero.

Promtool synthetic cases in tests/node-health.test.yml exercise the alert thresholds without changing node state or interrupting connectivity. Replace its rule_files placeholder with the rendered socrat.nodes.health rule file when running promtool test rules.


### Hardware and performance alerts

The node alert strip also shows CPU temperature, hardware thermal throttling, CPU/memory/I/O PSI, CPU steal, disk space, inodes and container CPU throttling. These panels remain filtered by the selected node. Hardware-capability absence is gray N/A only while the source collector and rule group are healthy; a previously observed metric disappearing is No telemetry. VPS hosts normally expose neither CPU temperatures nor thermal throttle counters. Container CFS counters are also absent on nodes without corresponding measured workloads.

New rules live only in socrat.nodes.hardware:

- SocratNodeCPUTemperatureHigh: less than 10 °C headroom for 5m. Use the hardware CPU critical temperature when present. Only socrat-1 has a model-specific fallback: its verified Ryzen 7 7840HS limit is 100 °C ([AMD specification](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-7000-series/amd-ryzen-7-7840hs.html)). Revisit this fallback before replacing that CPU. GPU/NVMe sensors are excluded.
- SocratNodeThermalThrottling: any core or package thermal event in a rolling 5m window, sustained for 2m. The event counter is not a percentage of lost performance.
- SocratNodeResourceContention: Linux PSI some over5m exceeds25% for CPU or10% for memory/I/O, sustained10m. Resource labels distinguish the three instances. PSI measures task stalls; existing utilization, load-average, disk-queue and Kubernetes eviction-pressure alerts remain distinct.
- SocratNodeCPUStealHigh: CPU steal exceeds10% averaged across CPUs over5m, sustained15m.

No new disk-space, inode or container-quota rules are created. Their cards reuse NodeFilesystemSpaceFillingUp/NodeFilesystemAlmostOutOfSpace, NodeFilesystemFilesFillingUp/NodeFilesystemAlmostOutOfFiles, and CPUThrottlingHigh. Filesystem instances are matched to the selected node by exporter instance; container-throttling instances by kubelet_node_name, retaining the worst state across all affected containers. Rule groups are checked for freshness before a healthy state is displayed. CPUThrottlingHigh remains informational and displays blue when firing.

Synthetic tests in tests/node-hardware.test.yml cover thresholds, pending durations, recovery, absent sensors, exporter duplication, CPU-sensor filtering, critical-limit precedence and package-only thermal events. They run offline in a disposable Promtool pod without changing real node conditions.
