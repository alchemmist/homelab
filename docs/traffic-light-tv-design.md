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
