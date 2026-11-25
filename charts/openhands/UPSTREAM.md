# Upstream provenance

Vendored from OpenHands/OpenHands tag v1.43.0, helm/agent-canvas.
Official release: https://github.com/OpenHands/OpenHands/releases/tag/v1.43.0
All upstream chart files are unchanged. Local addition: templates/socrat-safety.yaml.
Overrides: deploy/openhands/values.yaml. Official public GHCR image, immutable digest;
no custom UI, host Docker socket, host paths, Kubernetes RBAC or serviceaccount token.
Canvas/Agent Server/automation execute inside a dedicated non-root container, not
on the node host. Single owner, shared container across conversations; this is not
per-conversation container isolation or a multi-user security boundary.
