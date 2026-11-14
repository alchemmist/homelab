# Grafana-only network overview

## State

**Deployed through GitOps on12November2026**, source ecf0c89f.
Argo monitoring-k3s confirmed Synced/Healthy at that revision; the authenticated
Grafana read API returned UID socrat-network with all8expected panels.
**Browser visual acceptance is still pending:** the inspection browser reached
the normal Authentik sign-in form and had no Grafana user session. Native SSO was
not bypassed or weakened.

No new
agents, exporters, plugins, datasources, storage, public shares or alert rules.
Dashboard owner is the existing monitoring-k3s Argo application, not charts/grafana.

Source: `charts/monitoring-k3s/dashboards/network.json`, UID `socrat-network`,
title `Socrat / Network`. Published URL is
`https://grafana.socrat.alchemmist.xyz/d/socrat-network` under existing native auth.
No anonymous/public dashboard publication is intended.

## What is dynamic

- Existing service-probes blackbox results, presented as a native Node Graph.
  Green/red means the last fresh check passed/failed from the single cluster
  prober. The actual probe endpoint and observer pod are edge details. Default
  selection: HOME/NL/Moscow TCP443 and existing VPN probe. VPN probe is the
  configured cluster endpoint, not an external end-to-end VPN acceptance.
- Kubernetes Running pod placement from kube_pod_info and pod phase, filtered by
  namespace. Gray node-to-pod edges are placement, NOT observed traffic.
- Ready state of nodes; independent of pairwise mesh health.
- Existing node-exporter aggregate wg-socrat RX/TX byte rates on all six nodes.
  These do not provide per-peer route, handshake, or independent-path proof.
- Telemetry age for probes and node conditions.

Graphs exclude metric samples older than120seconds. Missing edges / No data mean
unknown, NOT success. Graphs discover only currently observed rows and do not
retain an expected inventory when a series disappears. The freshness panels are
aggregate diagnostics, not complete expected-target coverage. A failed scrape
can also remove series before the120second gate. No last-known-green fallback.

## What this does not do

It does NOT automatically reconstruct WireGuard/GOST/nested relay paths, read
Ansible configuration, trace internet hops, discover application dependencies,
or predict node-failure impact. A pod placement graph is not a service traffic
map. The existing Thanos datasource has no WG peer/handshake telemetry in the
bounded inspection; interface totals alone cannot recover those paths.

Achieving that extra depth requires additional input data. This version honors
the operator's preference to try the existing Grafana stack first, rather than
introducing a parallel platform or a custom topology service.

## Acceptance already performed

- Live read-only PromQL queries via the existing Grafana MCP/Thanos datasource:
  four default probe edges with source/target/id/color/endpoint/observer fields;
  fifteen Running pod placement edges for the default namespaces at sample time.
- All six wg-socrat RX/TX counters present; all six node Ready series present.
- Six dashboard contract tests; Helm lint and render passed. Existing unrelated
  Helm warning: deprecated v1 Endpoints in scrape.yaml.
- No deliberate failed probes, service changes, route changes or CNI changes.

## Publication and browser acceptance

1. Publication completed from a clean origin/main worktree, cherry-picking only
   the dashboard commit. Other locally committed incident/DNS/watchdog changes
   were NOT pushed. Existing newer remote n8n/SPI changes were preserved. No
   blanket sync/prune or Grafana restart was performed.
2. Verify only the additional `socrat-network-dashboard` ConfigMap and the
   dashboard sidecar import are required. No Grafana restart is expected.
3. Open the UID under normal authenticated Grafana access. Check both Node Graph
   panels, edge detail menu, selectors and 30second refresh. PromQL acceptance is
   not a substitute for actual Grafana data-frame/transformation/browser acceptance.
4. Confirm existing dashboards, SSO/TLS and public-dashboard policy are unchanged.
5. Roll back by reverting the source addition; prune=false means removal of the
   ConfigMap/dashboard may require a separately reviewed scoped cleanup. Do not
   enable blanket pruning as a shortcut.
