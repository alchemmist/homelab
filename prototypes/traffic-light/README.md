# Traffic Light · TMP Lab — all-app mosaic

Owner-directed fourth proposal, 2026-11-10. Replaces the rejected top8 timeline
with a native **Canvas mosaic covering every Git-managed Argo Application**.

Open with normal Grafana authentication:
<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## Layout and meaning

One Canvas panel973 at x12,y8,w6,h8. Seven columns, currently seven rows for49
applications, alphabetical. All original panels except old Argo909 remain
verbatim. No donut, numeric summary, top-k, list scrolling, LiteLLM or new service
tiles. Canvas is native in installed Grafana13.2.4, not a third-party plugin.
No custom CSS/JS or public share is introduced.

Each cell has an unambiguous short name, a field-bound background and a direct
link to that exact app in Argo CD. The field binding uses the full application
name. Native hover exposes the full name; the legend explains the current state color. The
small legend is embedded at the top of Canvas. Inline editing and pan/zoom are
disabled; scale constraints and zoom-to-content fit the whole mosaic.

| Color | Meaning |
|---|---|
| Dark slate | Quiet, no higher-priority state or recent sync |
| Cyan | Successful sync counter increment in preceding10m |
| Amber | OutOfSync |
| Violet | Progressing or Suspended (paused, not necessarily deploying) |
| Bright red | Failed/Error sync increment in preceding10m |
| Dark red | Degraded or Missing |
| Grey | Unknown state or missing/stale field data |

Current state only, not history. Priority is Unknown > Unhealthy > failed sync >
Progressing/Suspended > drift > recent successful sync > quiet. Higher-priority
states can hide concurrent activity. The10m sync pulse deliberately remains after
completion so brief changes are visible; it is not operation duration. Multiple
syncs can merge into that pulse. Sync is **not** proof of a Pod redeploy. No fake
errors, production redeploys or random animation are used to make it colorful.

Quiet cells are subdued, not bright green. A completely quiet mosaic is expected
when no app changed recently. Missing/stale app data or failed Argo scrape makes
the expected cell grey via the native missing-field color fallback, not quiet.

## Inventory and growth

The generator enumerates Application metadata in `deploy/argocd/apps/*.yaml` and
`deploy/argocd/root.yaml`; live audit confirmed the resulting49 names exactly
match all49 names returned by argocd_app_info. No applications are truncated.
Aliases are only for cell text; links and field identity always use full names.

When an Application is added/removed, regenerate this JSON. The generated-copy
unit test detects a stale mosaic versus Git inventory. More applications create
additional rows, not an arbitrary cap; however a fixed TV area has finite legible
capacity. Font/cell readability must be reviewed as density grows. Out-of-Git
runtime-only apps require explicit inventory reconciliation; Canvas does not
create elements dynamically merely because another Prometheus series appears.

## Validation

30 dashboard tests, including promtool tests for all state priorities, inclusion
of quiet apps, pulse expiry and missing/stale/down scrapes. All49 names matched
live and the instant query returned49 values. Native source schema/rectangle
config reviewed against Grafana13.2.4. Full Helm render must change only the
existing TMP ConfigMap payload; canonical JSON/public share/TV remain unchanged.
Rendered-browser checks completed at1920×1080 and1440×900 using a separate
headless Chrome context with the existing Viewer bearer restricted to the Grafana
origin; no shared browser profile was touched. Inspected screenshots: all49 cells
fit without scrolling; shortened overflowing aliases at1440; verified full-name
hover for monitoring-k3s. Native tooltip repeats the fixed short cell text rather
than a textual mapped state; use the visible legend/color and Argo link for state
details. Physical-TV readability remains the owner's acceptance step.

Initial deployment failed on Kubernetes'262144-byte annotation limit. Only the TMP
ConfigMap template now minifies its embedded JSON, keeping last-applied metadata
below the limit; a Helm size regression test covers it. Initial Canvas Scale
placement incorrectly used pixels; source review and browser inspection corrected
it to native percentage edge offsets, now also tested. No failed deployment or
uninspected browser result is claimed as successful.

## Rebuild / ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`, ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`, Sandbox folder. Git → monitoring-k3s
Argo auto-sync only. No exporters, alerts, network policies or shared TV assets
changed. Retiring the lab requires Git removal and exact reviewed ConfigMap
cleanup because automatic prune is false.

Reference: [native Canvas](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/canvas/).
Previous rejected panels950–972 remain only in Git history, not current TMP.
