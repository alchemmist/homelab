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
