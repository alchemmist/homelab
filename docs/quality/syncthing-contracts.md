# Syncthing host and endpoint contracts

The syncthing release runs a host-network file-synchronization daemon plus its
private GUI proxy.

- `syncthing-sync-0` and `syncthing-sync-1` are deliberately selector-less
  Services with explicit Endpoints: each GUI Service is pinned to the single
  node-local Syncthing device by IP, avoiding load-balancing across independent
  devices. They are Endpoints-only providers, not dangling Service selectors.
- `host-network`: the daemon binds its sync/discovery listeners on the node's
  host network, which is its intended public/private sync boundary.
- `run-as-non-root`: the hostPath `/var/syncthing` store and the host listeners
  are root-owned; the daemon needs to write that persistent state.
- `writable-host-mount`: `/var/syncthing` is the required synchronization data
  and configuration store, not arbitrary host access.
- `no-read-only-root-fs`: the private GUI sidecar copies its per-node nginx
  config into `/etc/nginx/nginx.conf` and nginx writes runtime temp/pid files,
  in addition to Syncthing's writable state; a read-only image root is therefore
  not the running contract.

The public-web-syncthing-proxy NetworkPolicy added in this pass restricts the
public GUI proxy to traefik/monitoring ingress and the two Endpoints-backed GUI
Services + DNS.
