# Official MCP connections for Homelab agents

Audit date: **2026-11-07**. Full point-in-time inventory and one decision per
Application: [`deploy/mcp/service-audit.json`](../../../deploy/mcp/service-audit.json).
This covers all 49 Argo Applications, every Deployment/StatefulSet/DaemonSet and
running systemd services on socrat-0/1/2/3, including internal database/cache and
Rancher/Fleet components. Supporting automation is not turned into one MCP per Pod.

## Project connections

No agent is required to contribute. A fresh clone contains no active Pi project
configuration. [The optional Pi example](../../../deploy/mcp/examples/pi-mcp.json)
documents reviewed connections; it does not install or enable anything. To opt in
after installing the runtime, copy it to `.pi/mcp.json` in a trusted checkout
(`mkdir -p .pi && cp -n deploy/mcp/examples/pi-mcp.json .pi/mcp.json`). Do not
commit local settings. Other clients should configure their own credential
transport; Pi's `!command` headers are not portable MCP configuration syntax.

| Name | Upstream / connection | State / purpose |
| --- | --- | --- |
| `socrat-grafana` | `grafana/mcp-grafana` 2.0.2, existing digest-pinned HTTPS server | Read-only Grafana plus Prometheus/Thanos, Alertmanager, Loki, Tempo and Pyroscope |
| `argocd` | `argoproj-labs/mcp-for-argocd`, npm `argocd-mcp` 0.9.0 with the [homelab Zod 4 port](../../quality/npm-patches.md) | Official project **Labs**, stdio, `MCP_READ_ONLY=true`; diagnostics, not an imperative deploy path |
| `socrat-metrics` | `prometheus/prometheus-mcp`, stable 0.18.0 | Official upstream binary, stdio; queries/docs/metadata through existing Grafana Viewer datasource proxy |
| `n8n` | Built into installed n8n 1.123.87 | **Disabled client pending owner enablement**, no third-party n8n wrapper |
| `umami` | Official `@umami/mcp` 0.2.0; native endpoint also exists in installed 3.4.1 | **Disabled client pending an authorized API key** |
| `github` | Official external GitHub remote MCP | Remains disabled, preserving earlier project policy |

The existing global `homelab-wiki` access is preserved, not replaced by a new
wrapper. Local stdio servers are started by the agent; they do not require
permanent cluster Deployments, new public ports or shared admin MCP credentials.
The tiny launcher only executes pinned upstream binaries with private credentials;
it implements **no MCP protocol, tools or REST-to-MCP translation**.

### Install on an agent machine

Requirements: Python3, Node20+, npm, trusted HTTPS, existing authorized SSH access
to socrat-0 for the initial credential copy. macOS arm64/x86_64 and Linux
amd64/arm64 artifacts are explicitly checksum-pinned.

```sh
python3 scripts/setup-official-mcp.py
```

This installs npm packages using `deploy/mcp/clients/package-lock.json`, verifies
the official Prometheus release archive SHA256 and extracts only the regular binary.
It reuses, **without rotation**, the already-provisioned Grafana Viewer/client
tokens into `~/.config/homelab/mcp/` (directory0700, files0600). The original
`~/.pi/agent/argocd-mcp-token` and `~/.config/n8n/mcp-token` are retained separately.
No password or new privileged role is created. After an authorized token rotation,
rerun setup to refresh the local Grafana copies; do not print the credentials.

The private file `metrics-http.yaml` references the Viewer token by filename and
rejects redirects. Direct Grafana MCP headers come from `mcp-credential.py` into
the client's pipe; **do not run that helper in a terminal to display output**.
Runtime read checks reject symlinks, wrong file ownership and group/world permissions.

Restart/reconnect MCP or start a new trusted Homelab session to load settings.
An existing agent session does not gain new tools merely from a Git commit.
Other MCP clients need their own native configuration format; this does not claim
automatic Claude/Cursor/Codex installation or credentials on other machines.

### Prometheus vs Thanos, and a stable-release trap

The existing Grafana datasource UID `prometheus` points to **Thanos Query**.
`socrat-metrics` uses that existing Viewer-authenticated proxy, not a new direct
TSDB/admin route. The common PromQL/label/series/metadata APIs work without setting
a specific backend. Native TSDB config/WAL/admin endpoints are not promised.

