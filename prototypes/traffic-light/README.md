# Traffic Light — approved Argo landscape (TMP retired)

Owner approved the compact stacked application-state history and explicitly
requested promotion to the canonical Traffic Light and deletion of TMP.

<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true>

## Production panel909

The approved live TMP975 is copied exactly, except ID909 replaces the existing
canonical Argo panel. x12,y8,w6,h6, no title, legend retained. Native Time series,
normal absolute-count stacking,85% area fill, step-after interpolation. No outlines
(lineWidth0), so zero Unhealthy does not draw a misleading red roof. Nonzero
Unhealthy retains its red fill. Other panels, UID, dashboard metadata, public share
and Fully Kiosk/TV settings are unchanged.

- **Ready**, dark green: Healthy+Synced.
- **Git drift**, amber: OutOfSync (cluster differs from Git), unless higher-priority
  state takes precedence; not necessarily unhealthy.
- **Progressing / paused**, blue: Progressing or Suspended health. Progressing means
  not yet ready; Suspended means paused, not necessarily active work.
- **Unknown**, grey: unknown/unrecognized health or sync state, not confirmed failure.
- **Unhealthy**, red: Degraded or Missing.

Counts are Argo applications, not Pods, sync operations or verified rollouts.
One contribution per app; root excluded. Priority: Unhealthy > Unknown >
Progressing/paused > drift > Ready. Latest timestamp wins over lingering old label
sets; simultaneous contradictions resolve to one category. All apps, not top-k.
Hover shows category counts, not app names/root cause. Area thickness is the count;
the upper boundary is cumulative, not the count of the top category alone.

Single PromQL target computes all categories,15s step/10000-point budget,12h
selected history. Missing/down/partially stale scrape telemetry yields gaps, not
healthy zeros; nulls are not connected. Missing inventory beyond lookback can lower
the observed total, indistinguishable from deletion without separate inventory.
No collector, scrape cadence or production rollout change.

## Maintenance / tests

```sh
python3 scripts/build-traffic-light-argo.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

30 tests cover canonical-panel preservation, geometry, title/legend/fill/zero
outline, colors/cadence, Helm size/no TMP rendering, PromQL partition, root
exclusion, healthy zeros, absent/down/stale/partially stale telemetry, newer state
replacing old labels and contradictory same-time states.

Live canonical was compared with Git before promotion; differences were only
Grafana API default normalization, no uncaptured owner edits. Promotion checks
prove all top-level source settings and all non909 panels unchanged and panel909
identical to approved live TMP975 except ID. Helm diff is exactly canonical
ConfigMap payload update plus removal of TMP ConfigMap from desired manifests.

## Retirement

Removed TMP JSON, Helm template and lab generator/test names. TMP UID was
`socrat-traffic-light-tmp-lab`; ConfigMap was
`socrat-traffic-light-tmp-lab-dashboard` in `cattle-monitoring-system`, Sandbox
folder. Automated prune remains false: after canonical reconciliation/inspection,
delete only that verified ConfigMap with UID/resourceVersion preconditions and
verify sidecar/provisioning removes the old Grafana dashboard. No blanket prune,
folder deletion, direct Grafana mutation or changes to the canonical public share.
Earlier rejected experiments remain only in Git history.

### Deployment receipt

Canonical reconciled and inspected at1920×1080 using the existing TV URL in an
isolated read-only browser; the state query returned HTTP200. Live comparison
proved all non909 panels and all nonversion dashboard settings unchanged;
canonical909 equals approved live TMP975 except ID. Tests30/30 and scoped Helm
diff passed. Argo's sole initial OutOfSync item was the retired TMP ConfigMap
(requiresPruning), not a failed canonical apply. Deleted that exact ConfigMap using
its captured UID+resourceVersion in DeleteOptions; API returned Success for the
same UID. Argo then Synced/Healthy. Grafana read API confirms TMP UID404 Not Found.
Canonical public UID/share and TV configuration were not recreated or mutated.
