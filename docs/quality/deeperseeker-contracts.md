# Deeperseeker runtime contracts

The deeperseeker release (`charts/deeperseeker`, pinned image
`harbor.socrat.alchemmist.xyz/homelab/deeperseeker@sha256:696884aa...`) reads
its admin credentials and upstream API key from the environment via
`secretKeyRef`: `DEEPSEEKER_ADMIN_USER`, `DEEPSEEKER_ADMIN_PASSWORD`, and
`DEEPSEEKER_API_KEY`. The application has no file-based configuration channel
for these values; the secret is managed out of band.

Docker verification: the pinned image started as uid 1000 with read-only rootfs,
a writable /tmp and data volume. Uvicorn completed startup on :4000; the
authenticated health endpoint returned its expected non-ready 503 in the empty
fixture (no valid upstream sessions), proving the app and probes run without a
writable image filesystem. The deployment now has non-root + RO rootfs,
dropped capabilities, RuntimeDefault and /tmp emptyDir. The xray sidecar now
has TCP liveness/readiness probes on its loopback SOCKS listener :1080, and a
NetworkPolicy limits ingress to litellm and egress to the configured VPN
endpoint, public HTTPS and DNS.