In upstream 0.18.0, setting `--prometheus.backend` overrides the explicit tool
allowlist and registers extra tools, including destructive ones. The launcher
intentionally **omits that flag** and selects only `build_info` plus the upstream
core query/docs/metadata set. Live `tools/list` must exclude reload, quit, snapshot,
delete_series and clean_tombstones. It also binds the ancillary web listener to
`127.0.0.1:0`; stdio must not create an anonymous listener on all interfaces:8080.
Do not replace the stable binary with a latest tag/RC just to avoid reviewing this.

### Grafana telemetry tools

The existing read-only Viewer identity and `--disable-write` remain in force.
Only the MCP Deployment's enabled tool families change: Loki, Tempo, Pyroscope
are added. No Grafana/database/backend restart, new datasource, duplicate scraper,
retention change or credential rotation is required. Loki query guardrails cap
range24h, estimated scan512MiB and returned log lines100; use bounded queries.

The canonical endpoint is `https://grafana-mcp.socrat.alchemmist.xyz/mcp`.
It already has a public exact reviewed bearer-auth route plus private access;
older VPN-only prose is historical. Trusted HTTPS and missing/invalid bearer
rejection must be verified; an HTML login page with HTTP200 is **not** MCP success.

## Pending native authorizations: deliberately not bypassed

### n8n

Native MCP exists but direct backend testing found:
- missing/invalid bearer → **401**;
- the existing valid MCP token → **403**, instance-level MCP disabled.

Public `/mcp-server/http` also fell through to the browser SSO gate and returned
HTML200. The two existing n8n ingress resources are now owned by the n8n chart;
all UI/TLS/routing identities are retained. Only exact `/mcp-server/http` is added
to the higher-priority native machine ingress. No wildcard `/rest`, whole-path SSO
bypass or anonymous server is added. Missing/invalid tokens must still return401.

The existing owner/admin must enable **Settings → Instance-level MCP → Enable MCP
access** in the native UI. No owner login/cookie is available to automate that
legitimately. Do not edit SQLite/settings directly, reset the account, forge a
session, rotate the existing MCP token or expose all workflows to get past403.
Then recheck initialize/tools/list and enable the project entry. On this installed
version, expect search/details/execution tools, **not** newer v2 workflow-edit tools.
The project exposes only search/details; production workflow execution stays hidden.
No workflows are toggled MCP-available or executed by this rollout.

### Umami

The installed3.4.1 image includes native `/mcp`, disabled unless `MCP_ENABLED=1`.
The official stdio package can call the existing API without enabling another HTTP
listener, so no service restart or latest-image pull is necessary. Supply a
separately authorized analytics API key for the intended user/team in
`~/.config/homelab/mcp/umami-api-key` (0600), then verify a bounded website read and
enable the project entry. No authorized key was available during the audit.
Do not reuse the database password, guess default credentials or reset an admin.

## Why not another MCP for every service?

- Official source is not sufficient: NetBird has no release and its documented
  npm package is unpublished; its cloud token store is explicitly a prototype.
- Rancher's first-party AI component has no standalone stable release and broader
  resource-write surface. Do not install a whole AI-agent stack or share an admin
  token just for inventory. Argo/Grafana already cover useful diagnostics.
- RustFS MCP is source-only without a release, with object upload/delete and
  access to backup data; root S3 keys are not an agent diagnostics credential.
- LiteLLM's official admin connector requires `proxy_admin` even for reads, plus
  gateway permission-response compatibility. No blanket admin token or proxy
  upgrade is introduced just to populate an MCP list.
- Uptime Kuma's native MCP is on master, not installed stable2.5.7; no unreleased
  upgrade or database migration is performed. Other upstreams are recorded as
  no suitable first-party operational MCP identified, not universally impossible.
- Open WebUI/vLLM MCP consumer support is not a server for administering them.
  Open Terminal **does** have first-party native MCP, but it exposes every API
  endpoint, including shell/file writes, under the shared terminal key. It is
  deliberately not enabled as a general diagnostics connector.
- Redis and MariaDB have official MCPs, but their deployed instances are internal
  application data planes. They are intentionally not exposed to agents as SQL,
  cache content or credential access. PostgreSQL reference/community adapters are
  not first-party PostgreSQL operational MCPs. Custom business-service wrappers
  and arbitrary OpenAPI-to-MCP generation are outside the user's requested scope.

