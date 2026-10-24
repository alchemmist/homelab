# Container resource budgets

Measured on 2026-10-20. Source of truth: `ansible/vars/container-resources.yml`, applied by `ansible/playbooks/container-resources.yml`. No credentials are stored here.

## Policy

- Every known regular and init container has explicit CPU, memory and ephemeral-storage requests. These are scheduling budgets, not preallocated RAM or an availability guarantee.
- CPU can burst without a limit for ordinary applications and infrastructure. Explicit CPU caps remain for Open Terminal (6), its cleanup sidecar (100m), vLLM (8) and SearXNG (1).
- Memory and ephemeral-storage limits remain individual safety ceilings. Their sum may exceed node capacity; this is controlled overcommit, not a guarantee that all workloads can peak together.
- The native admission policy overrides container budgets for matching namespace/controller/name profiles, including source-defined CPU caps where `removeCpuLimit: true`. Helm/operator templates retain their upstream values; effective Pod resources are intentionally managed by this catalog. Update the catalog when changing a budget, otherwise admission will override a chart-only change.
- Unprofiled containers retain explicit settings; missing requests fall back to 10m CPU / 32Mi RAM / 16Mi ephemeral storage and missing memory/storage limits to 1Gi / 4Gi. CPU limits are not injected. Unknown workloads must be audited and added, not mistaken for measured sizing.
- Host K3s/etcd and other system services are outside Pod admission. GPU extended resources are preserved. PVC/NFS/hostPath data is outside ephemeral-storage accounting.

## Evidence and sizing

Prometheus contained about 83.9 hours of history, not a full seven days. CPU percentiles use 5-minute rates sampled every 5 minutes; CPU maxima use 1-minute rates. Memory maxima use raw working-set samples. Statistics are maxima across pod generations/replicas, not pooled workload percentiles. Short-lived init containers have conservative explicit budgets rather than invented measurements.

Most existing CPU requests were retained: CPU scheduling capacity was not the bottleneck. Small infrastructure controllers received 25m rather than the previous generic 10m. Memory requests follow sustained working sets plus headroom, not the absolute simultaneous maximum. The historical runaway Chromium peak does not define normal Open Terminal demand. Existing declared memory limits were retained or increased; newly profiled formerly-defaulted controllers retain conservative headroom.

| Workload | Observed RAM p95 / max | New RAM request / limit | Reason |
| --- | --- | --- | --- |
| Rancher | 2724 / 3071 MiB | 2560Mi / 4096Mi | Reserve normal management load; avoid the old 3Gi ceiling |
| Grafana | 1360 / 1470 MiB | 1536Mi / 2048Mi | Protect normal use and dashboard bursts |
| Prometheus | 1624 / 1814 MiB | 2048Mi / 3072Mi | Room for queries, replay and compaction |
| LiteLLM | 1325 / 1406 MiB | 1536Mi / 4Gi | Worker baseline; retain burst ceiling |
| vLLM | 11309 / 16822 MiB | 12Gi / 24Gi | Loading peaks differ from steady state; GPU memory is separate |
| Open Terminal | 762 / 3894 MiB | 512Mi / 4Gi | Idle/interactive baseline; retain explicit runaway guard |
| VPN primary | 364 / 387 MiB | 448Mi / 768Mi | Protect critical service on small VPS |

Ephemeral-storage measurements from kubelet stats showed Rancher writable layers/logs near 2.1Gi, vLLM about 211Mi, LiteLLM 63Mi and WebUI 59Mi. Requests include realistic reservations and limits retain burst/log headroom; Open Terminal no longer inherits a 5Gi request merely because its limit is 5Gi. These measurements do not measure PVC contents.

## Placement check

The read-only `scripts/check-resource-budget.py` checks effective requests, including init/sidecar ordering, against node allocatable. This is not a scheduler, rolling-update or failure simulation. It does not equate unreserved requests with physically free RAM.

