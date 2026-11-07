# Monitoring: service-owned Argo Applications

## Current source of truth

| Application | Owns | Git source |
| --- | --- | --- |
| prometheus-stack | Prometheus, Alertmanager, operator, exporters, base rules/monitors | `deploy/platform/prometheus-stack/values.yaml`; kube-prometheus-stack chart 92.10.0 |
| grafana | Grafana, PVC, provisioning, RBAC, public ingress/policy proxy | `charts/grafana`, `deploy/platform/grafana/public-entry` |
| loki | Loki runtime/config, Service, retention rules | `charts/loki` |
| tempo | Tempo runtime/config and Service | `charts/tempo` |
| pyroscope | Pyroscope, persistent storage, CPU datasource/dashboard | `charts/pyroscope` |
| grafana-mcp | Read-only bearer MCP service | `charts/grafana-mcp` |
| thanos | Metrics storage/query cascade | `charts/thanos` |
| monitoring-k3s / monitoring-llm | Shared cluster/domain instrumentation, dashboards and access; shared backend leaf Certificate | Their existing charts |

The boundary is a separately deployable service, not an arbitrary YAML resource.
Prometheus Operator/exporters/Alertmanager remain a supported Prometheus stack;
Grafana is no longer bundled inside it. Shared PKI, instrumentation and application
owned dashboards/rules are not duplicated into every service. Existing host/cluster
Collectors and Prometheus's coupled OTEL sidecar are not reinstalled by this split.

Grafana chart 14.0.0 is vendored **unchanged** from the previously installed pinned
kube-prometheus-stack 92.10.0 dependency, under `charts/grafana/charts/grafana`.
The wrapper retains effective parent defaults and provisioning. Grafana image,
PVC, admin Secret and native OIDC Secret references are unchanged. Effective live
OIDC/session settings were adopted explicitly into values; anonymous access is
false in both ini and env. No password, client secret or DB contents are in Git.

## Names are compatibility, not Application ownership

Helm releaseName `kube-prometheus-stack` is retained for both the Prometheus stack
and standalone Grafana rendering. Argo is the deployer, not two imperative Helm
releases. The two Applications render disjoint resource sets. Existing selectors,
Service URLs, release labels and PVC names must not be changed just to match the
new Application names. In particular `kube-prometheus-stack-grafana` remains the
Grafana Service/Deployment/PVC. Pyroscope retains releaseName `profiling`; Loki
and Tempo retain `otel-loki` / `otel-tempo` and legacy part-of labels.

**Never `helm uninstall` the historical releases.** They describe resources now
owned by several Applications. Roll back only the current owning Application's
Git source. Historical Helm records and local data are retained for recovery.
Legacy `monitoring.yml` checks the independent owners before **any** role, and
`monitoring_stack` has the same guard for direct role callers. It refuses legacy
mutations after the split. Node/resource/PKI prerequisites are not permission to
upgrade the old combined Helm release.

## Non-destructive handoff, 2026-11-07

1. Disable old `kube-prometheus-stack`, `otel-backends`, `profiling` auto-sync and
   remove their deletion finalizers through Git; confirm live disarm.
2. Record 104 pre-migration object UIDs and a golden render contract. All 77
   Prometheus resources/CRDs render identically with Grafana disabled and the
   historical releaseName retained. Create a private consistent Grafana SQLite
   backup using the SQLite backup API and verify `quick_check`, never copying an
   active DB/WAL blindly. Temporary backup Pods use the existing sidecar image,
   a read-only PVC mount and no service-account token, and are removed afterward.
3. Add service owners. Grafana/Pyroscope/Prometheus adopt existing resources.
   Stage Loki and Tempo with automatic sync paused, then sync their own resources
   one at a time. Each gets a separate ConfigMap with byte-identical config;
   only its deployment's config reference changes. Preserve host paths, security,
   retention, images and client/server TLS. The existing shared Certificate is
   transferred to `monitoring-k3s`, without changing spec or issuing new SANs.
4. Verify 103 retained object UIDs, PVC/Secret/Certificate UIDs and service health.
   Of those, 93 carry application tracking; the 10 chart CRDs remain unannotated
   shared cluster definitions, present and Synced in the new Prometheus scope.
   Do not force per-application tracking/finalizers onto shared CRDs.
