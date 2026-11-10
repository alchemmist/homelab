# Traffic Light · TMP Lab — Argo state landscape

Owner-approved direction,2026-11-10: replace sparse sync-event lines with a native
**stacked area history of application states**. All applications are accounted
for, root excluded, no per-app top-k or 48-line legend.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## Display / meaning

Panel975 replaces old canonical Argo909 only in TMP. Same compact x12,y8,w6,h7
space, no heading or Y-axis caption. Bottom legend contains five state categories,
not application names. History follows the dashboard's12h range. Queries keep15s
step and10000-point budget. Areas are normally stacked (absolute app counts),
85% fill, step-after interpolation, not smoothed. Zero-based Y axis; no percentage
normalization or baseline truncation.

- **Ready**, dark green: Healthy+Synced.
- **Progressing / paused**, bright blue: Progressing or Suspended health. The latter
  is paused, not necessarily an update or failure.
- **Git drift**, amber: OutOfSync, unless higher-priority health takes precedence.
- **Unhealthy**, red: Degraded or Missing.
- **Unknown**, grey: unrecognized/unknown health or sync state.

Exactly one contribution per app. Priority: Unhealthy > Unknown > Progressing/
paused > drift > Ready. Latest sample timestamp for each app wins over older
state label sets that may linger in OTLP storage; same-time contradictions still
resolve to one category. root is excluded from every query.

Y = how many apps are observed in a state at that moment. Colored regions show
when the healthy majority gives way to transitions or problems and then recovers.
This is NOT a sync count, Pod rollout count, per-app audit log, uptime percentage,
or root-cause diagnosis. Hover shows the timestamp and category counts, not the
names of the affected apps. Shorter-than-scrape transitions may be missed.

Fresh zero categories require actual app telemetry. Scrape failure, absent app
metrics or partially stale inventory produce gaps in all five queries. Nulls are
not connected;45s disconnect threshold. If an app disappears beyond Prometheus'
lookback, a changing observed total cannot alone distinguish deletion from a
producer silently losing that app. No completeness/availability guarantee.

## Validation

Live12h/15s queries yielded real variation: Ready41–48, Progressing/paused0–6,
drift0–1, Unhealthy0–1, Unknown0–6 during the bounded audit. No test failure or
production rollout was triggered to manufacture colors. These are historical
observations, not claims of a current cluster outage.

30 tests cover generated-copy/canonical-panel preservation, native area stacking,
state colors, title/height/cadence, grid and rendered apply size. Native promtool
cases verify mixed states, no double-counting of simultaneous drift/Progressing,
root exclusion, fresh healthy zeros, absent/down/stale/partially stale telemetry,
newer status replacing lingering older labels and same-timestamp contradictions.
Helm comparison must change only the existing TMP ConfigMap payload.

Browser inspection is a separate acceptance step. Physical-TV readability and
owner visual approval remain separate from query/unit-test success.

## Build / ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`, ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`, Sandbox folder. Template compacts JSON
below Kubernetes last-applied annotation limit. Git → monitoring-k3s Argo auto-sync.
No custom CSS/JS/plugins, public-share, TV, collector, alert, network or canonical
JSON changes. Existing unrelated worktree changes belong to another task and are
not included. Experiments950–974 remain only in Git history. Retirement requires
source removal and exact reviewed ConfigMap cleanup because prune is false.
