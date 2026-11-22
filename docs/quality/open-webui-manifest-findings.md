# Open WebUI manifest findings (PR #494)

This is a source-only disposition of the open-webui findings from the local PR
inventory. It does not certify runtime behavior or approve a rollout.

## Fixed

The gateway's startup, readiness, and liveness TCP probes target the node-bound
listener `10.250.0.1:18080`. The gateway now declares its actual TCP container
port (`18080`) so rendered workload metadata agrees with those probes. This is
metadata only: `hostNetwork`, node placement, listener address, redirect, TLS,
and private route are unchanged. The regression test renders the chart and
checks all three probe targets against the declared port.

## Residual findings and required decision/evidence

- **host-network (1):** retain for now. The nginx gateway listens on the
  existing private node address `10.250.0.1:18080` on `socrat-0`; removing host
  networking would change the listener's network identity. A replacement
  requires an owner-approved node-address-preserving route and offline checks
  for positive and unrelated-source denial paths before changing the listener.
- **no-read-only-root-fs (4), run-as-non-root (4):** do not assert a non-root
  identity or read-only root filesystem based only on lint advice. The pinned
  Open WebUI image declares UID 0, and the app/migration/tool-guard paths may
  need writable locations. Approval requires image-supported numeric UID and
  writable-path evidence for the app, both init-container roles, and nginx,
  plus disposable startup/restart/rollback tests preserving the data volume.
- **env-value-from (4), read-secret-from-env-var (4):** retain Secret-backed
  environment injection to preserve the app's current DB, API-key, and auth
  configuration. A change requires evidence that the pinned application
  supports file-backed credentials for each variable and an approved
  rotation/restart test that does not expose credential values. Do not move
  secrets to plain values or broaden Secret access.
- **non-isolated-pod (2):** no NetworkPolicy was guessed. The web app needs its
  current ingress, LiteLLM, PostgreSQL, and identity-related paths; the gateway
  must serve the existing private redirect path. Owner approval requires an
  exact source/destination/port matrix (including DNS and probes), followed by
  offline positive tests for required peers and negative tests for unrelated
  peers. Host-network policy enforcement must be established separately.
- **unset-cpu-requirements (2), unset-memory-requirements (2):** these remain
  on the init containers. The long-running app and gateway already have
  explicit requests and limits; their values are not evidence for the
  migration-verification and tool-guard init workloads. Do not invent resource
  floors. Measure those init workloads in a representative disposable
  environment and get owner approval for resulting request values.

The above are decision/evidence gates, not lint suppressions or accepted
baselines. No service image, secret delivery, persistence, network permission,
listener, or resource policy was changed to hide unresolved findings.
