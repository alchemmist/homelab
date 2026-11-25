# Grafana MCP runtime contracts

The grafana-mcp release (`charts/grafana-mcp`, namespace cattle-monitoring-system)
reads its two tokens from environment variables via `secretKeyRef`:
`GRAFANA_SERVICE_ACCOUNT_TOKEN` (Grafana API credential) and
`MCP_GRAFANA_SERVER_TOKEN` (the MCP client bearer token). The MCP server has no
file-based configuration channel for those values; the Secret is managed out of
band.

A NetworkPolicy added in this pass restricts ingress to traefik on :8000 and
monitoring on :8080, and egress to the in-namespace Grafana API and DNS.
