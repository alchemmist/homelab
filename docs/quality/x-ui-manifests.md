# x-ui manifest findings

The chart now disables automatic ServiceAccount-token projection because x-ui's
containers do not call the Kubernetes API, and adds a TCP liveness check against
the existing node-local panel port. The readiness check remains the actual
Trojan listener; this does not change ports, routes, image, or host state.
`tests/test_x_ui_manifest.py` renders the chart and checks these behaviors and
preserves the host-network contract.

The following manifest findings remain intentionally unresolved pending owner
approval and service-specific evidence:

- **Host networking:** preserve the existing node listener and its source address.
  Decision needed: approve a staged listener/route migration only after confirming
  panel, subscription, Trojan, and certificate-renewal reachability and rollback.
- **`NET_ADMIN` / `NET_RAW`:** both are still declared. Decision needed: identify
  which capability (if either) the pinned x-ui/Xray runtime actually needs; prove
  panel, subscription and Trojan behavior with each capability removed in a
  disposable environment before changing the Pod security context.
- **Read-only root filesystem / non-root UID:** the upstream container uses root
  paths for its DB, cert and ACME state. Decision needed: obtain supported upstream
  UID and writable-path requirements, then validate a backup/restore and certificate
  renewal before changing identity, mounts, or filesystem permissions.
- **Writable host mounts:** DB, certificate and ACME hostPath mounts remain writable.
  Decision needed: approve and test a backup/restore and listener/certificate
  renewal migration first; preserve existing state and rollback. No storage path,
  ownership, or mount mode was changed.
- **Network isolation:** no NetworkPolicy was introduced. The chart uses
  `hostNetwork`, and its actual inbound/outbound peer matrix must be established
  before isolation can be meaningful. Decision needed: enumerate and test required
  panel/subscription/Trojan and DNS/ACME flows, including denied unrelated traffic.

These are residual decisions, not waivers or evidence of runtime acceptance. No
cluster interaction, rollout, backup, or production listener/certificate operation
was performed.
