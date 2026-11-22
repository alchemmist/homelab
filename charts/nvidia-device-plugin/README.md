# NVIDIA device plugin

This DaemonSet is pinned to `socrat-0` and uses the `nvidia` RuntimeClass. Its
registration contract is the host kubelet device-plugin directory:
`/var/lib/kubelet/device-plugins`. The container mounts that directory writable
because the NVIDIA plugin registers its gRPC device-plugin socket there. Do not
make this mount read-only or replace it with a temporary/alternate directory:
that would prevent kubelet registration and GPU resource advertisement.

The image currently runs as UID/GID 0. A generic `runAsNonRoot` setting is not
safe to infer from the chart: this image's startup and access to the NVIDIA
runtime/devices and kubelet registration socket need a supported non-root
contract. Before changing identity or host access, obtain an owner-approved
runtime design and verify it on a disposable GPU node with a successful
`nvidia.com/gpu` allocation, then verify that an unavailable GPU or failed
registration is reported as failure. No cluster test is authorized by this
chart change.

The plugin has no configured HTTP health endpoint or probe port in this chart;
adding conventional HTTP probes would invent an endpoint. Establish the exact
supported health signal for image `v0.20.1` and its failure semantics before
adding probes. Likewise, do not add a default-deny NetworkPolicy until the
required control-plane and node traffic has been inventoried and both allowed
registration and denied unrelated traffic have been tested. The DaemonSet
currently declares no such network policy.

These are explicit residual decisions, not accepted findings or suppressions:
1. Approve and demonstrate a supported non-root registration/runtime design on
   a disposable GPU node before setting a non-root identity or restricting
   host access/read-only filesystem behavior.
2. Identify and verify the image's supported liveness/readiness signal before
   adding probes.
3. Identify the required network peers and validate both permitted and denied
   traffic before isolating the pod.

The digest-pinned image and writable kubelet registration mount are deliberate
runtime requirements and must remain intact unless their replacements pass the
above behavior checks.
