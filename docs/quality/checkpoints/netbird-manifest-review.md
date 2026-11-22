# NetBird manifest findings: approval and evidence required

This is the source-only disposition of the 62 `netbird` manifest findings listed
in PR #494's blocking-manifests review. It is not an exception, acceptance
baseline, or authorization to change the running mesh. No values, charts, RBAC,
network policy, service identity, or PVC were changed: current evidence does not
establish a safe replacement for the flagged runtime contracts. The findings
remain open pending the decisions and positive/negative tests below.

## Decisions required

- **Host networking (6 occurrences):** the four `machine-socrat-*` host peers
  use host networking for node-local routing; STUN and relay/forwarder components
  also have host-network requirements to validate separately. Owner must approve
  any per-workload alternative only after a representative disposable-node test
  covers peer reconnect/restart, route and DNS behavior, stable identity, and
  conflicts with node listeners. No host-network setting is removed by this
  review.
- **Writable host mounts (4):** the host-peer TUN device and other host-bound
  mounts are part of node networking. Before altering a mount, identify each
  path and its writer/reader, then demonstrate equivalent TUN/routing behavior,
  least required mount mode, restart/reconnect and rollback on a disposable node.
  No mount is made read-only or relocated here.
- **`NET_RAW` (5):** determine which workloads actually open raw sockets and
  whether the exact NetBird/STUN/relay feature works without this capability.
  Require a negative test proving that unneeded raw-socket use is denied and a
  positive test for the required protocol after a representative restart. Do not
  remove it based only on generic least-privilege guidance.
- **Root/non-root and read-only root filesystem (8 each):** verify the pinned
  image's effective UID, required writable paths, TUN/device access, state
  ownership and startup behavior for each workload independently. A supported
  non-root identity and writable-path plan must pass enrollment/reconnect,
  route, relay/STUN and restart checks with existing state preserved before
  changing `runAsNonRoot`, UID, or filesystem behavior. No identity or storage
  migration is assumed safe by this review.
- **Liveness (8) and readiness (6):** identify a documented, locally testable
  health signal per component. Owner must decide whether loss of control-plane,
  signaling, relay or STUN reachability should restart a process or withdraw it
  from service. Test healthy, unhealthy, dependency-loss and recovery states;
  do not invent HTTP/TCP ports or use a process-only probe that masks an
  unusable mesh. No probes are added without this contract.
- **Liveness/readiness ports (2/3) and privileged ports (2):** resolve each
  flagged port to the actual listener, protocol, bind address and privilege
  requirements from the pinned image and current config. Owner must approve any
  port remap only with rendered Service/Ingress/forwarder consistency and an
  end-to-end disposable test; no listener or route changes are made here.
- **Secret delivery (2 `env-value-from`, 2 `read-secret-from-env-var`):** verify
  supported file-based configuration and rotation semantics for the exact
  server/relay credentials, including reload/restart behavior and file
  permissions. Owner approval and a credential-renewal test without exposing
  values are required before changing delivery. Existing secret keys and
  consumers remain intact.

## Validation boundary

The disposition is deliberately not a claim that the 62 findings are fixed.
Appropriate acceptance requires rendered-object comparisons plus isolated
positive and negative behavior tests for the exact component changed. Tests must
preserve mesh peer identities and existing state; no live-cluster, VPN identity,
route, DNS, credential, storage, or deployment operation is part of this review.
Until the owner supplies these decisions/evidence, these findings remain
explicit residuals rather than being suppressed or weakened.
