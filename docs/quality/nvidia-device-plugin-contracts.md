# NVIDIA device plugin host contracts

`nvidia-device-plugin` (DaemonSet, kube-system, pinned upstream v0.20.2) is a
node device driver, not a network service. The reviewed upstream `main.go`
resolves the host NVIDIA driver root and device nodes, opens NVML/devices, and
creates the kubelet gRPC socket under
`/var/lib/kubelet/device-plugins`. Root access is required to inspect/open the
host GPU devices and to create that kubelet-owned socket; the writable hostPath
is the required kubelet device-plugin channel.

The upstream implementation writes its sockets to that mounted host directory
rather than the image filesystem. The chart therefore adds read-only rootfs
plus /tmp, and exec liveness/readiness probes that assert the actual
`nvidia.sock` Unix socket exists (there is no HTTP health endpoint). A
NetworkPolicy with no ingress/egress is appropriate because the daemon uses
only the local Unix socket. Root and the writable host mount are registered as
the unavoidable node-driver contracts with this evidence.
