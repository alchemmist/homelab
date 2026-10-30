# Cats image delivery

## 2026-10-30 recovery

The second Cats replica on socrat-3 could reach registry-1.docker.io but timed
out reaching both resolved IPv4 addresses of auth.docker.io. Forcing IPv4 did
not resolve it. No cluster routing or DNS configuration was changed.

The healthy socrat-0 replica used manifest digest
`sha256:a85ce9a2ade6edad537e920303b171c8a7dd5c60ce072edf981ff2fe4b52b4b8`.
The same image was exported to a regular archive file from containerd, copied
via SSH/SCP, SHA-256 checked, and imported into the `k8s.io` namespace on
socrat-1 and socrat-3. All three eligible nodes have the image; socrat-2 is
excluded by the chart's node affinity.

The chart now uses that digest and `IfNotPresent`. Helm release cats revision
17 deployed successfully: both replicas Ready on socrat-1 and socrat-3, public
HTTPS returned 200. This avoids registry token requests for an already cached
immutable image. It does **not** fix general Docker Hub connectivity.

## Updating or adding a node

Before rolling out a new digest, verify registry access or prewarm every
eligible node. Export to a regular file, not stdout (streamed exports were
truncated during this recovery despite successful process exit):

```sh
# On a node with the verified image; use the new digest when updating.
sudo env K3S_CONFIG_FILE=/dev/null k3s ctr -n k8s.io images export \
  --platform linux/amd64 /tmp/cats-image.tar \
  docker.io/alchemmist/cats@sha256:<verified-manifest-digest>
sudo tar -tf /tmp/cats-image.tar >/dev/null
sudo sha256sum /tmp/cats-image.tar
```

Transfer using authenticated SSH/SCP, compare the archive SHA-256 at the
destination, then import:

```sh
sudo env K3S_CONFIG_FILE=/dev/null k3s ctr -n k8s.io images import \
  --platform linux/amd64 /tmp/cats-image.tar
```

Use a unique staging filename/directory in real runs; do not overwrite an
existing archive. Do not print registry credentials or copy containerd stores
directly. Imports validate content digests. Update `image.digest` in
`charts/cats/values.yaml`, apply the Helm release, and verify rollout and HTTPS.
An image cached on existing nodes does not provision future nodes automatically.
