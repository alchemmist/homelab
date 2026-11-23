# NetBird image-level contracts (registrable findings)

Consumer release target: `netbird-0` (`deploy/argocd/apps/netbird.yaml`,
manifests in `deploy/netbird/values.yaml`, images pinned by digest there).
This document is the per-object evidence for the registry entries in
`ci/quality/providers/netbird-vpn.yaml`. Every contract below is an
image-level requirement of the pinned upstream image, verified from the image
filesystem/entrypoint or by running the pinned image in Docker; none can be
satisfied by editing the manifest without forking upstream images.

## WireGuard machine peers: `machine-socrat-0`, `machine-socrat-1`,
## `machine-socrat-2`, `machine-socrat-3` (netbird-host-peers), `machine-socrat-5` (netbird-host-peers)

Image: `netbirdio/netbird:0.83.2@sha256:a2f6a659...` (entrypoint
`/usr/local/bin/netbird-entrypoint.sh`, binary `usr/local/bin/netbird`).

- `host-network`: the peer is a host/bare-metal gateway: it terminates
  WireGuard on the node address (`NB_HOSTNAME=machine-socrat-N`, hostNetwork
  true is the whole purpose of a host peer: interface `nb-host` must be
  placed directly into the node network namespace). The node firewall is the
  real boundary; cluster policies cannot apply (see the hostNetwork stance in
  `docs/quality/traefik-edge-vpn-backends.md` and `ci/quality/charts.py`,
  HOST_BOUNDARY_KINDS).
- `run-as-non-root` / `drop-net-raw-capability` / `writable-host-mount`
  (`machine-socrat-0..3` only): the binary has no file capabilities (image
  tar shows mode 0755 and no `security.capability` pax header), so the
  NET_ADMIN/NET_RAW/BPF set required to create and drive the kernel
  `nb-host`/tun interface can only be effective for uid 0; `/dev/net/tun`
  (hostPath CharDevice) is the kernel tun device the interface is built on.
  Caps are explicit and narrowed (drop ALL, add exactly NET_ADMIN, NET_RAW,
  BPF), privilege escalation disabled, seccomp RuntimeDefault.
  `machine-socrat-5` renders without the tun device (kernel-interface
  provisioning on that node comes up differently) and has no hostPath mount.

Peer runtime write surface is otherwise read-only (this release's fix, commit
`46dd6da90`): identity lives on the `machine-socrat-N`/`machine-socrat-N-state`
PVCs (`active_profile.json`, `default.json`, verified in Docker), `/var/run`
(socket) and `/var/log/netbird` are emptyDirs.

## STUN daemon: `stun` (netbird-pilot)

Image: `coturn/coturn:4.7.0@sha256:a00afb5b...` — coturn is a UDP STUN
daemon whose whole function is to listen on the node address on UDP 3478
(`--listening-ip=109.120.141.60`, hostNetwork true); client-visible socket
identity requires the node network namespace. The rest of the coturn
hardening is in the manifest: uid 65534, drop ALL + NET_BIND_SERVICE only,
read-only filesystem with a 1 MiB /tmp emptyDir (Docker-verified).

## NetBird management/dashboard: `server`, `dashboard` (netbird-pilot)

- `server` (`netbirdio/netbird-server:0.83.2`, entrypoint
  `/go/bin/netbird-server --config /etc/netbird/config.yaml`): the management
  gRPC/HTTP service binds port 80 (`containerPort: 80` is wired all the way
  through the edge forwarder's traefik routers
  `http://server.netbird-pilot.svc.cluster.local:80`, see the
  `netbird-edge-forwarder` ConfigMap `dynamic.yaml` in
  `deploy/netbird/values.yaml`); a non-root process cannot bind it (no file
  capabilities on the image), and the server keeps Sqlite/management state
  under `/var/lib/netbird` while Java/log rotation paths on the root
  filesystem are written at runtime.
- `dashboard` (`netbirdio/dashboard@sha256:3e8a714e...`, entrypoint
  `/usr/bin/supervisord -c /etc/supervisord.conf`): the image's
  `etc/supervisord.conf` mandates `user=root` for supervisor, the nginx master
  and the `init_cert` certbot program; nginx listens on port 80
  (`containerPort: 80`, reachable as `dashboard.netbird-pilot:80` from the
  forwarder ConfigMap `dynamic.yaml`). Docker-verified: the pinned image
  serves HTTP 200 on port 80 with the release's env, and the entrypoint
  mutates `/etc/nginx` config templates at startup (`init_cert` program,
  "Reloaded nginx to apply updated CSP configuration"), so the root
  filesystem cannot be read-only and supervisord cannot run as non-root.

## Relays: `netbird-relay-home`, `netbird-relay-vps` (identity)

Image: `netbirdio/relay:0.83.2@sha256:1b27bbad...` — same env contract class
as the gatus DSN case (`docs/quality/uptime-kuma-gatus-followup.md`): the
upstream relay binary reads the Ha relay auth secret exclusively from the
`NB_AUTH_SECRET` environment variable (`deploy/netbird/values.yaml`,
containers `env` entry `NB_AUTH_SECRET` -> `secretKeyRef`
`netbird-relay-home-auth`/`netbird-relay-vps-auth`), and there is no
file/flag alternative in the pinned image, so `env-value-from` and
`read-secret-from-env-var` cannot be removed from the manifest. All other
relay hardening is manifest-native: uid 65532, runAsNonRoot, drop ALL,
read-only filesystem (Docker-verified upstream).
