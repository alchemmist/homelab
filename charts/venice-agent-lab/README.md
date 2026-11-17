# Venice agent execution worker — undeployed draft

This is **not an OpenHands installation**. It is a credential-free execution
worker candidate for a separate mini-SWE-agent / OpenHands SDK controller.
There is deliberately no Argo Application, ingress, frontend, model secret,
controller deployment, cluster-wide role, Docker socket or hostPath.

The worker uses an immutable Node image, UID/GID 1000, read-only root,
no privilege escalation, dropped capabilities, RuntimeDefault seccomp,
bounded memory-backed workspace/tmp, and a deny-all ingress/egress policy.
Its service-account token is not mounted. The controller account also has token
mounting disabled by default; a future controller would explicitly project a
short-lived token into its own pod, never the execution pod.

A namespaced Role permits only get/delete of the fixed worker pod and get/create
of that pod's exec subresource. It cannot read secrets, list arbitrary pods,
create workloads, or modify deployments. The controller should delete/reset the
worker between tasks and verify the new pod UID; workspace state is disposable.
The model must only receive the custom remote bash tool, not the controller's
local terminal/file editor or dynamic MCP tools.

## Gates before activation

1. Choose an executor from measured accepted/blocked tasks and error receipts.
2. Build/pin the controller through Git and CI, not runtime package installation.
3. Add durable controller-only checkpoints, cancellation, original-deadline
   preservation and strict bounds; copy no model credentials into worker files.
4. Verify RBAC allows only the named exec target and rejects secret access,
   other pods, other namespaces and workload creation.
5. Verify actual CNI enforcement with negative DNS, API-server, LAN and public
   egress probes. A rendered NetworkPolicy is not proof of enforcement.
6. Check node/runtime PID limits. Kubernetes has no portable per-pod `pidsLimit`
   field equivalent to the local Docker harness's 128-PID setting. This draft
   does **not** claim that limit or a gVisor/Kata boundary.
7. Test positive workspace writes, read-only root, absent tokens/credentials,
   bounded output, frozen artifacts, fresh verification, restart and cancellation.
   The local Docker snapshot implementation is not a Kubernetes implementation.
8. Add native authenticated access before any UI ingress. Keep the initial
   controller headless; do not expose the standard host-access Agent Canvas
   launcher or mount the host/container runtime socket.
9. Activate through homelab Git and Argo only after these gates. No live image
   overrides. Preserve existing Venice, Qwen, identity, profiles and PVCs.

An actual first cluster pilot should be a single bounded task in a dedicated
namespace, not an unattended multi-hour rollout. The worker image currently
supports the Node fixtures only; real Venice/Python audits require a separately
CI-built, dependency-prepared worker image.

Local validation: `helm lint charts/venice-agent-lab` and `helm template` plus
Kubernetes client dry-run. These are schema/rendering checks, not runtime proof.
