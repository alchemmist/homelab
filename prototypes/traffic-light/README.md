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
name. Native hover uses that field to expose full name and mapped state. The
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

29 dashboard tests, including promtool tests for all state priorities, inclusion
of quiet apps, pulse expiry and missing/stale/down scrapes. All49 names matched
live and the instant query returned49 values. Native source schema/rectangle
config reviewed against Grafana13.2.4. Full Helm render must change only the
existing TMP ConfigMap payload; canonical JSON/public share/TV remain unchanged.
Browser visual inspection is a separate acceptance step, not proven by these
API/geometry tests. Physical-TV acceptance remains the owner's next check.

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
