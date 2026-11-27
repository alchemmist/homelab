# Closed HTTP backend assembly: selected Pod targets

`ci/quality/closed_root_backend.py::servers` builds the backend server list
for the narrow numeric HTTP case. It does not publish a router, read an API,
make a network request or expand the DNS-only fleet's permissions. The
caller must supply an owner-reviewed namespace, Service name and frontend
port, the independently approved cluster Pod CIDR, and consistent observations.
A sampled Ready condition is not an authorization decision.

For the Schoolbot case the release chart renders a selector-backed Service
with named port `http`, frontend 80, and numeric target 8000. The regression
uses that real render with synthetic runtime metadata. It requires the slice
controller and current Service UID, its resolved target port, a non-terminating
ready endpoint, and a matching Pod UID, namespace, name, selector, readiness
and IP. A host-network Pod or a changed TLS transport is rejected rather than
treated as ordinary HTTP. This function does **not** implement named target
ports, HTTPS, h2c, middleware, all Service options, or arbitrary route owners.

Use projected fields; do not give a key reader Pod-list permissions just for
this test. Controller labels and owner references are consistency checks, not
protection against a namespace writer. The backend and the controller still
need independent policy and source-identity admission. Stale observations
can disagree; rejection means no publishable result for this backend, **not**
permission to remove a protected router and expose a catch-all. Before real
acceptance, test a coherent live inventory, source/consumer failure behavior,
and verified SNI plus the expected health response through the same listener.

## Live Schoolbot health with a disposable TLS identity

Three tokenless Traefik Pods on `socrat-0`, `socrat-2` and `socrat-4` used
image digest `aa942a00bce033c909bf1f7e861d93761be4b31a035f10d2410d33e38a8f41cf`.
Each listened only on Pod loopback TCP/8443, with no Service or host port. A
file provider used the verified live numeric Pod target from `servers`, not a
public entrance or port-forward to the backend. The disposable namespace
policy denied ingress and allowed egress only to selected Schoolbot Pods in
the `schoolbot` namespace on TCP/8000. Each client port-forward terminated at
the **controller**. No service-account token, Kubernetes provider, production
TLS material, application credential or DNS change was used.

Using a locally trusted disposable certificate for `school-health.invalid`,
all three controllers returned HTTP 200 on the exact `/api/health` route;
the bounded Schoolbot checker verified JSON boolean `ok: true`. All three
returned 404 on `/api/health-extra`, and fresh connections with actual SNI
`inform.sch1357.ru` received the strict-SNI unrecognized-name alert. The
initial JSON-provider attempt did not pass TLS; the successful rehearsal
used a YAML file. An initial Moscow scheduling timeout was followed by a
successful run using the existing exact bootstrap taint toleration on the
fixture Pod only. No node taint was changed.

This proves an anonymous real backend action through the same restricted
controller configuration on three placements. It does **not** prove browser
trust for the real hostname, normal route discovery, authenticated access,
a database operation, or survival with the other entrances removed. The
synthetic trust root was scoped to the probe, never added to system trust.

### Egress peer negative control

A second disposable run kept each controller Pod UID, verified target and TLS
fixture unchanged across three stages. Only the **namespace selector** on the
fixture egress rule changed: Schoolbot, then the unrelated fixture namespace,
then Schoolbot again. The Pod selector and TCP/8000 were unchanged. No policy
in `schoolbot` was modified. Backend idle connection reuse was disabled and
the dial timeout bounded at two seconds for this experiment, so an established
backend connection could not hide a bad selector. Each client used fresh TLS.

| Fixture egress peer | HOME health | NL health | Moscow health | Neighbor path |
| --- | --- | --- | --- | --- |
| Correct namespace and Pod labels | 200, `ok: true` | 200, `ok: true` | 200, `ok: true` | 404 on all three |
| Same labels, wrong namespace | 502 | 502 | 502 | 404 on all three |
| Correct namespace restored | 200, `ok: true` | 200, `ok: true` | 200, `ok: true` | 404 on all three |

The neighboring route staying at 404 over verified fixture TLS distinguishes
upstream isolation from losing the listener. These are **source-side egress**
observations, not destination ingress authorization or production identity.

## Preserve per-router observability choices

The live backend inventory found two owners that explicitly disable access
logs and tracing: `identity/openhands-oidc` and `automation/spi-queue-ui`.
Dropping those options when building a file-provider router could record
requests an owner meant to exclude. Carry the explicit boolean values; an
empty settings map means inherit the listener's settings, **not** disable
logging everywhere. Unsupported or ambiguous overrides block compilation.
The backend inventory remains diagnostic, not a publishable route plan.

A network-isolated stock Traefik rehearsal enabled global JSON access logs
(including internal services). Three loopback requests to synthetic exact
routes reached the same `noop@internal` backend, all returning 418. The first
and last inherited logging and appeared in the log; the middle had explicit
`accessLogs: false` and `tracing: false` and did not. No query strings, tokens,
real application requests, tracing exporter or production logs were involved.
This demonstrates access-log suppression only, not exporter-level span
suppression or end-to-end confidentiality across upstream components.

A separate network-isolated run exercised a real OTLP/HTTP exporter at 100%
sampling, with the collector and marker backend on loopback. All three fresh
requests carried distinct synthetic sampled W3C trace IDs and received the
same 200 marker body. After flushing Traefik, the collector checked the
decompressed OTLP payloads for the three known binary IDs: both inherited
controls appeared, the explicitly disabled route's ID did not. JSON access
logs likewise contained only the two control paths. An earlier collector
that did not handle chunked request bodies failed to see the controls and
was rejected as evidence. This tests export of the supplied trace IDs under
these fixture settings, not span absence under unrelated IDs, upstream
application logging or retention by a production telemetry service. No
production traces, identity-provider callbacks or user data were involved.
