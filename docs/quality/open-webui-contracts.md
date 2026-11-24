# Open WebUI image contracts

The open-webui release (`charts/open-webui`, image
`ghcr.io/open-webui/open-webui:v0.12.3-slim@sha256:5adfb035...`, namespace
llm) runs the upstream Open WebUI server, which by upstream design manages its
static assets and runtime secret from inside the container.

## Root + writable rootfs

`/app/backend/start.sh` and the running app write static asset files
(`/app/backend/open_webui/static/{favicon.png,web-app-manifest-*.png,splash.png,
loader.js,user.png,...}`) at startup. Those paths live in the image's root
filesystem and are owned by root (uid 0), so:
- a read-only root filesystem fails with `Read-only file system: ...
  /app/backend/open_webui/static/favicon.png` (Docker-verified), and
- a non-root uid cannot write the root-owned static dir (Docker-verified:
  `Permission denied: ... /app/backend/open_webui/static/...`).

The writable/static-dir requirement is an upstream image contract, not a
manifest choice. The writable PVC is `/app/backend/data` (database + uploads);
the static writes target the image root and are unavoidable. This mirrors the
established harbor/netbird image-contract registrations.

## Env-only runtime secrets

The main `open-webui` container reads runtime credentials from the environment
via `secretKeyRef`:
- `DATABASE_URL` (secret open-webui-postgres) - the postgres connection string,
- `OPENAI_API_KEY` (the configured LLM upstream api key secret),
- `WEBUI_SECRET_KEY` (the auth secret, consumed to skip the start.sh generation
  that would otherwise write `.webui_secret_key` into the read-only CWD).

The image has no file-based configuration channel for these values; the
environment is the application contract (same class as the litellm/harbor/
grafana env-only registrations).

## Gateway (nginx reverse-proxy, hostNetwork)

The `open-webui-gateway` Deployment runs nginx:1.28-alpine. In this pass it was
hardened to run as non-root (uid 101), all capabilities dropped, read-only root
filesystem, with pod `fsGroup: 101` and dedicated emptyDir mounts for the nginx
temp paths (`/var/cache/nginx`, `/run` pid, `/tmp`). Docker-verified: nginx
serves HTTP 200 on the gateway port (18080, > 1024) under `--read-only --user
101:101` with those writable mounts. The gateway keeps `hostNetwork: true`
because it binds the host address 10.250.0.1:18080 on a specific node; that is
the registrable host-network contract.

## Isolation

NetworkPolicies scope the open-webui server (ingress :8080 from edge traefik,
egress postgres/DNS + the gateway) and the gateway (host-network pod; the node
firewall owns its boundary).
