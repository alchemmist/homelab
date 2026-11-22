# Unified logs: operator guide

## Access and boundaries

In Grafana open **Dashboards → Socrat / Unified logs** (`/d/socrat-unified-logs`). It uses the standard Loki datasource with UID `loki`, not Prometheus/Thanos. At the read-only check, the datasource is located in `cattle-monitoring-system`, reaches Loki over HTTPS with CA verification and a client TLS certificate; the keys stay in the existing Secret. The dashboard contains no passwords and does not change authorization. Log access is determined by Grafana permissions, not dashboard variables: the namespace filter is not a security boundary.

The dashboard ConfigMap is created by the chart `monitoring-k3s`, label `grafana_dashboard=1`. The existing sidecar reads all namespaces and uses `grafana_folder`. Do not edit provisioned JSON through the UI: changes must go through Git review. Other datasources, metrics, Thanos and application databases are not affected by this change.

## Search

1. Select the period at the top right (one hour by default), then Service, Namespace, Node and Severity. Multiple selection is supported. All for namespace/node/severity includes missing labels, so host logs without a namespace are visible without extra configuration. Service All requires a non-empty `service_name` (`.+`), as the safe Loki selector requires; records without a service_name must be searched separately in Explore by another non-empty label and their normalization fixed.
2. The graphs show the number of records per service over a dynamic interval and the number of error/fatal. The error panel also accounts for the selected Severity: when only info is selected it is predictably empty.
3. The log panel is limited to 1000 lines; shorten the interval or go via **Explore — same filters and time**. The link carries over the LogQL expression and the absolute boundaries of the current period. In Explore you can add a string search and view record details. Do not put user texts, trace IDs, pod UIDs or file names into indexed labels.
4. Severity: trace, debug, info, warn, error, fatal, unknown. unknown means an unclassified level, not info. Old records without severity are visible under All, but not when unknown is selected. Search the pod/container/systemd unit fields in the details (structured metadata), not in the list of index variables.

**No data does not mean health or zero errors.** First reset the filters and widen the period. Then check the datasource availability, the collector → Loki delivery and the retention window. The service list is built from logs that already arrived: a service missing from it is not proof that the service is absent. Compare coverage completeness with the Kubernetes inventory and host services. The dashboard does not replace an independent delivery check.

## Retention and disk capacity

The dashboard reads data and does not manage deletion. Retention changes must go through the managed Loki configuration and review: a base period plus exceptions by `service_name`/`severity`, rule priorities, the minimum supported window. Shortening the period is a potentially irreversible deletion, lengthening does not return deleted records. The period is counted not as a hard disk quota: compaction/delete delay and the current ingestion rate give headroom beyond the period.

Before rollout, record only aggregates: filesystem size and free space, the size of Loki chunks/index/WAL, bytes/day over a representative period, the growth rate, the compactor delay and the headroom before filling. Estimate: daily growth × retention period + WAL/index/compaction + reserve. Do not claim a measured limit without real measurements. Take the exact budget and thresholds from the agreed storage configuration; when space runs low, first limit the stream/period in an agreed way, do not delete directories by hand. Do not touch the Prometheus, Thanos directories or application databases.

## Safe rollout and verification

The current phase is local implementation only: no apply, sync or push. Before an approved rollout: run the offline tests and `helm template`, check the ConfigMap, then apply only the agreed GitOps change. After rollout, verify the dashboard load, the existing UID `loki`, the filters on a real service/node, each level and legacy missing labels, the Explore handoff (filters + time), an empty period and an unavailable datasource. Verify delivery via a safe synthetic marker; do not keep working-log bodies, tokens, certificates or screenshots of sensitive records in evidence.

UI rollback: return the dashboard/ConfigMap commit via the standard GitOps. This does not roll back an already-performed retention deletion. Do not restore Loki by deleting the PVC and do not change the existing datasource Secret on a UI rollback.