| Node | Proposed CPU requests / allocatable | Proposed RAM requests / allocatable | Unreserved RAM |
| --- | --- | --- | --- |
| socrat-0 | 3.575 / 20 | 19.02 / 31.04 GiB | 12310 MiB |
| socrat-1 | 1.855 / 16 | 10.19 / 14.71 GiB | 4631 MiB |
| socrat-2 | 0.440 / 2 | 1.52 / 1.92 GiB | 415 MiB |
| socrat-3 | 0.400 / 3.600 | 0.91 / 2.10 GiB | 1219 MiB |

socrat-2 is the tightest scheduling budget. socrat-3 had only about 419Mi physically available despite ample unreserved requests, with K3s (~1.1Gi RSS), Firefox and Happ accounting for substantial host-side use; do not migrate more workloads there based on requests alone. Reserving current workloads does not increase their actual RAM consumption immediately.

## Apply and verify

Run from `ansible/`:

```sh
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/container-resources.yml
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/container-resources.yml -e container_resource_policy_reconcile=true
```

Use the documented SSH inventory overrides when public multi-address DNS selects the wrong SSH entry point. The first command activates future-Pod admission but does not recreate running Pods. Existing binding means policy updates become active immediately. Server dry-run checks syntax before activation; synthetic Pod dry-runs validate behavior afterward and before evictions. Failed behavioral checks restore the previous admission configuration automatically. A dry-run never starts a workload.

The second command serially evicts noncompliant Pods with UID preconditions, respects PDBs, and waits for the same workload replacement to become Ready with desired resources. Single-replica services have brief interruptions. Stop on failure; do not bypass PDBs or readiness. Check actual node pressure, restarts and service probes after each batch.

Rollback requires restoring the previous policy/catalog and recreating affected Pods; removing only the binding does not revert existing Pod resources. Each playbook invocation preserves an independent `admission-backup-*` directory under `/home/alchemmist/.cache/homelab-resource-policy` and prints its location, so a later reconcile run does not overwrite the first snapshot. Keep a separate pre-change policy snapshot outside Git as well. Re-evaluate after a full week of representative load and after workload/version changes.

## Deployment verification — 2026-10-20

All 74 active Pods (91 regular/init containers) match the catalog and are Ready; all four nodes are Ready with no MemoryPressure, DiskPressure or PIDPressure. All 33 service probes succeeded after rollout. No OOM events were observed during the rollout window.

The scheduler redistributed some unpinned workloads during recreation; this is the verified final placement, not the earlier planning snapshot:

| Node | CPU requests | RAM requests / allocatable | Unreserved RAM |
| --- | --- | --- | --- |
| socrat-0 | 3.575 | 19.36 / 31.04 GiB | 11958 MiB |
| socrat-1 | 1.700 | 9.44 / 14.71 GiB | 5399 MiB |
| socrat-2 | 0.530 | 1.64 / 1.92 GiB | 287 MiB |
| socrat-3 | 0.465 | 1.19 / 2.10 GiB | 931 MiB |

The smallest scheduling margin is socrat-2 (~287Mi). Do not add workloads there merely because aggregate cluster capacity is available. Physical MemAvailable fluctuates independently; it was about 809Mi on both small nodes at final verification. Neither this snapshot nor requests guarantee survival of simultaneous peaks or node loss.

Verification: 41 resource-policy/budget unit tests; Ansible syntax check; server-side policy validation plus all 56 regular/init profile dry-runs; 18 Promtool scenarios for the quota tile. Live tile values are Clear on socrat-0/1 and N/A on socrat-2/3, which have no CPU-limited containers. CPU limits remain on exactly four containers (Open Terminal, cleanup sidecar, vLLM, SearXNG).

## Follow-up: offload auxiliary workloads from socrat-2

`ansible/playbooks/socrat-2-offload.yml` moves only `img-proxy`, `metrics-server` and `local-path-provisioner` to socrat-1. It refuses cluster-wide resource reconciliation, applies admission configuration first, and rolls out the selected deployments sequentially. The image proxy is updated through Helm with its previous values preserved; the two K3s controllers receive minimal node-selector patches.

The three profiles also specify `nodeSelector: {kubernetes.io/hostname: socrat-1}`. Admission enforces this placement for replacement Pods even if K3s regenerates a packaged Deployment. Other node-selector labels are preserved. The image proxy chart carries the same default. Changing placement requires updating the profile as well as the controller/chart, not just patching a Pod. No packaged K3s manifests are disabled or rewritten.

