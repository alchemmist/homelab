# Prometheus, Alertmanager, operator and exporters: separate Applications

## Current ownership

There is no `prometheus-stack` Application or shared mutable aggregate values file.

| Application | Git source | Existing resources |
| --- | --- | ---: |
| prometheus | `charts/prometheus` | 38: Prometheus CR, its supporting resources, common recording/alert rules and cluster monitors |
| alertmanager | `charts/alertmanager` | 6: Alertmanager CR, routing/config Secret, SA/Service/monitor and its own rules |
| prometheus-operator | `charts/prometheus-operator` | 20: operator, webhook/RBAC/monitor resources, own/reloader rules and 10 shared CRDs |
| node-exporter | `charts/node-exporter` | 6: node DaemonSet, SA/Service/monitor and its own rules |
| kube-state-metrics | `charts/kube-state-metrics` | 7: exporter Deployment, RBAC/SA/Service/monitor and its own rules |

Operator-generated StatefulSets/Pods/PVCs follow their Prometheus/Alertmanager CR
owner references. The operator manages their lifecycle but does not own their
application configuration. This is analogous to CNPG operator vs an application's
PostgreSQL Cluster. Supporting resources are not turned into new Applications.

Grafana, Loki, Tempo, Pyroscope, Grafana MCP and Thanos keep their independent
Applications. Cluster/domain instrumentation remains in its existing sources.

## Shared source is not shared deployment

Every component has its own chart/values and Argo Application (`project: default`,
`prune: false`, `selfHeal: true`). All five link the **unmodified**, versioned
upstream archive `charts/_vendor/kube-prometheus-stack-92.10.0.tgz`, verified by
SHA256. This reuses pinned templates, not an aggregate deployment. Rendering is
offline; no repository/OCI dependency download is needed by Argo. Symlinks stay
inside the Git repository, as with the existing local database dependency pattern.

Each wrapper enables only its own runtime and owned rule groups. Each can pin a
separately reviewed bundle/version rather than replacing a shared archive in place.
No common mutable values file couples component deployments. The whole chart's
original output is partitioned into five disjoint sets, not rendered five times
with all components enabled.

Historical Helm releaseName `kube-prometheus-stack`, resource names, selectors,
release labels, Service endpoints and PVC names are intentionally retained.
Argo renders manifests; it does not create five imperative Helm releases with
that name. Do not `helm uninstall` or upgrade the historical release.

The Prometheus wrapper has an explicit `alertingEndpoints` entry matching the
former automatically generated Alertmanager endpoint, byte-for-byte in rendered
spec. Disabling Alertmanager rendering inside that wrapper therefore does not
remove alert delivery. kubelet Service management stays enabled in the operator;
cluster monitor definitions are emitted only by Prometheus. CRDs are emitted only
by the operator; their existing unannotated/shared tracking behavior is preserved.

## Non-destructive handoff — 2026-11-07

1. Record live UID/owner metadata for all 77 resources, 8 regular runtime Pods,
   4 PVC/bound volumes and UID/content hashes of the 3 affected Secrets (including
   operator webhook TLS). Secret contents are never printed or stored in Git.
2. Disable old `prometheus-stack` automatic sync/self-heal and remove its deletion
   finalizer in Git; confirm no active operation or live finalizers remain.
3. Add the five new Applications. Verify their union is **exactly the original
   77 resource payloads**, with no missing/extra/duplicate identities. This includes
   all rule expressions, pod templates, images, RBAC, storage/retention settings,
   Alertmanager routing and webhook configuration. No runtime upgrade or migration.
4. Confirm new ownership of 67 tracked objects and unchanged UID/declared new scope
   of the 10 shared CRDs. Check all five Applications are Synced/Healthy and have
   normal automatic sync enabled. Verify readiness and the active Alertmanager
   discovery endpoint, not just Git state.
5. Delete only the now-finalizer-free aggregate Application and its obsolete values
   directory from Git. Root prunes that Application, **not** the transferred data
   or workloads. No global prune, Helm uninstall, PVC deletion or database repair.

Baseline render hashes and owners: `tests/fixtures/prometheus-service-handoff.json`.
The first monitoring handoff fixture is updated to current service owners without
changing those 77 original payload hashes. Intentional future runtime changes must
update the reviewed contract, not work around it by disabling tests.

The legacy combined monitoring Ansible installer is retired with an unconditional
always-tag failure before any mutation, even on a fresh cluster. Existing helper
files/rollback records remain; restore credentials or machine prerequisites under
separate reviewed procedures, not by reviving the old umbrella installation.
Thanos's node-placement lookup reads the current standalone Prometheus values.

## Acceptance and limits

- All 77 existing resource UIDs preserved. Rendered payload equality is exact.
- All 8 existing component Pods retain UID, node, readiness and restart counters:
  **no regular component rollout or restart was required**.
- All 4 existing PVCs retain UID and bound volume. The 3 target Secrets retain
  both UID and content, including the existing operator webhook TLS keypair.
- Prometheus and Alertmanager readiness succeed; Prometheus still discovers one
  active Alertmanager endpoint. No synthetic production alert notification was sent.
- All five new owners are Synced/Healthy, with `prune=false/selfHeal=true`.
- 104 focused tests and 24 pytest subtests pass; all five component Helm lints
  and the legacy playbook syntax check pass.
- Source archive checksum, offline links, disjoint ownership, one-runtime-per-app,
  selector/endpoint preservation and retired-installer safety are regression-tested.

The prior Prometheus WAL checksum incident is not repaired or silenced by this
ownership change. No WAL/blocks were deleted or truncated, no data reset, retention
change, source-scraper change, duplicate scrape path or new HA/DR acceptance is
implied. This does not rerun browser MFA/onboarding or every-producer telemetry
validation; those systems' configurations were not changed by the handoff.


## Retirement closeout

The aggregate was removed at `bcc93ca` after disarm `652e286` and adoption
`78a9336`. Final readback: aggregate absent; all five component owners and root
Synced/Healthy; all 49 Applications Synced/Healthy at this snapshot. The repeated
UID/Pod/PVC/Secret-content audit still passes. Public-access regression is 134/134.
Argo health does not establish database integrity: the pre-existing
`PrometheusTSDBCompactionsFailing` alert remains visible, alongside the expected
Watchdog heartbeat. No alert masking or WAL repair was performed.

Private pre-handoff metadata/render/hash receipts are retained 0600 under
`~/.config/homelab/monitoring/migrations/2026-11-07-prometheus-components/`.
An ownership rollback requires another disarm/finalizer-free handoff. Do not
blindly revert commits that delete the five new Applications with active resource
finalizers: that can cascade into their workloads. Roll back ordinary runtime
settings only through their current owning chart, preserving persistent data.
