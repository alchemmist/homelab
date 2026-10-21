# Socrat monitoring

The first phase installs `kube-prometheus-stack` in `cattle-monitoring-system`: Prometheus, Grafana, Alertmanager, kube-state-metrics and node-exporter. It collects metrics from every current cluster node, including socrat-3. Loki, Alloy, Telegram delivery and telephone alerts are separate phases.

Prometheus runs on socrat-0 and scrapes every 5 seconds. Grafana, Alertmanager and their supporting controllers stay on socrat-1. Node-exporter runs on every node. Dashboards keep the datasource uid `prometheus`, and that datasource reads Thanos Query. Alerts are still evaluated by the local Prometheus. Rancher integration and the private Grafana gateway share this stack; they do not create a second Prometheus.

## Container resource budgets

`ansible/playbooks/container-resources.yml` manages measured per-workload requests and selective CPU limits through the native `socrat-container-resource-defaults` admission policy. The authoritative catalog is `ansible/vars/container-resources.yml`; see [resource budgets](resource-budgets.md) for measurements, per-container values, capacity checks, rollout and rollback.

Ordinary services can burst CPU without a quota. Open Terminal, vLLM and SearXNG retain explicit caps. Memory and ephemeral-storage limits remain safety ceilings, not capacity reservations. Unknown workloads receive fallback requests and memory/storage limits but no automatic CPU cap. GPU/custom resources remain intact. Pod admission does not manage host K3s/etcd services.

Existing Pods change only through an explicitly enabled serial reconciliation (`-e container_resource_policy_reconcile=true`), with UID-guarded Eviction, PodDisruptionBudgets and replacement readiness checks. Completed Pods are excluded. The role validates policy syntax before activation and checks synthetic Pods afterward, before eviction; updating an already-bound policy affects new Pods immediately.

## Storage and availability

Grafana and Alertmanager stay on socrat-1 and explicitly select `local-path`, because this cluster also has an NFS storage class. Prometheus runs on socrat-0. Its local TSDB is a 12-hour scratch copy. The long archive is Thanos. socrat-2 is not part of the cascade.

| Workload | Where | What is kept |
| --- | --- | --- |
| Prometheus | socrat-0, 10 GiB local-path PVC | 12 hours of 5-second samples, no size quota, compaction disabled |
| Thanos raw | socrat-0, `/var/lib/socrat-thanos` | 5 days of raw blocks, plus the 5-minute blocks still needed to build the hour |
| Thanos 5-minute shelf | socrat-1, one-disk MinIO | 5-minute blocks for 30 days |
| Thanos hourly shelf | socrat-3, one-disk MinIO | hourly blocks for 730 days |
| Grafana | socrat-1, 1 GiB | Persistent database and settings |
| Alertmanager | socrat-1, 1 GiB | Persistent silences and notification state |

Local-path PVC sizes do not enforce filesystem quotas. At about 150 thousand series the steady cascade is about 22 GiB on socrat-0, about 7 GiB of 5-minute blocks on socrat-1, and about 29 GiB of hourly blocks on socrat-3 after two years. Those are estimates, not quotas. Low disk raises a warning. Raw and 5-minute blocks are removed only after the next coarser copy has been checked. Hourly blocks older than 730 days are deleted on socrat-3.

The Grafana datasource uid `prometheus` points at Thanos Query on socrat-1. Dashboard JSON is not rewritten. Alerts are evaluated by Prometheus on socrat-0 and sent to Alertmanager on socrat-1. If socrat-0 is down, fresh samples and alert evaluation stop with it; Grafana stays up. If socrat-3 is offline, graphs lose only hourly blocks that have already moved there. Alertmanager's receiver discards notifications intentionally; delivery is not configured yet.

Moving Prometheus off socrat-1 deletes its current TSDB and does not copy the old 30-second history into Thanos. Run `ansible-playbook playbooks/monitoring.yml -e monitoring_prometheus_relocate=true` from `ansible/`. Without that flag the stack role refuses the upgrade while the Prometheus volume is still on socrat-1. Grafana and Alertmanager claims are not deleted.