The migration frees 192Mi of memory requests on socrat-2: its total is now 1488Mi, leaving approximately 479Mi unreserved. Actual RAM usage is independent of that reservation. CoreDNS is the later exception: one replica is placed on socrat-2 and admission reserves 128Mi for it. That leaves roughly 350Mi of requests unreserved on a node with about 1.92Gi allocatable. The other replica stays on socrat-0. Metrics Server and new local-path volume provisioning now depend on socrat-1; existing volume data stays on its original nodes.

Verification on 2026-10-20: all three deployments Ready on socrat-1; metrics API returned all four nodes; image proxy returned HTTP 200 and an image through both public IPs; all 15 PV specifications and identities unchanged; resource audit found no mismatches across 74 active Pods. Final repeated checks found all four nodes Ready without pressure and 33/33 fresh successful service probes, including Wiki. An earlier transient Wiki probe failure was not reproduced or diagnosed; no Wiki changes were made. All 47 resource/budget and four offload scope unit tests passed, covering selector validation, unrelated-label preservation, wrong-node detection and the restricted rollout scope.

VPN, Remark42, edge ingress and node telemetry remain on socrat-2. Uptime Kuma runs on socrat-3. Syncthing no longer runs there: the node had no folders, and its `/srv/syncthing` directory is kept. The DaemonSet, probes and grouped tile cover socrat-0 and socrat-1.

## Reproduce the measurements

Run these instant Prometheus queries, then map pod owner references to workloads and take the maximum across replicas/generations. Do not average away a busy replica.

CPU p95 in cores:

```promql
quantile_over_time(0.95,(max by(namespace,pod,container)(rate(container_cpu_usage_seconds_total{container!="",container!="POD",namespace!=""}[5m])))[7d:5m])
```

Working-set p95 in bytes:

```promql
quantile_over_time(0.95,(max by(namespace,pod,container)(container_memory_working_set_bytes{container!="",container!="POD",namespace!=""}))[7d:5m])
```

Raw working-set maximum in bytes:

```promql
max by(namespace,pod,container)(max_over_time(container_memory_working_set_bytes{container!="",container!="POD",namespace!=""}[7d]))
```

Export current Pods and Nodes with `kubectl get pods -A -o json` and `kubectl get nodes -o json`, and the catalog as a JSON list. Then run `python3 scripts/check-resource-budget.py --pods pods.json --nodes nodes.json --profiles profiles.json`. Keep raw Pod exports outside Git because they can contain sensitive environment values.

## Per-container catalog

