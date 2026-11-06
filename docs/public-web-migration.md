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
| rancher.socrat.alchemmist.xyz | Native Rancher OIDC and existing restricted principals, public local-password actions denied | Small policy proxy preserves Rancher agents, API bearer credentials and websockets; private recovery remains |
| grafana-mcp.socrat.alchemmist.xyz/mcp | Existing native MCP server bearer-token validation | Existing read-only tools and fixed Grafana upstream; no health/admin backend ports exposed |

`charts/public-web-entry` owns the new explicit Ingress resources, their
certificate references and a small isolated Rancher policy proxy. Root Argo deploys the dedicated Application. VPS Traefik
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

## Applied acceptance — 2026-11-06

First batch is **delivered**, not just rendered: public-web-entry and traefik-edge
were Synced/Healthy at `63650a15edbacfec09ad2cc952332d3fd96b96f8`.
All six hosts have both public A addresses and no AAAA according to Google DoH.
TLS verified at both entrances. `scripts/check-public-web-entry.py` passed
**54/54** anonymous/forged-header/invalid-token checks. It reads the existing
migration-owned address inventory; repeat `--address` twice outside the repo.
Both public destinations from the Mac used the unchanged work VPN interface,
not NetBird private routes. A second LAN host also passed; that second run is
not an independent Internet vantage or proof of access from every provider.

A fresh ordinary observer completed password + personal TOTP enrollment + proxy
OIDC at the public VPS Grafana entrance. Its search API read succeeded and native
Grafana admin settings were denied. The same authenticated observer was denied
at the Search gate because it lacks the required group. Authentik renders that
policy-denial HTML with **HTTP200** at its authorization endpoint; acceptance
checks the denial state and absence of the Searx backend, not a fictitious
transport 403. All temporary test identities were deleted. Initial smoke-driver
failures were protocol mistakes (combined identification/password form and tuple
handling), not justification to weaken MFA or app policies.

MCP read-only acceptance on BOTH public entrances: missing/invalid token401;
existing valid token initialized a session and listed **20 tools**, with no write
tools. No token was printed or rotated. Existing public hostname regression:
**30/30 HTTPS checks passed**. Identity gate audit subsequently returned
**operations=0**. Tunnelblick retained its original process; NetBird4/4 and
standalone recovery WG off.

**Not complete:** owner Mac resolver cleanup; Syncthing public GUI/path migration;
full Uptime Kuma administrative SSO boundary review; exhaustive authenticated
acceptance of every app/role and clean-device browser acceptance. The existing
Syncthing service for node0 answers at its root but not `/sync/`; the node1 GUI
service failed connectivity from the controller. Do not start/reconfigure a
Syncthing writer or expose an unreviewed fallback to make this appear complete.
Local DNS overrides are still retained, especially during the mandatory work-VPN
session. New clients need no resolver files for the six delivered public hosts.

Focused source/ingress/NetBird regression: **175 passed, 4 skipped,
139 subtests passed**; public-web playbook syntax check passed. Native-route
Helm guards reject wrong namespace/service/port/path instead of treating a
`native` label as proof of backend authentication. Portal Grafana/Rancher text
was updated without changing their provider, policy or account fields.


### Rancher local-password boundary

Readback found only generic OIDC and local Rancher authentication enabled. Since
local recovery must not become a public password-only MFA bypass, the public
Rancher ingress uses a dedicated nonroot policy proxy in cattle-system. It denies
POST/PUT/PATCH/DELETE to the normalized `/v3-public/localProviders` path family,
strips method-override headers, and otherwise preserves native API authorization,
websocket upgrades and OIDC. The existing private gateway still reaches Rancher
directly for owner recovery. No Rancher config, password, principal or role is
changed. Stock nginx stable-alpine is pinned to a TLS-fetched OCI index digest
whose body SHA256 matched Docker-Content-Digest. The proxy has no mounted secrets
or service-account token and bounded CPU/memory/tmp. Logs contain status/method/
duration only, never URI, cookies or token-bearing query strings. Argo sync waves
wait for the proxy before switching the existing public ingress; no second
competing Rancher hostname owner is introduced.
