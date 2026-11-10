# Traffic Light · TMP Lab

Private Grafana sandbox, forked from the owner's current canonical layout on
2026-11-10. Canonical JSON, public share, TV assets and Fully settings are not
changed. This is a proposal for owner feedback, **not an approved replacement**.

Open: <https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

The preview requires normal Grafana authentication. Do not public-share spending,
key aliases or user attribution without an explicit separate review. There is no
new anonymous access, datasource, exporter, scrape target, alert or network policy.

## Research and design decisions

Reviewed upstream Grafana documentation (latest pages describe 13.3; installed
panels report 13.2.4, so use only established core options):

- [Stat](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/stat/):
  large current values work well at TV distance. Used for ready/drift/attention.
  Instant queries avoid accidentally retaining a last healthy sample during gaps.
- [State timeline](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/):
  rowHeight changes the fraction of a row, not the available panel height. The old
  two-row, two-grid-unit panel cannot become substantially more legible through
  rowHeight alone. Orange mapped to Git drift; blue mapped to progressing/paused,
  not an unexplained CPU-like magnitude. First proposal replaces these strips
  with explicit counts and named exceptions rather than repeating the same chart.
- [Bar gauge](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/bar-gauge/):
  native horizontal bars, top labels, distinct colors and abbreviated values make
  key usage comparable. No percent-capacity fiction: the range is relative to the
  largest usage value. This is input+output tokens, NOT dollars.
- [Pie/donut](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/pie-chart/):
  attractive for a small number of shares, but less effective for comparing long
  alias labels and tiny consumers. Keep as an optional next lab experiment, not
  the first TV choice.
- [Canvas](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/canvas/):
  promising for a HOME → Moscow → NL topology with data-driven arrows/status.
  Do not invent link-health or throughput from deployment readiness. Canvas is
  core in the installed version; no plugins/custom CSS/JavaScript are required.
  Defer a topology panel until actual transport/watchdog metrics are available.

### Argo: an attention board, not two unexplained lines

The old x12,y8,w6,h2 area expands into the deliberately empty central space:

| Panel | Grid | Meaning |
|---|---|---|
| Argo ready / Git drift / Apps attention | x12/14/16,y8,w2,h2 | Synced+Healthy; not Synced; not Healthy |
| Attention table | x12,y10,w6,h2 | Up to three current affected apps, health and sync status |

Counts are not disjoint: one application can be both drifted and unhealthy.
Progressing/Suspended are attention states, not automatically outages. The table
shows up to three exceptions; counters cover all. With fresh healthy telemetry it
explicitly says `All apps healthy + synced`. Without telemetry it must not claim
all clear. Click-through opens Argo for the actual events/diffs; these metrics do
not contain a root-cause explanation. This first proposal prioritizes NOW over
history; canonical retains its historical visualization for comparison. A later
iteration can add sync activity bars or a larger per-app timeline if desired.

### LiteLLM: rolling usage first; do not mistake $0 for free

[Upstream metric definitions](https://docs.litellm.ai/docs/proxy/prometheus)
confirm API-key alias dimensions for tokens, requests and spend. Actual installed
series include `litellm_*_metric_total` counters and `litellm_spend_capture_rate`.
Queries aggregate to aliases before visualization; no hashes, key values, email,
user IDs, IPs, prompts or request bodies are added to the dashboard.

Fresh audit: tokens/requests are nonzero for several aliases, but **all spend
counters are zero and the emitted provider spend capture ratio is NaN**. This
proves the monetary series is not useful for this proposal; it does NOT prove
traffic is free, and it does not diagnose whether custom pricing, subscription
billing or another accounting limitation is responsible.

- x12,y12,w6,h3: top four named aliases by tokens over rolling **24h**.
- x12,y15,w3,h1: reported USD/24h, gated on fresh scrape and every emitted provider
  capture ratio being fresh and exactly 1; currently `Unverified`.
- x15,y15,w3,h1: total proxy requests/24h, including unnamed keys.
- x2,y11,w2,h1: requests/5m for recent activity; fresh zero is legitimate quiet time.

24h is a deliberate fixed query window, independent of the dashboard's 12h range;
there is no calendar-midnight reset or noisy blank overnight. `increase` handles
counter resets but estimates between scrapes, may be fractional, cannot recover
unobserved history or replace DB/invoice billing reconciliation. Aliases represent
keys/apps, not necessarily unique people. Unnamed aliases are excluded only from
the ranking, not total requests. Existing historical labels can contribute usage
within 24h even if a key is no longer active now. No DB reads or pricing changes
are authorized/executed as part of this lab.

Next accounting step, if requested: verify model/provider pricing and capture
semantics against a bounded known request and native spend records. Only after
that swap token ranking to a USD ranking or add tokens/USD as separate panels.

### Service holes: bounded readiness, not invented probes

| Tile | Grid | Actual evidence |
|---|---|---|
| RustFS | x6,y6,w3,h1 | rustfs/rustfs Deployment available vs desired |
| VPN relay · MSK | x6,y7,w3,h1 | vpn-transit/vpn-transit Deployment available vs desired |
| S3 reader | x0,y11,w2,h1 | identity/rustfs-gateway Deployment available vs desired |

All have fresh available and desired metrics; scaled-to-zero is orange and stale
or missing is grey. Green only means the Pod readiness contract is met. It does
not demonstrate authenticated S3 PUT/GET, OIDC login, external ingress, independent
backup or working end-to-end VPN. Current VPN is Moscow worker relay → shared mesh
→ NL, with independent native fallback. Existing top `VPN mode` and clients panel
are preserved; the existing fallback metric is NOT relabelled as Moscow's mode.
No fresh Moscow watchdog/data-path metric was found in the bounded metric audit.

Good next additions, after confirming producer metrics: S3 capacity/operations and
errors; relay throughput paired with actual path-health and mode; Argo sync events
per hour. Avoid guessing full objects/S3 quota from the retained local-path PVC,
using generic node mesh traffic as pure VPN usage, or a green pod as VPN success.

## Rebuild / test / deploy

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Source JSON is generated from canonical, preserving every existing panel verbatim
except old Argo panel909. Separate UID `socrat-traffic-light-tmp-lab`, separate
ConfigMap `socrat-traffic-light-tmp-lab-dashboard`, Sandbox provisioning folder.
Do not regenerate after unrelated canonical edits without reviewing the diff.
Git → monitoring-k3s Argo auto-sync; no blanket sync/prune, live dashboard edits or
service restarts. Retiring the lab later requires source removal and, because
prune is false, exact reviewed cleanup of this one ConfigMap.

## Acceptance boundaries

All 11 new PromQL queries were executed read-only against the real datasource.
At the audit: 49 ready apps, zero drift/attention; three new deployments ready;
nonzero named-key usage; fresh requests/5m zero; monetary panel intentionally
unverified. These are point-in-time observations, not permanent health claims.
31 dashboard tests pass, including promtool cases for healthy, drift, degraded,
missing/stale data, scaled-off readiness and NaN/partial monetary coverage.

Browser launch returned `Browser is already in use` for the shared profile. No
profile lock was removed, browser closed or another person's session modified.
**Rendered-browser and physical-TV visual acceptance are not complete.** Owner
should inspect the TMP link and choose what to iterate. The native JSON/API and
layout tests do not prove font clipping or real TV readability.