| Namespace / owner pattern / container | CPU request | CPU limit | RAM request | RAM limit | Ephemeral request / limit |
| --- | --- | --- | --- | --- | --- |
| blog / `^blog-[a-z0-9]+$` / blog | 20m | none | 32Mi | 256Mi | 64Mi / 1Gi |
| cats / `^cats-[a-z0-9]+$` / cats | 10m | none | 32Mi | 128Mi | 64Mi / 1Gi |
| cattle-capi-system / `^capi\-controller\-manager-[a-z0-9]+$` / manager | 25m | none | 96Mi | 512Mi | 64Mi / 1Gi |
| cattle-fleet-local-system / `^fleet\-agent-[a-z0-9]+$` / fleet-agent | 25m | none | 384Mi | 768Mi | 64Mi / 1Gi |
| cattle-fleet-system / `^fleet\-controller-[a-z0-9]+$` / fleet-controller | 25m | none | 160Mi | 512Mi | 64Mi / 1Gi |
| cattle-fleet-system / `^fleet\-controller-[a-z0-9]+$` / fleet-cleanup | 25m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| cattle-fleet-system / `^fleet\-controller-[a-z0-9]+$` / fleet-agentmanagement | 25m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| cattle-fleet-system / `^gitjob-[a-z0-9]+$` / gitjob | 25m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| cattle-fleet-system / `^helmops-[a-z0-9]+$` / helmops | 25m | none | 64Mi | 512Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^grafana\-mcp-[a-z0-9]+$` / grafana-mcp | 25m | none | 96Mi | 256Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-grafana-[a-z0-9]+$` / grafana-sc-dashboard | 25m | none | 96Mi | 256Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-grafana-[a-z0-9]+$` / grafana-sc-datasources | 25m | none | 96Mi | 256Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-grafana-[a-z0-9]+$` / grafana | 50m | none | 1536Mi | 2048Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-grafana-[a-z0-9]+$` / init-chown-data | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-kube\-state\-metrics-[a-z0-9]+$` / kube-state-metrics | 20m | none | 96Mi | 192Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-operator-[a-z0-9]+$` / kube-prometheus-stack | 30m | none | 96Mi | 256Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^monitoring\-service\-probes-[a-z0-9]+$` / blackbox-exporter | 25m | none | 64Mi | 128Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^rancher\-monitoring\-dashboards\-monitoring\-proxy-[a-z0-9]+$` / nginx | 50m | none | 32Mi | 256Mi | 16Mi / 256Mi |
| cattle-system / `^rancher-[a-z0-9]+$` / rancher | 250m | none | 2560Mi | 4096Mi | 2560Mi / 4Gi |
| cattle-system / `^rancher\-webhook-[a-z0-9]+$` / rancher-webhook | 20m | none | 192Mi | 384Mi | 64Mi / 1Gi |
| cattle-system / `^system\-upgrade\-controller-[a-z0-9]+$` / system-upgrade-controller | 25m | none | 96Mi | 256Mi | 64Mi / 1Gi |
| cattle-turtles-system / `^rancher\-turtles\-controller\-manager-[a-z0-9]+$` / manager | 25m | none | 160Mi | 600Mi | 64Mi / 1Gi |
| cert-manager / `^cert\-manager-[a-z0-9]+$` / cert-manager-controller | 50m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| cert-manager / `^cert\-manager\-cainjector-[a-z0-9]+$` / cert-manager-cainjector | 50m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| cert-manager / `^cert\-manager\-webhook-[a-z0-9]+$` / cert-manager-webhook | 20m | none | 64Mi | 256Mi | 64Mi / 1Gi |
| format-quorum / `^format\-quorum-[a-z0-9]+$` / format-quorum | 100m | none | 128Mi | 1024Mi | 64Mi / 1Gi |
| img-proxy / `^img\-proxy-[a-z0-9]+$` / nginx | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| kube-system / `^coredns-[a-z0-9]+$` / coredns | 100m | none | 128Mi | 256Mi | 64Mi / 1Gi |
| kube-system / `^local\-path\-provisioner-[a-z0-9]+$` / local-path-provisioner | 10m | none | 64Mi | 512Mi | 64Mi / 1Gi |
| kube-system / `^metrics\-server-[a-z0-9]+$` / metrics-server | 100m | none | 96Mi | 512Mi | 64Mi / 1Gi |
| kube-system / `^traefik-[a-z0-9]+$` / traefik | 100m | none | 256Mi | 512Mi | 64Mi / 1Gi |
| llm / `^litellm-[a-z0-9]+$` / litellm | 250m | none | 1536Mi | 4096Mi | 128Mi / 2Gi |
| llm / `^litellm\-branding-[a-z0-9]+$` / nginx | 10m | none | 16Mi | 64Mi | 16Mi / 256Mi |
| llm / `^litellm\-postgres-[a-z0-9]+$` / postgres | 100m | none | 256Mi | 1024Mi | 64Mi / 1Gi |
| llm / `^llm\-switcher-[a-z0-9]+$` / gateway | 100m | none | 160Mi | 512Mi | 64Mi / 1Gi |
| llm / `^monitoring\-llm\-status-[a-z0-9]+$` / collector | 10m | none | 32Mi | 96Mi | 64Mi / 1Gi |
| llm / `^open\-terminal-[a-z0-9]+$` / open-terminal | 250m | 6 | 512Mi | 4096Mi | 256Mi / 5Gi |
| llm / `^open\-terminal-[a-z0-9]+$` / browser-cleanup | 5m | 100m | 16Mi | 128Mi | 16Mi / 256Mi |
| llm / `^open\-webui-[a-z0-9]+$` / open-webui | 250m | none | 768Mi | 2048Mi | 128Mi / 2Gi |
| llm / `^open\-webui-[a-z0-9]+$` / prepare-tool-guard | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| llm / `^open\-webui\-gateway-[a-z0-9]+$` / nginx | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| llm / `^searxng-[a-z0-9]+$` / searxng | 100m | 1 | 384Mi | 768Mi | 64Mi / 512Mi |
| llm / `^vllm-[a-z0-9]+$` / vllm | 2 | 8 | 12288Mi | 24576Mi | 512Mi / 4Gi |
| lms / `^lms-[a-z0-9]+$` / lms | 50m | none | 96Mi | 512Mi | 64Mi / 1Gi |
| monori / `^monori-[a-z0-9]+$` / front | 10m | none | 32Mi | 512Mi | 64Mi / 1Gi |
| monori / `^monori\-back-[a-z0-9]+$` / back | 10m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| monori / `^monori\-sync-[a-z0-9]+$` / sync | 10m | none | 96Mi | 512Mi | 64Mi / 1Gi |
| remark42 / `^remark42-[a-z0-9]+$` / remark42 | 50m | none | 64Mi | 512Mi | 64Mi / 1Gi |
| socrat-home / `^socrat\-home-[a-z0-9]+$` / nginx | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| storage / `^nfs\-subdir\-external\-provisioner-[a-z0-9]+$` / nfs-subdir-external-provisioner | 10m | none | 64Mi | 512Mi | 64Mi / 1Gi |
| traefik-edge / `^traefik\-edge-[a-z0-9]+$` / traefik | 50m | none | 128Mi | 192Mi | 64Mi / 1Gi |
| umami / `^umami-[a-z0-9]+$` / umami | 10m | none | 384Mi | 768Mi | 64Mi / 1Gi |
| umami / `^umami\-db-[a-z0-9]+$` / postgres | 10m | none | 256Mi | 1024Mi | 64Mi / 1Gi |
| uptime-kuma / `^uptime\-kuma-[a-z0-9]+$` / uptime-kuma | 50m | none | 256Mi | 512Mi | 64Mi / 1Gi |
| wiki / `^wiki\-runtime\-wiki-[a-z0-9]+$` / wiki | 100m | none | 192Mi | 1024Mi | 64Mi / 1Gi |
| x-ui / `^x\-ui-[a-z0-9]+$` / primary | 100m | none | 448Mi | 768Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^alertmanager\-kube\-prometheus\-stack\-alertmanager$` / alertmanager | 25m | none | 64Mi | 128Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^alertmanager\-kube\-prometheus\-stack\-alertmanager$` / config-reloader | 25m | none | 48Mi | 128Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^alertmanager\-kube\-prometheus\-stack\-alertmanager$` / init-config-reloader | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^prometheus\-kube\-prometheus\-stack\-prometheus$` / prometheus | 200m | none | 2048Mi | 3072Mi | 64Mi / 1Gi |
| cattle-monitoring-system / `^prometheus\-kube\-prometheus\-stack\-prometheus$` / config-reloader | 25m | none | 48Mi | 128Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^prometheus\-kube\-prometheus\-stack\-prometheus$` / init-config-reloader | 10m | none | 32Mi | 128Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^kube\-prometheus\-stack\-prometheus\-node\-exporter$` / node-exporter | 25m | none | 48Mi | 96Mi | 16Mi / 256Mi |
| cattle-monitoring-system / `^monitoring\-etcd\-metrics$` / proxy | 25m | none | 16Mi | 64Mi | 16Mi / 256Mi |
| kube-system / `^nvidia\-device\-plugin$` / nvidia-device-plugin | 50m | none | 64Mi | 256Mi | 64Mi / 1Gi |
| kube-system / `^svclb-traefik-[a-z0-9]+$` / lb-tcp-80 | 10m | none | 8Mi | 512Mi | 16Mi / 256Mi |
| kube-system / `^svclb-traefik-[a-z0-9]+$` / lb-tcp-443 | 10m | none | 8Mi | 512Mi | 16Mi / 256Mi |
| syncthing / `^syncthing$` / syncthing | 50m | none | 128Mi | 512Mi | 64Mi / 1Gi |
| syncthing / `^syncthing$` / private-gui | 10m | none | 16Mi | 512Mi | 16Mi / 256Mi |
