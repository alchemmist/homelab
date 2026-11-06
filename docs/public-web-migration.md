# Public HTTPS application entry migration

Goal: ordinary public DNS and browser Authentik/MFA, without client resolver files
or VPN for web applications. Node SSH, databases, Kubernetes internals and telemetry
receivers remain private. DNS publication is not an authorization boundary.

## Reviewed first batch

| Host | Public admission | Backend authorization retained |
|---|---|---|
| grafana.socrat.alchemmist.xyz | Dedicated Authentik proxy gate, exact groups cloned from native Grafana admission | Existing Grafana OIDC roles; internal anonymous Viewer remains behind the gate, not publicly accessible without gate login |
| search.socrat.alchemmist.xyz | Authentik owner / netbird-internal-admins, mandatory MFA | Search UI, no grant to other admin apps |
| llm.socrat.alchemmist.xyz | Authentik gate with existing Open WebUI admission | Native WebUI identity, roles, chats unchanged |
| litellm.socrat.alchemmist.xyz | Authentik gate with existing LiteLLM admission | Native reviewed-subject OIDC and API keys unchanged |
| rancher.socrat.alchemmist.xyz | Native Rancher OIDC and existing restricted principals | No interactive proxy blocking Rancher agents, API bearer credentials or websockets |
| grafana-mcp.socrat.alchemmist.xyz/mcp | Existing native MCP server bearer-token validation | Existing read-only tools and fixed Grafana upstream; no health/admin backend ports exposed |

`charts/public-web-entry` owns only the new explicit Ingress resources and their
certificate references. Root Argo deploys the dedicated Application. VPS Traefik
adds exactly cattle-system and cattle-monitoring-system to its namespace list;
this requires its own targeted controller rollout, not a k3s/node/VPN restart.
Certificates are independently issued by cert-manager, not copied between owners.

Proxy gates are necessary in particular because the existing private Grafana
allows anonymous Viewer. Publishing its backend directly is forbidden. A proxy
login is an admission gate, not native Grafana identity: native Sign in remains
necessary for owner/editor privileges. Do not advertise this interim two-layer
behavior as a completed seamless native-SSO migration. No monitoring stack upgrade
or Grafana/Collector lifecycle change is part of this batch.

## Identity ownership and operations

`deploy/public-web/services.json` is an exact host/upstream allowlist.
`scripts/public-web-access.py` is create-only/audit-first. It verifies bound
mandatory MFA; preserves the existing app groups; creates separate proxy providers
and applications; adds their group bindings; preserves all existing embedded
outpost provider assignments. No users, native roles, passwords, OAuth secrets or
existing application settings are replaced. Existing gate/provider/binding drift
stops, rather than silently broadening or overwriting it.

Use `ansible/playbooks/public-web-access.yml` with the existing controller SSH and
become credentials. Default is audit. For creation, explicitly supply
`public_web_apply=true` and `public_web_approve_plan_hash=<fresh audit hash>`.
Private before/after snapshots and receipts are under
`/var/lib/homelab-public-web-access`; partial/uncertain runs block rerun pending
manual reconciliation. Never run the broad Authentik foundation configurator for
this migration. Gate readback must converge BEFORE public ingress activation.

## Remaining scope / acceptance boundaries

- Existing public chat, LiteLLM canonical host, Wiki, n8n, Harbor, Argo and x-ui
  need regression checks, not duplicate competing ingress ownership.
- Syncthing node GUI domains require a separate reviewed admission/path migration;
  node identities, BasicAuth and `/sync/` path compatibility must be preserved.
- Existing local resolver overrides must not be called unnecessary/removed until
  the affected hostname has accepted public routing. Do not touch corporate
  resolver files, Tunnelblick settings or flush global DNS during its required
  session. Clean-client verification is distinct from owner-Mac verification.
- RustFS console/S3 routes and SPI switching remain separately gated by their
  rollout authorization and acceptance; do not piggyback them on this chart.
- Test each public address with valid TLS, no cookies, forged identity headers,
  invalid tokens, native role checks and applicable API/websocket behavior.
  Tests from this Mac forced to public destinations are not independent external
  vantage tests. Do not declare all onboarding complete from anonymous redirects.
