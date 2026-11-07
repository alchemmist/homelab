# Traffic-light TV design

## November 2026 revision

Source of truth: `charts/monitoring-k3s/dashboards/traffic-light.json`.
Start from the live Grafana dashboard, not an older provisioned layout. The latest
manual VPN visualization is a **Stat**, not a time series; retain it. Its bottom
edge (`y + h = 18`) is the hard boundary. The dashboard retains its existing time
window and 5-second refresh. Fully settings and remote-control bindings are unchanged.

### Design decisions

- Apply USE to the existing host resource column and RED to HTTP observability.
  Keep the RPS history; replace the redundant node CPU history with home HTTP p95.
- CPU values are busy logical cores, including iowait, not GHz or Kubernetes
  requests. Memory is total minus available. Root filesystem usage is size minus
  free; reserved but free blocks are not counted as occupied.
- Every resource bar displays an absolute value (cores or IEC bytes), with its
  own node's live capacity as `max`. Percentage thresholds remain 75/90, evaluated
  against that dynamic maximum. Do not use a single maximum across unlike hosts.
- Two instant table queries are joined on **nodename**, never Time. Rows-to-fields
  maps Used to field.value and Capacity to max. Missing usage/capacity rows are
  filtered out, not converted to healthy zeroes. Node tiles retain explicit
  unknown/health semantics.
- HTTP p95 aggregates histogram buckets before histogram_quantile. Only the home
  Traefik currently exposes these duration buckets. Label this scope explicitly;
  do not call it VPN or whole-edge latency. No requests yields a gap/NaN, not 0.
- The 19×3 strip below RPS and Disk shows at most three firing alert names,
  critical before warning. Alert instances are grouped by name and severity;
  the existing count tiles retain the full instance counts. Do not label the
  rank value as a count or duration. No-alert sentinel requires a healthy,
  recent Prometheus scrape. The table hides the synthetic numeric rank.
- The incident list is deliberately bounded. Its compact height, long-name
  readability and per-field scaling still require a rendered TV check.
- No custom plugins, external scripts, animation, dashboard rotation, Fullly
  Plus injection or additional free-disk tile.

### Research

Official Grafana references reviewed:

- [Dashboard best practices](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/):
  USE/RED, low cognitive load, symptom-first presentation, normalized comparisons,
  hierarchy and version-controlled dashboards rather than decorative density.
- [Bar gauge](https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/bar-gauge/):
  absolute units, per-field configuration, unfilled region and percentage thresholds.
