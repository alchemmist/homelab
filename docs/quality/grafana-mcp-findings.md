# Grafana MCP manifest findings: owner decision required

Scope: PR #494, starting at `dc4ee377`, `charts/grafana-mcp`. The five blocking findings are two `env-value-from`, two `read-secret-from-env-var`, and one `non-isolated-pod`.

No manifest change is safe to infer from those diagnostics alone. The two Secret-backed values are the existing Grafana service-account token (`grafana-token`) and the dedicated MCP client bearer token (`client-token`) in `grafana-mcp-credentials`. Both are required for the real MCP→Grafana Viewer-proxy request and bearer-authenticated `/mcp` endpoint. Removing either credential, weakening authorization, or changing the service account's Viewer scope would break or weaken the service. A Secret volume is not an equivalent credential-delivery fix without confirming that this pinned upstream MCP binary supports file-backed token reload/rotation; implementing an unverified workaround is not acceptable.

The missing isolation policy is similarly not repairable with an invented peer list. The MCP needs its Grafana backend; the exact allowed inbound caller(s), DNS requirements, and any other required egress must be established against the deployed public bearer-auth route and gateway/cluster topology. A default-deny or broad allow policy without that inventory could either break real requests or silently permit excessive access.

## Required owner decisions/evidence

1. Confirm a supported credential-file interface and rotation/reload behavior for pinned `grafana/mcp-grafana:2.0.2`, for both independent tokens. If unavailable, explicitly accept the current Secret-backed environment delivery or approve an upstream-supported replacement. Preserve the dedicated client token and Viewer-only Grafana authorization.
2. Specify the exact namespace/pod selectors and source(s) permitted to reach MCP port 8000, plus required DNS and MCP→Grafana traffic. Include verified gateway/proxy identities and the Grafana Service destination; do not assume public clients connect directly to the Pod.
3. Approve that exact network boundary after offline positive/negative rendered-policy tests (authorized request path succeeds; unrelated namespace/pods, destinations and ports are denied). Validate the credential renewal path without exposing token values.

Until those decisions and evidence exist, retain the current real credentials, bearer boundary, Viewer authorization and endpoint; report the five findings as unresolved. This is a scoped residual decision, not a suppression, waiver, fabricated policy, or claim that the manifests gate passes.
