# PR #494 — monitoring-k3s findings review

**Scope:** only the `monitoring-k3s` manifest owner, reviewed from `dc4ee377`.
No runtime operation was performed. No rule, gate, debt record or suppression was
changed. This review does not declare the manifest scan clean.

## Decision

No source change is safe without additional owner evidence/approval. The 22
reported findings are: `dangling-networkpolicy` (1), `dangling-service` (5),
`host-network` (2), `no-anti-affinity` (1), `no-liveness-probe` (5),
`no-readiness-probe` (4), and `non-isolated-pod` (4).

The five Service findings are composed-owner references, not justification for
inventing target workloads: Argo application-controller metrics in `argocd`, the
Prometheus OTLP receiver, node-local etcd metrics/endpoints, Grafana MCP health,
and Traefik metrics in `kube-system`. Their selectors/endpoint ownership must be
verified against the respective Argo/Prometheus, node-agent, Grafana-MCP and
Traefik owners in a composed offline inventory before changing them. Adding
placeholder Deployments, changing selectors or moving these resources could
silently remove actual telemetry or point scrapes at the wrong workload.

The network policy in `service-probe-access.yaml` is in namespace `llm`; it
selects the `open-terminal`/`vllm` workloads and admits the chart's
`monitoring-service-probes` source on TCP/8000. The labels and namespace are
cross-owner contracts. A chart-only manifest scan cannot prove that either
foreign workload has those labels, nor that this is the complete required
traffic matrix. Do not broaden or remove this policy without the composed
workload inventory and permitted/denied connectivity tests.

Both host-network workloads have a concrete source-address requirement:
`monitoring-etcd-metrics` serves node-local etcd through each node's configured
address, while `socrat-public-ip-probes` binds the LAN source address on the
selected node for direct public-IP measurements. Replacing host networking or
changing bind/route/source identity needs an owner-approved design and
representative node-path tests; the existing direct-IP regression explicitly
checks this identity contract.

The missing-probe findings concern workload health declarations, not the
blackbox target probes. Do not equate a ServiceMonitor/exporter scrape with a
meaningful readiness/liveness signal. Before adding probes, owners must specify
an endpoint or command and failure semantics for each affected container,
including whether a collector's transient backend/API failure should restart
it. The `no-anti-affinity` report likewise needs a placement decision: the
service-probe Deployment already declares hostname topology spread and a
required node affinity; do not add a conflicting scheduler requirement without
an availability/capacity review.

`non-isolated-pod` findings require an approved ingress/egress peer matrix for
the affected workloads. Existing monitoring has real scrape, telemetry and
external-probe traffic; default-deny policies with guessed peers can break
monitoring while appearing secure. Obtain source/destination namespaces,
selectors, ports, DNS needs, and both positive and negative test cases before
introducing isolation.

## Required follow-up decisions

1. Supply an offline composed resource inventory for the five external Services
   and the policy's foreign Pod selectors; verify actual target selector/port
   ownership without relying on live cluster state.
2. Approve the source-identity-preserving alternative, if any, for both
   host-network probes and prove target/source/route behavior in an isolated
   representative environment.
3. Name the supported health check and restart/readiness semantics per affected
   container; demonstrate behavior for healthy, failed, and unavailable-backend
   cases before adding probes.
4. Decide whether topology spread is sufficient for the probe exporter or
   approve a specific anti-affinity behavior with capacity/scheduling tests.
5. Approve exact network peer/port/DNS matrices for each workload; test intended
   traffic succeeds and unrelated traffic is denied before adding policies.

Until those decisions and evidence exist, leave all 22 findings visible. This is
an explicit residual decision, not an accepted baseline or a claim that PR #494's
full manifests gate passes.
