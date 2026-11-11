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

Owner thickness refinement: groupWidth/barWidth increased0.2→0.4, approximately
 doubling visible thickness. Panel remains x12,y8,w6,h1; no layout/query changes.

## Superseding owner layout capture — 11 November 2026

Owner manually rearranged live Traffic Light; captured separately before changes.
Current layout24×20: resourcesh10 atx8/13/18, right node columnx23, Argo strip
x0,y19,w12,h1. UP908 stays removed per owner. New node927 (socrat-5) is cloned from
node4926, in free x23,y7; IP tiles and all other owner panels stay put.98 empty cells.
Both width factors now1 for maximum native visible strip thickness, preserving
module bounds and raw current-state query. `build()` now updates thickness in the
existing canonical panel without rebuilding or resetting owner-edited geometry.
This supersedes earlier historical position/thickness/cell-count notes above.

Owner-layout refinement acceptance:32 tests passed and scoped Helm diff changes
only canonical ConfigMap. Live before/after comparison (normalizing empty API
defaults) confirms all existing owner panels/settings retained, except requested
909 width factors, plus new927. Node5 health query returns0 (OK), not stale fallback.
Inspected actual deployed TV URL at1920×1080 in isolated Viewer browser: right
column includes green5 and bottom Argo strip fills its existing module height;
current instant query HTTP200, Ready48. Physical television itself not inspected.

Latest owner-only recapture: node5 now immediately follows4 atx23,y5; VPS IP and
Home IP nowy6/y7. Panel907 width8→7, stillx16,y10,h4.102 intentionally empty cells.
Pulled live dashboard without additional design/query changes; updated geometry
fixture and assertions.32 tests passed. Supersedes earlier node5/IP positions and
empty-cell count. Existing strip and remaining owner edits retained.

TV/public thickness correction: width factors already1; fresh real public scene
at1920×1080 had strip canvas only27px withh1. Changed only909 gridPos.h1→2,
x0,y19,w12 unchanged.21-row fit,114 empty cells; other saved geometry untouched.
Preserved Fully settings, existing presentation assets, query/data and all owner
edits. Device ADB/Termux unavailable in current LAN; no physical-TV verification
or reload possible yet. New geometry needs page reload, not merely5s metric refresh.

## Current owner-approved direction: per-Application Bar gauge

Owner rejected continuous state-count strip and requested h1 battery-like blocks.
Captured live manual909.h1 first (e5c33ed). Native bargauge909 now x0,y19,w12,h1,
transparent, hidden values/names/legend, no unfilled area. One vertical equal-full
block per Application, sorted alphabetically via seriesToRows→sortBy(Metric)→
rowsToFields. One instant query, no history/count aggregation/averaging. Latest
priority classification retained; codes1..6 = original codes+1. Positive categorical
codes saturate display max1 equally; NOT readiness percentages or utilization.
Value mappings encode all6 state colors. Up/fresh90s/inventory completeness guards
still yield no data on absent/down/partial stale telemetry; no fabricated blocks.

Native Gradient display with fixed color mode + value mappings gives SOLID fills,
not a multistate gradient; avoids Basic mode's inherent2px outline and translucent
fill. Retro LCD subdivisions are NOT applications, so not used. Minimum size0,
name/value hidden: no reserved text area. Native Bar gauge has built-in outer
padding and10px inter-bar spacing without a supported override; no fake padding
option, plugins, CSS or Fully injection added. Header/title/legend absent.

Isolated browser-only48-app mixed-status fixture verified exact colors and stable
alphabetical order (reversed input frames), no production data/workload mutations.
Live bounded query independently returned48 unique app names, all code5=Ready.
32 tests pass, including extended promtool positive per-app code/gap/overlap tests.
Physical-TV access remains blocked as documented; actual public route checked
separately after deployment. Reload Fully page to pick up new visualization.

Deployed acceptance2e1c05ce: actual anonymous public scene (no interception),
1920×1080 and55%-viewport emulation both returned48 unique app frames and rendered
exactly48 blocks. Visible panel text empty; borders0px. Native blocks9.64×27.91px;
emulated26×72.09CSSpx. Live snapshot47 green Ready +1 grey Unknown (not synthetic).
Actual public screenshot inspected. Live normalized before/after confirms only909
changed and all other owner panels/settings retained. Argo Synced/Healthy.
Physical device/reload still not verified; mixed6-color renderer fixture was a
separate browser-only test, never production metric/app mutation.

## Inventory/fit/hover correction, latest request

Bounded live K8s inventory49 Applications. Actual public909 query returned48
unique names; set difference was exactlyroot, with no other missing/extra apps.
Official MCP Prometheus query was temporarily blocked by its Grafana-service DNS
lookup, so comparison used actual successful public panel-query frames instead.
Current per-app query now includesroot so total matches Argo (49 at this snapshot).
Historical `queries()` count tests retain default exclude-root semantics; current
`application_query()` explicitly usesinclude_root=True with completeness/freshness
across ALL Applications. Tests verifyroot is classified, not just added as zero.

Native Auto sizing ignores customminVizWidth0, uses default8. With48 bars, a narrow
signed-in panel showed last targets outside its right edge; DOM count alone was
insufficient acceptance. Sizing nowmanual,minVizWidth0,minVizHeight0. Browser tests
must verify every colored block AND link target is fully inside its panel, not
merely count DOM nodes. Native10px gaps remain. No CSS/JS/plugin changes.

Owner-requested height2 atx0,y19,w12;21-row fit and114 empty cells. One native data
link per field: title${__field.name}, URL Argo/applications/argocd/${__field.name},
targetBlank. Standard browser title on hover, not a custom Grafana tooltip; click
opens the matching app. No permanent text. Authenticated normal + kiosk preview
verified49 named links sorted identically to49 real query frames, native title
attributes resolved and first/middle/last target hover succeeds. TV public mode
remains intentionally noninteractive; user hover works on ordinary signed-in route.

Post-deployeb7cd6a3 acceptance: actual public query and signed-in normal/kiosk
routes return49 unique app frames, names exactly equal live K8s Application names.
All49 native link titles resolved; hovered EACH of49 targets successfully in normal
and kiosk at1920×1080 AND1440×900. All targets fully inside panel (no clipping).
Normal narrow viewport requires scrolling panel into view before lazy queries run;
not a missing-data failure. Public actual scene and55%-viewport emulation render49
colored blocks, each completely inside panel, no visible text/borders. Native public
block height76.66px at1920×1080. No query interception/fixtures in live acceptance.
Live dashboard comparison ignoring empty defaults/version confirms only909 changed;
32 tests pass, scoped Helm only canonical CM, Argo Synced/Healthy.

Device status changed during this run: documented192.168.0.19:5555 now responds but
ADB saysunauthorized (SSH useralchemmist). Model cannot be verified until authorized.
No authorization bypass, key reset, Fully reload or physical screenshot performed.
