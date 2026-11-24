# Venice browser bridge contracts

The venice-api release runs the browser bridge
`harbor.socrat.alchemmist.xyz/homelab/venice-api@sha256:614934b5...` and, in
candidate mode, the Chrome runtime
`harbor.socrat.alchemmist.xyz/homelab/venice-browser@sha256:10f6a5c1...`.

## Environment-only API key

Both `venice-api` and the `venice-browser-candidate` bridge container read
`API_KEY` from secret `venice-api-env` via `secretKeyRef`. The Python service
uses it as its bearer-token configuration; there is no file-based configuration
channel for this value. The secret is managed out of band.

## Hardening and verification

- `venice-api`: Docker run of the pinned image as uid 1000 with a read-only
  root filesystem and writable /tmp and /data completed application startup;
  GET `/` on :8080 returned HTTP 200. The deployment now uses
  `runAsNonRoot`, `readOnlyRootFilesystem`, dropped capabilities, seccomp
  RuntimeDefault, and a liveness probe on the same verified `/` endpoint.
- candidate bridge and SSH egress: liveness probes now exercise the existing
  loopback health checks; both use read-only root filesystems and drop all
  capabilities.
- candidate Chrome: its `browser-entrypoint.sh` starts Xvfb and loopback VNC
  and `browser_runtime.py` keeps a persistent browser profile on the PVC. The
  pinned image is intentionally launched without `--no-sandbox`. A local amd64
  Docker attempt could not verify strict read-only hardening because the Chrome
  setuid sandbox exited prematurely under the host's qemu emulation; this is not
  treated as proof that the cluster cannot run it. The candidate therefore keeps
  its existing writable filesystem as a separately evidenced image-runtime
  contract rather than claiming an unverified hardening change.

NetworkPolicies isolate the main API to litellm on its service port; the
candidate already has its own policy with no public listener by default.
