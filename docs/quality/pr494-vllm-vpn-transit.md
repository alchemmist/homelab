# PR #494 service findings: vLLM and VPN transit

This note records the scoped offline review from `dc4ee377` and the one safe
manifest correction. It does not certify runtime behavior or authorize a rollout.

## VPN transit

The rendered relay Deployment already declares its actual localhost TCP readiness
check (`127.0.0.1:443`), but had no matching declared container port. The chart now
declares TCP/443 as `https`; this is container metadata and does not add a
listener, hostPort, route, or network permission. A scoped test checks that the
port declaration and readiness check agree.

Residual findings and required evidence/decision:

- `image-digest`: the image is a node-local `localhost/homelab/vpn-transit` artifact
  and the chart uses `imagePullPolicy: Never`. The configured tag/hash is not an
  authoritative OCI descriptor. Publish/provide the exact artifact's authoritative
  OCI descriptor (and verify it against the deployed binary) before pinning it;
  do not substitute a fabricated digest or a public image.
- `host-network`: required by the current relay design to own the node-local
  listener; preserving host networking avoids changing the endpoint and failover
  contract. A replacement needs a reviewed endpoint/port-owner migration.
- `no-liveness-probe`: readiness confirms the actual local TCP listener. No
  independent process-health signal is currently evidenced; adding a liveness
  probe based on the same socket could restart a process on an endpoint symptom.
  Provide an authoritative health contract and prove positive/negative behavior
  before adding one.
- `non-isolated-pod`: host-networked node relay has no safe Kubernetes policy
  boundary demonstrated here. Provide a complete required traffic matrix and
  prove permitted and denied flows before proposing isolation.
- `run-as-non-root`: the chart documents that this static Go executable needs
  effective `NET_BIND_SERVICE` under the current CRI to bind 443. Preserve root
  and the narrowly-added capability until a candidate identity is proven to bind
  the required listener on a disposable node without weakening this contract.

## vLLM

No safe source-only change resolves these five findings. The chart's NVIDIA GPU,
model cache and API-key requirements are real; changing identity, filesystem,
secret delivery, or callers without evidence could break inference or expose the
service.

- `env-value-from` and `read-secret-from-env-var`: provide upstream/version-specific
  evidence that vLLM accepts the API key from a mounted file, including a safe
  renewal/reload path and tests that authorized requests continue to work while
  missing/invalid keys are rejected. Do not replace the key with a literal, weaken
  authentication, or invent a wrapper.
- `no-read-only-root-fs` and `run-as-non-root`: prove image startup, model-cache
  access, GPU device access and all writable paths under a candidate numeric UID
  and read-only root, with positive inference and negative permission tests. The
  existing `/model-cache` PVC does not prove all runtime writes or GPU permissions.
- `non-isolated-pod`: identify actual required clients (including LiteLLM and
  monitoring) and required egress, then test allowed and denied flows using the
  real owner selectors in an offline composed inventory before authoring policy.

No live cluster checks, workload changes or generated evidence were used.