- [Transformations](https://grafana.com/docs/grafana/latest/panels-visualizations/query-transform-data/transform-data/):
  join by stable identity and rows-to-fields for dynamic configuration.
- Grafana **v13.2.4** source: `public/app/features/transformers/rowsToFields/rowsToFields.ts`
  and `fieldToConfigMapping/fieldToConfigMapping.ts`: verified that `max` is a
  supported rows-to-fields handler, rather than assuming automatic per-node scaling.

State timelines would be useful for service flapping but add another historical
layer and require TV readability validation. Heatmaps need more vertical space;
Canvas/custom plugins would add maintenance without fixing a missing signal.
Neither is included merely for visual novelty.

### Validation and rollout

Run `python3 -m unittest discover -s tests -p test_traffic_light.py`.
Tests cover the complete 24×18 tiling without overlaps or holes, absolute units,
dynamic maxima, relative thresholds, latency query and bounded incident list.
New queries were evaluated against live Prometheus: all four node usage/capacity
pairs returned data, p95 returned a duration, and the alert list returned the
currently firing warning.

ConfigMap is owned by **Argo CD** (`monitoring-k3s`). A direct ConfigMap patch was
observed to be reverted by reconciliation; it is not a lasting deployment path.
Ship via GitOps; do not disable self-heal.

## Rollout verification, 7 November 2026

Released as `208e2ea` through main. Work was isolated in a separate worktree based
on the current remote main, without including unrelated dirty files from the
operator's checkout. Argo CD subsequently reported Synced / Healthy.

A separate Chromium browser was used because the shared Playwright MCP profile
was occupied. Authenticated as the existing TV Viewer using the cluster secret;
credentials were not printed or committed. The public dashboard URL was opened
at 1920×1080 and its rendered screenshot inspected. Confirmed:

- CPU values in cores and RAM/root disk in GiB;
- capacity-relative bar lengths, including the orange high-memory node;
- HTTP p95 history replacing CPU history;
- the bounded incident table showing the live PrometheusTSDBCompactionsFailing warning;
- the existing VPN Stat and sparkline retained;
- all visible panels fit within the browser viewport.

This verifies the actual served public dashboard, not a mocked API response.
The physical TV / Fully scale still needs operator confirmation. In particular,
Grafana autofit and the gateway inset affect final panel heights; the JSON grid
boundary is tested, but exact pixel alignment on the physical TV is not claimed.

## Activity experiment: n8n and Argo CD

The user approved the CPU/Memory/Disk panels. Git tag
`tv-resources-approved-20261107` points to the released baseline (`208e2ea`).
The activity experiment must leave panel IDs 21, 22 and 23 byte-for-byte equivalent
as JSON objects. It replaces only the latency and incident blocks.

- Argo CD native controller metrics: ready count requires both Synced and Healthy;
  Git drift is separate. One vertical segment per app: green ready, blue progressing,
  amber drift, red degraded/missing/unknown. This is current delivery state, not a
  fabricated deployment history. Tooltip identifies each application.
- n8n has an in-flight execution, so it is **not restarted or reconfigured**.
  A separate non-root observer polls GET `/api/v1/executions?includeData=false`
  every 30 seconds using an existing API key mounted from the out-of-Git Secret
  `socrat-n8n-observer`. The observer only makes read requests; the existing key
  itself is not represented as a newly scoped read-only credential.
- No workflow payloads, execution IDs, names or API secrets are exposed as metric
  labels or printed. Metadata stays transient in process memory. No public route
  is created for the observer. A pinned native OTel sidecar scrapes it over loopback
  and Argo CD over a ClusterIP Service, then sends metrics using a dedicated
  cert-manager client certificate through the existing mTLS OTLP receiver. No
  main Collector, Prometheus or n8n restart is needed. Egress is restricted to
  n8n, Argo CD, the cluster OTLP receiver and DNS. Legacy ServiceMonitors do not
  activate scraping after the native-OTel cutover. n8n configuration and persistence are unchanged.
- Counts mean **starts in the last 5 minutes / hour by current outcome**, not
  completions or cumulative counters. The historical chart samples rolling
  windows at five-minute intervals; do not apply rate/increase. Older executions
  that resume and finish now are not counted as new starts.
- n8n's unfiltered API excludes running executions: fetch running separately;
  waiting executions are not running. Paginate and deduplicate IDs. A bounded
  scan that exceeds budget fails closed rather than publishing partial totals.
- Gauge history begins with observer deployment. No synthetic historical backfill.
  First hour can show real summary counts immediately from execution metadata.
  Export failures suppress counts and expose collection_success=0, not healthy zero.

### Activity preview verification

Published experiment `8355cae`, native-pipeline corrections `94bb894` / `fe41cd6`,
and aligned n8n readouts `3e5b64d` via GitOps. The approved resource snapshot is
also checked by a dedicated fixture in `test_traffic_light.py` (commit `7a320d0`).
24 dashboard tests + 4 observer tests pass; Helm lint passes.

Live checks: both new native scrape targets have up=1, the observer has
collection_success=1, and the two-container observer pod is Ready. Argo CD reports
Synced / Healthy. No n8n rollout or main telemetry pipeline restart was performed.
Initial use of legacy ServiceMonitors produced no data because that scrape owner
is retired; replaced by the isolated native OTel sidecar and removed those three
now-unused Service/ServiceMonitor objects created by this experiment.

The public dashboard was opened in an authenticated Viewer browser at 1920×1080
and its actual screenshot inspected. Confirmed absolute-resource bars unchanged,
Argo CD ready/drift counts and colored app segments, real n8n rolling-start bars,
and a single aligned three-value readout. At check time n8n showed 72 recent starts,
60 errors and 1 running execution; these are observed data, not demonstration values.
The chart shows rolling five-minute windows over the last hour, sampled at 30s;
neighboring bars overlap in time and must not be summed as disjoint bins. History
begins at deployment; the blank portion before it is intentional. Physical Fully
TV scale still requires operator review.