5. Remove old Application manifests and aggregate charts/values/public extension
   path, and restore Loki/Tempo normal auto-sync. Root prunes only finalizer-free
   Application objects. Retire only the unused old `otel-backends` ConfigMap after
   checking workloads no longer reference it, with exact UID/resourceVersion
   deletion preconditions. No global prune, data deletion or Helm uninstall.

`tests/fixtures/monitoring-split-contract.json` records the original payload hashes.
Tests allow only reviewed Grafana native-auth adoption and the two backend config
references; the rest of the retained local runtime payload remains identical.
Future intentional runtime changes must update that reviewed migration contract.
Public policy/auth rules were not changed by the split. Concurrent independent TV
layout work (`832e341`, `757dc18`) updated the shared presentation asset while this
handoff was in progress; its changes are preserved, not overwritten by the initial
snapshot. The original and newly reviewed policy ConfigMap hashes are recorded in
the fixture. Only that reviewed TV asset update is re-baselined.

## Acceptance and limits

- 100 focused ownership, public access/TV, profiling, retention, relocation and
  dashboard tests pass (24 pytest subtests also pass);
  Helm lint succeeds for the four local service charts and existing shared chart.
- Public TLS/anonymous/forged-header/invalid-token regression: 134/134 before and
  after the service handoff. Native TV sharing/presentation checks: 24/24 at both
  public IPs using the existing share, without republishing. Both repeated successfully after retirement;
  neither check is new browser enrollment or independent-provider acceptance.
- Grafana DB reports ok; native OIDC redirects to Authentik. Before/after consistent
  private SQLite snapshots preserve users, organizations/memberships, datasource
  identities, dashboard UIDs, OAuth identity links and public-dashboard sharing.
  Dashboard provisioning may legitimately update dashboard content/revisions.
- Prometheus/Alertmanager readiness verified. Loki/Tempo verified-CA mTLS `/ready`
  returns 200 and requests without a client certificate fail. Native ingester
  readiness has a 15s delay after its first readiness check; TCP Pod readiness
  alone is not the functional acceptance gate. Recent Loki logs and stored Tempo
  traces are queryable without printing log bodies or trace payloads.
- Grafana/Loki/Tempo each have one planned rollout. Other components are not
  deliberately restarted. No versions, retention durations, data locations or
  access rights were upgraded as a side effect of the ownership migration.
- This does **not** claim a full browser MFA/role matrix, fresh traces from every
  producer, a new profiling ingestion test, off-node backups, HA or DR validation.
  The private DB snapshots are a migration safeguard, not a cluster backup design.


## Final retirement readback and separate incidents

Old Applications are absent. The unused shared ConfigMap was deleted only after
all Pod/Deployment/StatefulSet/DaemonSet/Job/CronJob references were absent, with
UID/resourceVersion preconditions and a private rollback snapshot. All 103 retained
resource UIDs and all previously sampled PVC/Secret/Certificate UIDs are unchanged.
Before/after consistent SQLite snapshots are retained privately (0600) under
`~/.config/homelab/grafana/migrations/2026-11-07-monitoring-split/`, not Git.
Grafana/Loki/Tempo were rolled out; other old completed Job Pods expired normally,
and an independently changed Thanos compactor/TV proxy is not attributed to this
split. Concurrent dashboard/TV commits were preserved during rebase.

Do **not** turn the migration acceptance into a claim of cluster-wide health:

- Prometheus logs contain a WAL segment `00001786` checksum error at 09:00 UTC,
  before the 10:20 UTC disarm commit. The existing Prometheus Pod was not restarted.
  `PrometheusTSDBCompactionsFailing` remains visible; no alert mute, WAL truncation,
  block deletion, data reset or unapproved database repair was performed.
- The separate concurrent blog release `8b3e079` points at an unavailable Harbor
  digest: new Pod ImagePullBackOff, two old Pods still serving. No unrelated release
  rollback or image substitution was performed as part of monitoring ownership.
- Root's separate Rancher drift was traced to two already-live Argo PostDelete
  lifecycle finalizers absent from Git. They are now declared explicitly, preserving
  hooks and actual metadata rather than adding diff ignores or changing Rancher.

Investigate the WAL with a safe backup/repair procedure and the missing blog
artifact as separate incidents; neither is permission to prune state or rerun the
retired combined monitoring installer.