All decisions and source links are in the audit, including infrastructure,
controllers, exporters, platform dependencies and our own applications.


### Optional Pi setup with cached launchers

Authorized operators can instead pass `--configure-project /path/to/homelab`
to the installer to use absolute cached launcher paths. This option backs up
existing private settings before rewriting them and refuses tracked/unignored
configurations. Without the option, setup does not write any agent configuration.

## Verified closeout

Feature handoff: `e77eed4`. Snapshot: 49 Applications, 114 workload controllers,
271 Pod records (including completed jobs/direct operator-owned database Pods),
and running service-unit inventories on all four nodes. These are inventory
counts, not a claim of 271 independent services or MCP installations.

- Actual Pi configuration loader accepts both the tracked worktree settings and
  the original Homelab checkout's private cached-path settings. The latter had
  unrelated dashboard/Traefik work: tracked source/branch was **not** reset or
  merged. Its old owned project symlink was recorded privately and detached;
  the shared config target is untouched. Existing project-specific Wiki settings
  remain in the ignored local config; none of those credentials went into Git.
- Argo CD: initialize, tools/list (11 tools), no write tools, real bounded
  application listing. Official metrics: same checks (10 tools), real `query=1`.
- Grafana MCP: 37 tools, all read-only; trusted HTTPS, missing/invalid token denial,
  dashboard read and Prometheus query pass. Loki labels, scoped Tempo resource
  attributes and Pyroscope labels succeed through the actual MCP, without printing
  response data. This is not every-producer ingestion/profile coverage acceptance.
- Both adopted n8n Ingress UIDs are unchanged and tracked by `n8n`. Grafana's
  actual Pod and n8n's actual Pod retain UID; the Grafana MCP rollout is intentional.
  Grafana MCP credential Secret UID and content hash are unchanged.
- n8n public endpoint now returns native JSON401 for missing/bad tokens and
  JSON403 for the existing valid token until owner enablement, not HTML200.
  The n8n/Umami project entries remain disabled; no claimed successful connection.
- **131 tests + 24 subtests**, Helm lint for both affected charts, and public
  regression **134/134** pass. These are focused regression checks, not a fresh
  browser MFA, backup restore or full monitoring-data-integrity acceptance.

Setup can use `--offline --archive /path/to/the/release.tar.gz` with the existing
npm cache; the archive checksum is still enforced. The release archive is never
extracted wholesale. Private original-profile rollback metadata is under
`~/.config/homelab/mcp/project-backups/`, never in Git.

## MCP for Homelab agents — 2026-11-07

The agent entry point is `AGENTS.md`; Pi is optional; see the example
`deploy/mcp/examples/pi-mcp.json` — local settings are not in Git.
Initial connection protocol: [runbook](official-mcp.md),
[audit-time registry of all services](../../../deploy/mcp/service-audit.json).
The later local n8n enablement is described below; the earlier blocker in the
registry does not mean the endpoint currently refuses.
The audit covered 49 Argo Applications, all Deployment/StatefulSet/DaemonSet
and running systemd units of the four nodes, not only the Helm catalog apps.

## Connections

- `socrat-grafana`: the already-deployed official Grafana MCP 2.0.2; Viewer,
  disable-write, Loki/Tempo/Pyroscope added. Dashboards, Prometheus/Thanos,
  Alertmanager, logs/traces/profiles are available through it. Passwords/
  certificates are not rotated.
- `argocd`: official **Argo CD Labs** MCP 0.9.0, pinned npm lock, stdio/read-only.
  GitOps remains the desired-state path, not live mutation via MCP.
- `socrat-metrics`: official Prometheus MCP stable 0.18.0, stdio, common
  read-only PromQL/docs/metadata APIs via the Grafana Viewer and the **Thanos
  datasource**. This is not a direct TSDB/admin/WAL API. Do not set
  `--prometheus.backend`: in this version it overrides the allowlist and
  returns extra tools, including destructive ones.
