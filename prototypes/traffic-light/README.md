# Traffic Light · TMP Lab — per-application sync lines

Owner-selected proposal,2026-11-10: replace the mosaic with an ordinary native
Time series chart, one colored line per Argo application, **root excluded**, no
legend. No other added blocks or changes to canonical TV.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## Meaning and presentation

Panel974 fills x12,y8,w6,h8. Y = estimated successful syncs in the **preceding15m**;
X = dashboard range (currently12h). Sampled every minute. Lines are unstacked,
no area fill or smoothing,2px width. Single-series hover shows the application
name/value and supports a link to that application in Argo CD. The legend is
hidden as requested. Colors are explicitly pinned by full name using a stable
hash-derived color, independent of other applications' presence/order.

This is a rolling count, not a lifetime total or non-overlapping15m buckets.
`increase` handles resets and extrapolates between scrapes, so counts can be
fractional; displayed zero decimals are presentation, not exact event accounting.
A successful sync does not necessarily redeploy Pods. Failed syncs, restarts and
rollouts are NOT plotted or inferred as successes.

All fresh app_info names except root are included. Two current applications had
no initialized successful-sync counter; they get zero while app telemetry and
the Argo scrape are fresh. Retired counter label sets are excluded. Missing/stale
app or scraper telemetry produces gaps, not a healthy zero. This cannot establish
counter completeness if a producer silently omits a previously emitted counter
while continuing to emit fresh app_info. No changes to exporters or ingestion.

Quiet applications coincide at zero; equal positive series can overlap too. This
is an inherent limitation of a many-line chart, not filtering or a top-k cap. Many
colors may be similar. Hover is the way to identify a line; color is identity,
not severity. New apps appear through the dynamic query; regenerate overrides to
pin their colors. Long dashboard ranges can downsample short peaks.

## Validation and acceptance

Live12h/1m query returned48 applications, none named root. Observed nonzero lines
included grafana, monitoring-k3s, socrat-bot, spi-triage and thanos. This is a
point-in-time observation. No production rollout was triggered to create data.
30 tests cover canonical panel preservation, native line/no legend settings,
per-name colors, grid, rendered ConfigMap size and promtool semantics for root/
retired exclusion, never-initialized/quiet apps, failed-only counters, stale/down
telemetry and expiry of the15m rolling window. Helm render changes only the TMP
ConfigMap payload. Inspected the deployed chart in an isolated read-only Viewer
browser at1920×1080: colored line peaks visible, legend absent, no rendering
error. Hovering a peak showed `monitoring-k3s`, timestamp and value4. Shared
browser profile was not touched. Physical-TV acceptance remains with the owner.

## Build / ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`, ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`, Sandbox folder. Existing TMP template
minifies embedded JSON to stay below Kubernetes last-applied annotation limits.
Git → monitoring-k3s Argo auto-sync. No custom JS/CSS/plugin, public sharing, TV
settings, alerts, datasource or network changes. Canonical panel909 remains on
canonical; TMP removes it and adds only974. Previous experiments950–973 are gone
from TMP, retained only in Git history. Retirement requires source removal and
exact reviewed ConfigMap cleanup because automatic prune is false.
