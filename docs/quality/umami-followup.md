# Umami manifest findings: remaining owner decisions

PR #494 added the `/api/heartbeat` liveness probe to the Umami Deployment. The
existing readiness endpoint and polling cadence remain unchanged. The remaining
Umami findings are intentionally not cleared by guessed identity, filesystem,
network, credential, or resource settings.

Before restricting the workload, obtain and review:

- **Identity and API token:** numeric UID/GID and startup behavior from the exact
  pinned image; confirm whether it needs a Kubernetes API token. Only then decide
  whether to set a non-root pod identity and disable service-account token
  automount. Do not infer the UID from the image's `nextjs` username.
- **Writable paths:** runtime evidence or upstream documentation for every path
  Umami writes, including temporary/cache paths and any startup-generated files.
  A read-only root filesystem needs explicit writable mounts and restart tests.
- **Database credentials:** supported file-based PostgreSQL credential input,
  renewal/rotation behavior, and successful reconnection after rotation for the
  `pg-common` credential. The current `umami-pg-common` Secret reference and
  `umami-env` external Secret must remain intact until that contract is verified.
  Do not copy credentials into Helm values or create an empty Secret.
- **Network isolation:** identify actual tracker-ingestion clients, public
  ingress path, PostgreSQL service, DNS and health-check sources. Test required
  tracking/DB flows and denied unrelated clients before adding a policy; do not
  assume selectors or create default-deny rules with guessed peers.
- **Resource requests:** measured startup and steady-state CPU/memory floors for
  this pinned image under representative analytics load. Do not copy limits or
  invent request values.

These are evidence/owner decisions, not waivers or authorization to mutate the
live service. Until then, retain the existing identity, secret delivery, writable
filesystem, network reachability, and resource behavior. No live-cluster test or
credential operation is part of this offline change.