- `n8n`: native MCP **works**. After the local access-token update, real
  `initialize` and `tools/list` passed; the server returns
  `search_workflows`, `execute_workflow`, `get_workflow_details`. In the Mac's
  local project config the client is enabled; agents get only search/details;
  execution stays hidden. The token is stored only in
  `~/.config/n8n/mcp-token` (0600), not in Git. The exact route
  `/mcp-server/http` belongs to n8n; the UI gate/TLS are preserved. The
  original backend 403 is no longer a current blocker.
- `umami`: official stdio 0.2.0 is installed, but there is **no authorized
  API key**. The client is disabled; a scoped user/team analytics key (0600)
  is needed, not the DB password.
- The global wiki MCP is preserved; GitHub remains disabled in the project.

`python3 scripts/setup-official-mcp.py` installs verified upstream binaries
and reuses the existing Grafana credentials without rotation; private copies
stay out of Git. A new agent/MCP reconnection will load the project config
after the repository is trusted. Do not run the credential helper manually to
print the token. Other machines/clients need their own setup; do not promise
that this commit configured them automatically.

No MCP for the sake of numbers: NetBird/Rancher/RustFS are first-party sources
with caveats about a stable package/authorization; LiteLLM admin requires
proxy_admin even for reads; Kuma MCP is absent in the installed stable 2.5.7.
Internal DB/cache, backup buckets, controllers and our own services get no
hand-written/third-party wrappers or broad rights. Open Terminal has native
MCP, but it exposes the full shell/file API under the shared key; it is
deliberately not enabled as an ordinary diagnostics connector. The decision
for **every** Application with upstream evidence is in the registry.

Read-only tools do not permit an agent to publish logs/private data, execute
workflows, silence alerts, or treat Healthy as proof of WAL integrity.
HTTP200 with an HTML/IdP login page is not a successful MCP initialize.

## Verified outcome

Feature commit `e77eed4`; the full audit also contains 271 Pod records
(including completed jobs and operator-owned DB Pods) and 114 workload
controllers — this is **not** a count of separate services/MCP. The tracked
config has 3 enabled official connectors; the previously working local wiki
access is preserved separately.

Verified: the actual Pi loader, Argo 11 tools + a real read, metrics 10 tools +
`query=1`, Grafana 37 read-only tools + auth rejection/dashboard/query.
Loki/Tempo/Pyroscope metadata was really read via MCP, without printing
contents. Both n8n Ingresses kept their UIDs and are owned by n8n; the
Grafana/n8n Pods were not restarted; the MCP Secret UID/contents did not
change. Deliberately only the Grafana MCP rollout with the new tool families.

131 tests + 24 subtests; public regression 134/134. The old WAL incident was
not “fixed”, no alert hidden. These are original acceptance results, not a new
full run. n8n's 403 was the original blocker and was closed by a later protocol
check; **the Umami missing key remains**.

The original dirty checkout retains dashboard/Traefik changes; branch/source
were not reset/merged. Its ignored project MCP config was switched to the
installed cached launchers after a private backup of the old symlink; the
shared target and the Wiki override are preserved. Do not commit private local
config with inherited credentials: the new tracked version in main contains
only safe references. A new trusted session will see the connections; an
already-running MCP session needs a reconnect.


## Outcome after the local n8n enablement

No additional MCP deployments on the cluster are required. The Argo and
metrics servers are started by the agent over stdio as designed; there is no
need to move them into permanent Pods for the count. Umami is an optional
follow-up if agents need traffic analytics: first a separate authorized
analytics API key.

It is important to distinguish local vs shared config: n8n is enabled in the
private `/Users/antonmoss/code/homelab/.pi/mcp.json`; the example
`deploy/mcp/examples/pi-mcp.json` still contains the conservative
`enabled: false`. This wiki-only update does not change the shared config,
runbook, audit or settings on other machines. On a new checkout, verify the
entry's state, your own authorized token and the protocol handshake, then
enable the client without widening toolExposure. Do not copy the entire local
private config into Git — it may contain inherited credentials of other MCPs.

A new session on the configured Mac will pick up n8n; an existing one needs a
reconnect. The token update does not permit executing production workflows and
does not mean they were executed during verification: only handshake and
discovery were checked. A token passed through chat should be reissued at the
earliest opportunity; this is a security recommendation, not a current
technical blocker. Do not repeat the token value in documentation, commits
or logs.
