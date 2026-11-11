# Traffic Light — current Argo state strip (supersedes historical landscapes)

Owner rejected the historical stacked graph, including Symlog refinement, and
requested one thin real-time module with no title, legend, axes or history.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true>

## Current panel909

Native horizontal Bar chart, one stacked bar, x12,y8,w6,h1 (formerly h6).
All other panels stay put; the30 freed grid cells remain empty for owner plans.
Title/legend/axes/value labels hidden; no borders, full opacity. Fixed state colors.
Instant Prometheus **table** query, not range; newest observed argocd_app_info
labels per Application, excluding root, grouped once per app. A constant row label
plus native groupingToMatrix/organize transforms yields ONE row with six numeric
state columns. Percent stacking fills the module width; segment widths are shares
of the current observed inventory, not a timeline. Source values remain app counts.

- Ready (green): Healthy+Synced.
- Progressing (blue): health Progressing, not yet ready; not proof of Pod rollout.
- Suspended (amber): paused, deliberately distinct from active Progressing.
- Git drift (amber): OutOfSync unless a higher-priority state applies.
- Unhealthy (red): Degraded/Missing.
- Unknown (grey): unknown/unrecognized health or sync state.

Priority: Unhealthy > Unknown > Progressing > Suspended > drift > Ready. Unknown
sync prevents a healthy green state. Latest timestamp wins over older label sets;
contradictory same-time states still contribute once. No counter, increase, rate,
rolling window, last12h state history, top-k, Symlog, smoothing or synthetic sync.
Argo app health status has no separate generic Pending state; progressing/unknown
are rendered from actual exported status, never inferred from cumulative counters.

The dashboard refreshes5s. Raw Argo cadence was measured15s; refresh does not create
new samples faster than collection.90s freshness limit is a stale-data guard,
not averaging. Failed/down/absent/partially stale telemetry gives no data, not a
fully green bar. Fresh zero categories remain zero-width and do not draw outlines.
Inventory silently lost beyond Prometheus lookback cannot be distinguished from
actual deletion without a separate inventory source. Counts are Applications,
not Pods, deploys or full service availability. Hover gives state/count details.

## Build / validation / isolation

```sh
python3 scripts/build-traffic-light-argo.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
python3 -m unittest discover -s tests -p 'test_overview_capacity.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

32 tests cover instant/non-range native rendering configuration, no title/legend/
axes, single-row matrix shaping, six colors, current-state classification and
fresh zero/missing/down/partially stale telemetry plus lingering old status labels.
Suspended now has its own category. Fixture909 height1 leaves52 intentional empty
cells in24×16 grid. All other panel content/geometry and dashboard metadata remain
unchanged. Overview capacity gauges and Traffic Light CPU/Memory/Disk bars are
untouched. Helm diff changes only canonical ConfigMap payload. Live owner/source
comparison before edits found only API defaults/schema normalization, no uncaptured
manual edits. Existing canonical UID, public share and Fully/TV configuration stay.

TMP UID/ConfigMap and previews were retired earlier with exact UID/resourceVersion
cleanup; they are not recreated. Prior timeline/line/mosaic/landscape/Symlog
experiments remain in Git history only. No plugins, custom CSS/JS, collector
configuration, sync/prune, rollout or global dashboard-setting changes.

Native rendering refinement: percent scale is explicitly bounded0..1 so all-green
fills100% of the width (auto-ranging with integer decimals otherwise leaves half
empty). Both groupWidth/barWidth0.2 make the strip genuinely thin. Native transparent
panel option enabled. These are display bounds on normalized stacking; hover still
shows original counts, e.g. Ready48, not48% or a clipped value1. Mixed-color rendering
was checked only in an isolated browser response fixture, never by changing Argo
apps or production telemetry. Live data is checked separately without that fixture.

Acceptance: inspected the final deployed bar at1920×1080 in an isolated Viewer
browser on real data (HTTP200): Ready48, other categories0; full-width green thin
strip, hover retains count48. No history or visible legend/axis/title. Compared
live dashboard before/after: only909 differs; all nonversion settings and other
panels match.32 tests passed, Argo Synced/Healthy. Physical-TV acceptance remains
owner-side. Local synthetic mixed-state rendering was separate from this live check.
