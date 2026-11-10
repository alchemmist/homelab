# Traffic Light · TMP Lab — raw-cadence per-app sync lines

Current owner request: maximum available time precision, no graph title, slightly
less height. Native Time series panel974 at x12,y8,w6,h7 (previouslyh8), no title,
legend or Y-axis caption. root remains excluded; stable per-app colors preserved.
All other panels and canonical/public TV remain unchanged.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## Actual precision, not assumed precision

A bounded raw Prometheus range-vector query for monitoring-k3s returned timestamps
exactly15s apart (four points in1m). Argo is currently collected every15s, **not5s**.
No exporter/collector change is part of this dashboard request. Set both panel and
target interval to15s, maxDataPoints10000; the12h query returns2881 samples per app
rather than the previous721 samples. Longer ranges can still force a larger step.

Y is now the successful sync counter increment **between the last two raw
samples**, normally15s apart. No15m rolling window, rate normalization or
extrapolated fractional events. The45s lookback only locates the last two samples;
it does NOT accumulate or smooth45s of activity. PromQL uses idelta with an
explicit counter-reset branch: nonnegative delta is retained; a negative delta
means a reset and contributes the current counter value instead. Multiple
underlying counter series are reset-corrected individually before summing by app.

A value1 means one success was observed between those samples, not that a deploy
lasted15s. Actual operation timestamp within that interval, operations before the
first observation, and increments lost at reset/collection outage cannot be
reconstructed. A delayed sample can aggregate a longer interval into one point.
This remains Argo successful sync activity, NOT a Pod rollout/restart/failure log.

Fresh app_info gates inclusion; retired apps/root are excluded. Apps with no
initialized successful-sync counter can show zero. A known counter lacking two
recent samples stays a gap, not a fabricated zero. Missing/stale app or scraper
telemetry also produces gaps. Gaps are not connected;45s disconnect threshold.
A silently vanished counter can eventually become indistinguishable from an
uninitialized one while app_info remains fresh; no completeness guarantee.

Lines are unstacked, no fill/smoothing; equal/quiet values overlap. Single-series
hover identifies the app, sample time and increment. Colors are pinned by name
and independent of app order. New dynamic app series appear automatically;
regenerate overrides to pin their colors. No legend/top-k or extra blocks.

## Evidence / tests

The12h/15s live query returned48 app lines without root. Observed positive sample
counts were2 grafana,10 monitoring-k3s,2 socrat-bot,4 spi-triage,12 thanos; every
positive sample had value1 rather than the previous extrapolated~1.017. These are
point-in-time observations, not exhaustive exact deployment counts.

30 tests include native promtool cases at15s evaluation/sample cadence for root/
retired exclusion, quiet/failed-only apps, short pulse expiry, stale/down data,
known-counter gaps and counter resets. Generated-copy/original-panel checks,
height/title/step/point-budget checks, grid and Helm apply-size regression pass.
Publication changes only the existing TMP ConfigMap payload. Rendered-browser
inspection is a separate check; physical-TV acceptance remains with the owner.

## Build / ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`, ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`, Sandbox folder. Template minifies JSON to
stay below Kubernetes last-applied annotation limit. Git → monitoring-k3s Argo
auto-sync only. No custom CSS/JS/plugin, public-share, TV-setting, datasource,
collector, alert or network changes. Canonical909 stays on canonical; TMP replaces
it with974. Experiments950–973 remain only in Git history. Retirement requires
source removal and exact reviewed ConfigMap cleanup because prune is false.
