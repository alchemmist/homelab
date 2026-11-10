# Traffic Light · TMP Lab — Argo only

Owner-directed second proposal (2026-11-10). The first counters/table/LiteLLM/
readiness proposal was rejected. All its added panels950–960 have been removed.
Only the Argo area differs from canonical; original service tiles, resources,
node row, n8n, VPN and intentional left-side whitespace are preserved verbatim.
Canonical JSON/public sharing/TV assets/Fully settings are unchanged.

Open with normal Grafana authentication:
<https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light-tmp-lab?kiosk=1>

## Two graphic panels, no big numeric tiles or table

- **Application state ring**, panel970, x12,y8,w6,h4. Native Pie chart in donut
  mode, without numeric labels; compact colored legend. Every app contributes to
  exactly one slice: Ready (Healthy+Synced, green), Git drift (Healthy but not
  Synced, amber), Working (Progressing/Suspended, blue), Unhealthy (Degraded or
  Missing, red), Unknown (other health states, grey). Nonhealthy status takes
  priority over sync drift so no app is double-counted. Hover exposes counts;
  this is status distribution, not uptime percentage. With all apps healthy the
  ring is solid green; do not invent decorative incidents to make it multicolor.
- **Sync activity**, panel971, x12,y12,w6,h4. Native time-series visualization
  using stacked, slightly separated, opacity-gradient columns. Completed syncs
  per 15-minute window: Succeeded green, Failed amber, Error red. Query step and
  increase window both15m; full history follows dashboard range (currently12h).
  Actual sync counters contain these phases. Fresh quiet time is zero and stale
  telemetry is a gap. `increase` handles resets but yields estimated/fractional
  counts; this is not an exact event log. Argo reconciliation without a sync is
  not counted. Color mappings remain stable if a series disappears.

No extra service tiles, LiteLLM panels, counters or attention table. No plugins,
custom CSS/JavaScript, new exporters, alerts, network policies or public sharing.
Links open native Argo CD for investigation. The donor panel909 remains on the
canonical dashboard for comparison and is removed only in this TMP.

## Validation and limits

All five donut queries and the12h activity query executed read-only on real data:
49 Ready apps at the audit; activity had successful operations in33 of49 queried
windows and no failed/error increments. These are point-in-time observations.
29 dashboard tests pass, including native promtool tests for disjoint categories,
healthy zero categories, missing/stale/down scrapes and quiet/active sync counters.
Full Helm render succeeds; original panels are checked verbatim against canonical.

Browser launch again returned `Browser is already in use` for the shared profile.
No profile locks or other person's session were touched. Rendered-browser/font/
physical-TV visual acceptance is **not complete**. Owner feedback on the TMP link
is needed; API/geometry checks cannot establish that the result looks attractive.

## Rebuild and ownership

```sh
python3 scripts/build-traffic-light-lab.py
python3 -m unittest discover -s tests -p 'test_traffic_light*.py'
helm template monitoring-k3s charts/monitoring-k3s -n cattle-monitoring-system \
  -f charts/monitoring-k3s/alert-graphs.values.yaml
```

Separate UID `socrat-traffic-light-tmp-lab`; separate ConfigMap
`socrat-traffic-light-tmp-lab-dashboard`; Sandbox folder. Deployed through Git →
monitoring-k3s Argo auto-sync only. Regeneration reads canonical without writing
it; review donor changes before regenerating. Retiring the lab requires Git
removal and exact ConfigMap cleanup because automatic prune is false.

Native visualization references researched for this proposal:
- [Pie/donut](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/pie-chart/)
- [Time series](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/)
- [State timeline](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/state-timeline/)

Historical LiteLLM audit from rejected proposal: token/request metrics had nonzero
usage by alias, all spend counters were zero and emitted spend capture ratio NaN.
Do not treat zero spend as free traffic. No pricing or billing configuration was
changed; monetary visualization is now entirely removed as requested.