## Metrics and access

Standard collectors cover node CPU, memory, filesystem and network use, pod state and restarts, kubelet/container metrics and the Kubernetes API. K3s has a shared metrics registry; separate scheduler/controller-manager endpoints must not be assumed to behave like a kubeadm installation. Etcd collection uses the dedicated authenticated monitoring endpoint on each of its three members, rather than exporting etcd client credentials to Prometheus.

The API collector uses the two control-plane WireGuard addresses and excludes the duplicate legacy socrat-0 LAN endpoint. Home-node kubelet scrapes drop duplicated control-plane metric families while retaining kubelet metrics; cAdvisor and probe collectors remain intact. Kubelet serving certificates are verified against the cluster CA. Exporters listen on private node addresses, and the etcd proxy listens only on WireGuard port 9238 with bearer authentication.

Grafana is available at [grafana.socrat.alchemmist.xyz](https://grafana.socrat.alchemmist.xyz/d/socrat-overview) only through the `socrat-wg` WireGuard network. Viewing dashboards requires no login. Grafana sets `server.root_url` to `https://grafana.socrat.alchemmist.xyz/`, so copied dashboard/panel links and short-link redirects use the private domain rather than localhost. Host enforcement and subpath serving remain disabled for Rancher proxy embedding. Home LAN membership alone does not grant access. There is no permanent public Grafana Ingress. Requests sent explicitly to the public ingress address receive its default HTTP 404 response, including requests with forged WireGuard or LAN `X-Forwarded-For` headers.

Private DNS resolves the Grafana hostname to `10.250.0.3`. The private HTTPS gateway on socrat-1 forwards WireGuard traffic to Grafana; no public Grafana route is installed. Clients need both the WireGuard connection and private DNS resolution. The checker bypasses DNS explicitly while preserving the hostname and validating TLS, so its private probe verifies the gateway separately from client DNS configuration.

`monitoring-private-dns.yml` publishes the record on all three existing private DNS servers. The macOS `wireguard_admin_client` role installs one suffix resolver `/etc/resolver/socrat.alchemmist.xyz` pointing to `10.250.0.2`, `10.250.0.3` and `10.250.0.1`. It covers Grafana and future service names without per-domain client changes. Installing it requires macOS administrator access once. Ordinary clients can instead include these DNS servers in their WireGuard profiles; existing imported profiles need a one-time update. Connect the existing `socrat-wg` tunnel before opening Grafana; the private hostname record exists in our private DNS. Public wildcard DNS can still return an address for this name, as it does for the node hostnames; that is not a dedicated public Grafana record and does not provide a Grafana route. Removing Grafana’s ingress does not imply public NXDOMAIN.

Grafana's anonymous Viewer access supports private viewing and Rancher's authenticated service proxy and embedded dashboards. Administrative operations still require Grafana's `admin` account. The `socrat-grafana-admin` Secret contains `admin-user` and `admin-password`; secrets must not be placed in Git or printed by verification commands. Do not expose the anonymous Grafana Service through an unrestricted ingress or NodePort, and do not trust arbitrary forwarded headers as proof of WireGuard access.

To copy the Grafana password into the macOS clipboard without printing it or writing a plaintext password file:

```sh
ssh socrat-0 'kubectl -n cattle-monitoring-system get secret socrat-grafana-admin -o jsonpath="{.data.admin-password}"' | base64 --decode | pbcopy
```

Paste it directly into the login form or a password manager. The clipboard contains a secret until replaced; avoid clipboard-history sharing. Retrieve the username separately with the same command replacing `admin-password` with `admin-user` and omitting `| pbcopy`.

## Socrat Overview

The default home is **Overview**, with a dark default theme and navigation to **Nodes** and **Services**. Together with **LLM**, these are the four dashboards at the root; the 12 embedded Rancher dashboards live in the **Rancher** folder. These 16 dashboards are the complete installed set. Numeric Stat panels across all four primary dashboards use compact 2–3-row layouts with 18px values; existing 1–2-row node alert tiles retain their hierarchy. LLM aggregate percentages and request/error counts follow the same compact style as latency percentiles. Metric queries, units and model labels are preserved. The 12 embedded Rancher dashboards contain only time-series panels. Overview capacity gauges retain percentages and derive used/total captions from current queries through native join, field organization and rows-to-fields transformations; memory and disk captions use GiB. Separate used/total Stat panels have been removed. Introductory logo/title/description panels are omitted so metrics appear immediately. The supplied brand asset remains versioned in `deploy/monitoring/branding/socrat-cover.png` but is not displayed on these dashboards.

The primary dashboards are versioned as JSON in `charts/monitoring-k3s/dashboards/` and published by the chart. **Overview** (UID `socrat-overview`, retained for existing links) summarizes readiness, key services, per-node resources, active alerts, control-plane redundancy and restarts. **Nodes** (`socrat-nodes`) compares CPU, load, memory, swap, filesystems, disk I/O, interfaces, temperature and uptime, with a node selector. Temperatures are available only where sensors exist. **Services** (`socrat-services`) combines replica readiness, resources and troubleshooting for application workloads, with a service selector. Overview service tiles use explicit HTTP/TCP probes; external-site probes and notification delivery are separate work.

Overview's **Cluster health** section uses large colored stat cards backed by Prometheus `ALERTS`: firing critical instances, firing warnings, pending instances and distinct unready pods. Values refer to the end of the selected time range. Clicking opens Grafana Alerting filtered by severity/state or KubePodNotReady; that list shows current state. The former Needs attention section and its alert-details table have been removed. Watchdog and InfoInhibitor are hidden. Zero fallback requires a successful Prometheus self-scrape. Native alert detail pages expose instances and resource annotations.

The 12 dashboards retained for Rancher integration use plain titles without a prefix and live in the **Rancher** folder. Their UIDs, variables and embedding paths are preserved. The Helm post-renderer retains only the 12 embedded dashboard UIDs. It excludes every other Rancher template, including `rancher-home-1`, and removes empty dashboard ConfigMaps so upgrades do not restore them. Overview now includes host CPU, memory and local-filesystem utilization gauges with used/total captions inside each gauge, plus capacity-weighted cluster CPU and memory trends. Host totals are not Kubernetes allocatable resources; local filesystems are deduplicated per node and device. The 38 **Kubernetes Diagnostics** dashboards have been removed. Grafana retains the empty historical folder until an administrator deletes it through the folder API; the deployment no longer provisions content into it. kube-prometheus-stack default dashboards are disabled with `grafana.defaultDashboardsEnabled: false`; metric collection, recording rules and alerts remain enabled. Additional dashboards can be added deliberately when needed. Grafana sidecar folder annotations and filesystem folder provisioning keep this organization across upgrades.

The `monitoring_rancher` Helm post-renderer normalizes titles and groups Rancher dashboards. Rancher supplies node addresses with its default exporter port `9796`, while our exporter uses `9100`. The Node and Node Detail dashboards retain that URL parameter and resolve the actual exporter instance by node IP using a hidden query variable. Their Node selector displays `nodename` (socrat-0/1/2/3) while retaining the exporter address as its query value through Grafana named text/value captures. All panels use the resolved instance, preserving existing metrics and history. The monitoring checker exercises this path for every node. Both embedded node dashboards also show CPU temperature in °C, with individual core labels where supplied by hardware. The query selects only CPU chips (`coretemp`, `k10temp`, `zenpower`), excluding disk/GPU sensors; unlabeled CPU sensors retain their sensor ID. socrat-0 exposes per-core readings, socrat-1/3 expose a shared CPU sensor, and socrat-2 exposes none. Missing sensor data is not converted to zero. For the embedded Cluster Nodes dashboard it joins original queries with `node_uname_info{job="node-exporter"}` on `instance` and uses `nodename` in legends. It preserves metric values and existing Prometheus labels/history. Apply chart changes through `playbooks/monitoring.yml --tags monitoring_base,monitoring_k3s,monitoring_rancher` so upgrades keep the customization; the renderer requires Python PyYAML on socrat-0.

The **LLM** dashboard adds GPU temperature/utilization, vLLM and LiteLLM request metrics, and the separate switcher queue. Collection and rollout details are in [LLM monitoring](monitoring-llm.md).

Node and GPU graphs aggregate away exporter pod identity so a node-exporter rollout does not create duplicate legend entries over historical time ranges. Node gauges retain the node name; disk and network graphs also retain the device, GPU graphs retain GPU identity, and CPU temperature graphs retain chip and sensor identity. Gauges are averaged rather than summed across exporter identities. The base monitoring Helm post-renderer retains this normalization for the five optional Node Exporter templates if they are explicitly re-enabled. This changes dashboard queries only; stored metrics and scrape labels remain intact.

Every data panel has an English description available from the information icon beside its title. Descriptions explain the measurement, units, time window and relevant missing-data behavior. The four primary dashboards store descriptions in their JSON sources. The retained Rancher dashboards use `deploy/monitoring/dashboard-descriptions/rancher-core.json`; the other catalogs are historical references for optional templates and are not part of the installed dashboard audit. Descriptions are applied through `ansible/files/dashboard_descriptions.py`. Rendering fails if a new template panel has no catalog entry, so chart upgrades cannot silently introduce undocumented panels. Row headings and static text panels are excluded. Known display-unit corrections for Grafana latency, CoreDNS cache entries and Node Exporter network drops/disk I/O saturation are applied with the descriptions; metric queries remain unchanged.

## Service availability tiles

Overview replaces the key-service readiness percentages with 31 compact service-name tiles covering 33 endpoints. The catalog is `serviceProbes.targets` in `charts/monitoring-k3s/values.yaml`. A dedicated blackbox exporter on socrat-1 probes each target every 5 seconds with a 3-second timeout. HTTP probes check application health/readiness endpoints or a safe application response. TCP probes cover the VPN listener, 3xUI panel, image proxy, PostgreSQL services and NFS; they do not verify authentication or an end-to-end transaction. Syncthing has one tile and one rule with separate alert instances for its three nodes; the tile becomes unhealthy if any instance fails and requires all three fresh results to show green. Grafana MCP exposes an internal health-only Service; a narrow NetworkPolicy allows the probe pod to reach the private LLM services.

Each tile has its own `SocratService...Unavailable` Prometheus rule, Pending during failed checks and Firing after 2 minutes. Green requires a successful probe, fresh successful collection and fresh rule evaluation; missing telemetry is gray, never a synthetic success. The separate collector-unavailable rule warns about failed monitoring. Only the service name appears on the tile. Ansible resolves native Grafana rule links after Prometheus loads the rules. All targets are checked from inside the cluster: these tiles do not establish that public DNS, external ingress, VPN tunneling or the monitoring node itself will survive a site outage.

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

Kubernetes deployment uses the existing administration access on socrat-0. The private DNS play uses sudo on the DNS nodes. Tags `monitoring_thanos`, `monitoring_base`, `monitoring_k3s`, `monitoring_rancher`, `monitoring_access` and `monitoring_dns` allow scoped updates. `monitoring_base` also installs Thanos. Retargeting Prometheus from socrat-1 to socrat-0 additionally requires `-e monitoring_prometheus_relocate=true`. The private gateway role preserves existing Syncthing Helm values and authentication, adding only the Grafana virtual host and its certificate.

After the external-quorum rebalance, etcd metrics are collected from socrat-0/2/3 and API metrics from socrat-0/1/3. During a known node outage, `-e '{"monitoring_wait_for_daemonsets":false,"monitoring_k3s_wait":false}'` allows configuration updates without waiting for DaemonSet pods on that unavailable node. Deployment and StatefulSet rollout checks remain enabled. Verify the online targets separately; these options do not make missing targets healthy, and the full monitoring checker still requires all nodes to recover.

Keep Helm values and provisioned dashboards in the repository. Apply changes through the Ansible monitoring playbook. Before a chart upgrade, inspect release notes and CRD requirements, capture current Helm values and Kubernetes workload/PVC metadata, and preserve the Grafana database and credentials. Never uninstall or delete persistent claims as a troubleshooting shortcut: the current storage class uses the Delete reclaim policy. The relocate flag is the exception, and it deletes only the Prometheus TSDB claim while that claim is still bound to socrat-1.

When disk usage grows, first inspect series cardinality and which Thanos resolution is using the space. A warning for low disk does not delete blocks. The shipping job removes 5-minute blocks on socrat-1 only after their hourly copy is on socrat-3, and only when they are older than 30 days or free space there falls below about 40 GiB.

## Verified deployment on 2026-10-16

All four nodes and all 30 scrape targets passed the verification script, including three etcd members and both API servers. The Socrat Overview dashboard was loaded by Grafana. At initial installation, public HTTPS used Basic authentication; it was subsequently replaced with WireGuard-only anonymous viewing. The current access checks are described above; etcd metrics rejected unauthenticated requests and accepted the private token on all three nodes.

Prometheus and Grafana pods were restarted independently. The same historical Prometheus samples and all three PVC identities survived. A temporary annotation written to Grafana's database also survived its restart and was removed after verification. The 87 pre-existing namespace, PVC, Deployment and StatefulSet identities were unchanged.

Measured monitoring pod memory was approximately 1.5 GiB across the cluster, with about 37 GiB disk space remaining on socrat-1. These are post-install observations, not forecasts. Rancher proxy health and generated embedding paths were checked through the Kubernetes service proxy; an authenticated Rancher browser session was not available for visual verification.

## WireGuard-only access verification

After removing the ingress password layer, the private gateway returned 200 without credentials from the socrat-wg network. It also ignored stale Basic credentials sent by a browser. The earlier implementation retained a public ingress that returned 403. That ingress, its Helm release and its public TLS Secret were removed from the cluster and deployment source. Live checks confirmed no application route, strict-TLS private access, and the same default public 404 response as 0.socrat.alchemmist.xyz, including requests with forged forwarding headers. All three private DNS servers returned `10.250.0.3` for the Grafana hostname. The full monitoring checker remained green, and Syncthing device identities, folder paths and pause states matched the pre-change snapshot.

Client setup is separate from server verification: install the macOS resolver and enable socrat-wg before opening the page. Ordinary home LAN access does not substitute for the WireGuard connection.


## Selected-node diagnostics

Nodes shows one selected node by name. Its Node alerts section uses compact colored tiles backed by Prometheus alerts. The original six cover Ready, MemoryPressure, DiskPressure, PIDPressure, scheduling disabled and node-exporter freshness. Normal is green, Pending amber, Firing red; a firing cordon alert is blue because maintenance may be intentional. Tiles link to Grafana alert rules; the header separately links to the selected Rancher node. A missing Kubernetes-state scrape or stale rule evaluation shows No telemetry instead of a healthy zero.

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


### Node alert coverage

Nodes groups supported checks into 30 alert tiles. The Systemd collector and service restart metrics are enabled on all four nodes through the existing read-only host mount and host D-Bus socket. Evictions is an event counter: an absent series with fresh healthy kubelet collection and rule evaluation means no observed events, not unsupported telemetry. Certificates uses K3s-native remaining-lifetime metrics and SocratNodeCertificateExpiration (less than 30 days for 15 minutes), replacing unsupported kubelet certificate-manager rules. RAID/bonding tiles and rules are removed because those features are not configured. CPU thermal combines temperature alerts with hardware throttle events where available: socrat-0 exports both, while socrat-1 exposes temperature only. Missing hardware counters are not simulated.

The additional groups cover node/kubelet reachability, readiness flapping, pod capacity, evictions, kubelet latency and certificates, CPU/memory load, disk I/O, network errors/interface flapping/conntrack, clock synchronization, file descriptors, textfile collector and systemd. Their descriptions enumerate the original rule names. Per-node alert groups exclude KubeletDown (all kubelets missing), TargetDown (service-level aggregation), and operator-level lookup errors because those are not individual-node conditions.

The new groups retain exporter and kubelet instance-to-node mappings for 24h. Active alerts are evaluated before the healthy-source fallback so losing a scrape does not hide an unreachable-node alert. Mixed CPU-load groups preserve informational firing in blue and warning firing in red. A group shows Clear only when its supporting metrics and sources are present; partial unsupported coverage is N/A, and failed collectors or previously present metrics disappearing are No telemetry. Evictions is the deliberate exception: Kubernetes creates its counter only after an event, so a healthy fresh kubelet with no counter is Clear. Certificate coverage uses actual K3s expiry telemetry. Tests in `tests/node-kubelet-telemetry.test.yml` cover expiry thresholds, recovery, lazy event counters, missing sources and active-alert precedence.


## Grafana memory headroom

On 2026-10-19 Grafana repeatedly hit its 768 MiB container memory limit (about 67 restarts over 12 hours). Kubernetes recorded OOMKilled; socrat-1 still had 6–7 GiB available. The chart-generated GOMEMLIMIT of 691 MiB left too little room for non-Go memory, other processes and transient overshoot. Main-process RSS reached about692 MiB while container RSS approached750–758 MiB.

Grafana now requests512 MiB, has a1536 MiB hard limit, and explicitly sets GOMEMLIMIT=1GiB. The latter is a soft Go runtime memory budget, not an RSS cap; the remaining container headroom covers other memory. Apply through monitoring_base. Existing PVCs, Grafana database, credentials and dashboards are preserved. Watch container restarts, OOM terminations, RSS/working set and Go-managed memory after changing the limit. This corrects demonstrated memory headroom pressure; it does not by itself prove the absence of a memory leak.


## Container OOM and restart alerts

The socrat.containers.health group applies across namespaces, including Grafana itself. SocratContainerOOMKilled checks a regular container's last termination reason OOMKilled and its timestamp within the previous10m, with a30s pending period. A stale retained OOM reason does not keep the alert firing forever, and future timestamps are excluded. This is sampled Kubernetes state: a later termination can overwrite the recorded reason, so it is not a complete event log.

SocratContainerRestartsFrequent checks at least3 estimated restarts over30m for1m, including regular and init containers. It does not require continuous NotReady or CrashLoopBackOff. Both rules deduplicate kube-state-metrics replicas and retain namespace, pod, container, pod UID and node; pod-UID joins prevent attribution to a replacement pod with the same name. Each alert has a direct Rancher pod URL.

Nodes includes compact OOM and Restarts cards linked to their native Grafana alert rules. No notification receiver is configured by this change.

Ten synthetic cases in tests/container-health.test.yml cover first-observed/recovered OOM, stale and non-OOM terminations, future timestamps, restart bursts despite Ready, low counts, counter resets, init-container restarts and duplicate scrapes. The OOM expression was also checked against historical Grafana metrics from2026-10-19 before the memory fix.


## Node alert navigation

The Nodes header has an Open node in Rancher dashboard link that interpolates the selected node. Alert tiles instead link to native Grafana rule-detail pages. A tile with multiple rules offers each rule separately, including severity when warning and critical variants share a name. Direct rule pages show the rule and its instances; they are not restricted to a single node instance.

Native datasource-managed rule identifiers include the rule file UID, group, name and a definition fingerprint. The monitoring_k3s role therefore installs rules first, waits for the live Prometheus definitions to match the Kubernetes definitions, and generates nodeAlertLinks Helm values before publishing the final dashboard. Expressions are canonicalized through Prometheus format_query. Link generation follows the pinned Grafana13.2.4 identifier format and checks current feature toggles; verify compatibility when upgrading Grafana. Reapply monitoring_k3s after changing alert definitions, including rules from monitoring_base. Source JSON retains name-search fallback links for standalone chart rendering; the managed deployment replaces these with direct links.

The resolver refuses missing or stale rule definitions rather than emitting an outdated link. Tests cover native fingerprint fixtures, query normalization, severity variants and convergence after rule/UID changes. Rule expressions and evaluation behavior are unchanged by this navigation feature.
