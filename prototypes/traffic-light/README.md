# Traffic Light · TMP Lab — activity by application

Owner-directed third proposal, 2026-11-10. Replaces the rejected donut + total-sync
chart with **one app-level activity map**, not another all-green summary.

Open with normal Grafana authentication:
<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## What is shown

Native `state-timeline` panel972 fills x12,y8,w6,h8. Each row is a named Argo
application, time runs left to right. The taller panel gives up to eight thick
rows, unlike the old two thin aggregate strips. All unrelated panels/coordinates
remain verbatim from canonical. Left-side whitespace is intentional.

| Color | Meaning |
|---|---|
| Dark slate | Quiet: no higher-priority observed state or recent sync |
| Cyan | Successful sync counter increment detected within preceding10m |
| Amber | OutOfSync |
| Violet | Progressing or Suspended (paused, not necessarily deploying) |
| Bright red | Failed or Error sync increment within preceding10m |
| Dark red | Degraded or Missing health |
| Grey | Unknown/unrecognized health or sync status |

This is an **observed activity/state map**, not exact event timestamps/durations.
The10m sync window intentionally makes brief operations visible at TV distance.
A sync pulse stays visible after completion for that window; it does not mean
execution took10m. Multiple syncs inside that window merge into a single region.
Priority is Unknown > Unhealthy > failed sync > Progressing/Suspended > drift >
successful sync > quiet. Consequently a higher-priority state can hide another
concurrent event. Hover gives app/time/state; the data link opens that application
in Argo CD for exact operation details, diffs and events.

## Cohort and data quality

Up to eight applications are chosen **once at the end of the requested range**
using PromQL `@ end()`, so changing top-k membership cannot make rows pop in/out
through history. Current issues rank first. Then the score combines sync counts
and one-minute issue samples over the selected range; this favors real changes
without letting a single transient historical Unknown crowd out every active app.
Quiet zero-score apps are not used as filler. The selected rows are not promised
to be visually sorted by score; Prometheus/Grafana may list them alphabetically.
The top8 is deliberately not an exhaustive cluster incident inventory.

Each state requires fresh app data and a fresh successful Argo scrape. Missing
metrics are gaps, not dark quiet bands. Nulls are not connected; a90s disconnect
threshold prevents bridging prolonged data gaps. If no app qualifies the panel can
be empty; an empty panel is **not** proof that the cluster is healthy. Queries use
1m resolution; transitions shorter than scrape/step resolution may be missed.

Counter resets are handled by `increase`; counter pulses are inferred between
scrapes, not exact audit events. Longer dashboard ranges can downsample and hide
brief events. No incident or deployment is triggered to create decorative data.

**Sync does not mean Pod redeploy.** Healthy/Progressing and sync counters are
available, but the bounded live audit found no kube_deployment_labels series
carrying Argo instance or app-instance attribution. There is no reliable generic
join to assign all rollout/restart metrics to Argo apps. Do not guess from similar
names, add false rollout markers, or call Suspended an active deployment. Actual
workload rollouts and container restarts require a separately reviewed mapping/
producer and are not represented as such in this proposal.

## Validation / acceptance boundaries

Live12h range query returned721 samples per selected app with actual different
states, including sync, drift, Progressing, Degraded and Unknown. Observed rows
included root, spi-triage, thanos, lms, netbird, node-exporter, socrat-home and
cert-manager. Selection changes naturally as the window moves. State5 occurred
historically for LMS; red markers were NOT fabricated. These observations are
point-in-time, not a current-outage diagnosis.

29 tests pass, including native promtool tests for precedence, exclusion of quiet
apps, pulse expiry, missing/stale/down scrapes. Helm render succeeds; tests compare
every original panel except909 verbatim with canonical. Publication changes only
the existing TMP ConfigMap payload, not alerts/exporters/network policies/TV.

Shared browser profile again returned `Browser is already in use`. No lock was
removed or another person's session closed. **Rendered-browser and physical-TV
visual acceptance remain incomplete**; API/layout tests do not establish font
clipping or visual attractiveness. Owner feedback on this TMP is still needed.

## Rebuild / ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`; separate ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`; Sandbox folder. Git → monitoring-k3s
Argo auto-sync only. Canonical JSON/public share/TV assets/Fully settings are not
changed. No plugin, custom CSS/JS, new scrape, public share or test redeploy.
Regeneration reads canonical without writing it. Retirement requires Git removal
and reviewed exact ConfigMap cleanup because automatic prune is false.

Reference: [native state timeline](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/).

Previous rejected proposals (retained only in Git history): counters/table +
LiteLLM/readiness panels950–960; donut970 + aggregate sync chart971. All are absent
from current TMP. Historical LiteLLM spend audit showed zero counters with NaN
capture coverage: do not interpret it as proven free traffic or reintroduce a
misleading dollar visualization without a pricing/accounting check.
