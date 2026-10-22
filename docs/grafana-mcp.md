# Grafana MCP

User connection instructions live in `wiki/content/observability/grafana-mcp.md` and are published at <https://wiki.socrat.alchemmist.xyz/observability/grafana-mcp/>.

The private Streamable HTTP endpoint is `https://grafana-mcp.socrat.alchemmist.xyz/mcp`. Clients need the administrative `socrat-wg` network and its split DNS. Authentication uses a dedicated bearer token stored in `cattle-monitoring-system/grafana-mcp-credentials`, key `client-token`. Never publish the token or reuse the Grafana administrator password as an MCP credential.

The MCP service reads Grafana through its Kubernetes Service. Keep the server read-only and its Grafana identity at Viewer permissions; declarative dashboard and alert changes belong in homelab. Do not expose the endpoint through a public ingress or add public A records for it.

## Deployment

The official `grafana/mcp-grafana:2.0.2` image is pinned by digest in `charts/grafana-mcp/values.yaml`. Ansible creates or reuses the `socrat-mcp` Grafana service account with Viewer permissions, provisions independent Grafana and client tokens, and deploys the private gateway and DNS record.

Run from `ansible/`:

```sh
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/grafana-mcp.yml --ask-become-pass
```

The first run also requires `grafana_mcp_admin_user` and `grafana_mcp_admin_password` through a protected extra-vars file or Ansible Vault. Existing credentials are reused on subsequent runs without the administrator password. Sensitive bootstrap tasks use `no_log`; no token belongs in inventory. Secret resource-version changes trigger a deployment rollout when this playbook is reapplied, so environment-based credentials pick up rotations.

The MCP Service is ClusterIP-only. Its private nginx virtual host preserves the client Authorization header and supports streaming without buffering. The endpoint shares Grafana's node placement on socrat-1 and is not independently highly available. Public HTTP-01 routes exist temporarily only for certificate validation.

## Acceptance

Run `python3 scripts/check-grafana-mcp.py` from the repository root. It reads the client token through SSH without printing it.

For a client with a stale DNS cache, `--address 10.250.0.3` overrides resolution only inside the checker and keeps hostname/certificate verification intact. This proves private HTTPS connectivity but does not prove the client's system DNS cache is current.

Verify trusted HTTPS over WG, rejection without a token and with an incorrect token, successful MCP initialization and `tools/list`, and a real dashboard read and Prometheus query. Confirm write tools are absent. Check that public ingress does not expose the MCP service. A browser GET of `/mcp` is not a protocol health check.

## Wiki publication

The deployed wiki uses the shared `hugo-docs` runtime. Accepted local publications and its persistent data are authoritative; Git is synchronized in the background. Follow `docs/wiki.md` and inspect the live page after publishing. Do not overwrite `/data/repository`, force-reset it to GitHub, or restart the wiki to bypass pending publications. A committed Markdown file alone is not proof that the live page has been published.

The normal synchronization worker fetches the remote branch approximately every 30 seconds. After processing its pending local publications without conflicts, it imports the content prefix, validates and renders it, and atomically publishes the resulting snapshot. Push the new page through the normal Git workflow, then verify the live URL. If publication is delayed, inspect the runtime synchronization status and logs rather than bypassing the worker.
