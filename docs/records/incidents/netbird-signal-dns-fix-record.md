# NetBird macOS initial connection: Signal proxy and DNS repair

Date: 2026-11-03. Actual deployment and CLI verification; not full pilot acceptance.

## Evidence and diagnosis

- Real owner Authentik authentication admitted and registered one Darwin 0.82.0
  peer. No pending approval or expired login. No machines enrolled by automation.
- Local daemon's minimal Status answered `Connecting`, while full CLI status
  waited. Restarting the system daemon did not fix it. This was not proof of a
  daemon deadlock: engine initialization was waiting for Signal registration.
- Owner supplied a private mode-0600 local copy of the root-owned log. Repeated
  errors were `no registration header from the Signal server within 10s`.
  Tokens, authentication links, raw logs and diagnostic bundles are not published.
- Unary native gRPC GetServerKey succeeded over trusted TLS through both public
  entrances. That was insufficient to validate a bidirectional Signal stream.
- Synthetic header-only, open-request-side ConnectStream probes timed out through
  both entrances (6-second deadline), but succeeded directly at the server (~81ms)
  and at the scoped forwarder's h2c entrypoint (~265ms).
- Traefik 3.7.13's Kubernetes Ingress provider reads backend scheme via
  `parseServiceConfig(service.Annotations)`. The old renderer incorrectly put
  `service.serversscheme=h2c` on **Ingress**. The outer hop therefore used HTTP/1.1,
  causing the open-request-side Signal header handshake to stall.

## Narrow deployed fix

Created only `identity/netbird-edge-forwarder-grpc`, selecting the existing
forwarder pods, port 8082, with the h2c annotation on the **Service**. Changed only
`identity/netbird-grpc` backend references and removed its ineffective scheme
annotation. Applied under exact Ingress/old Service UID and resourceVersion
checks with private exclusive before/complete journals. Existing REST/WebSocket
Service spec unchanged; no Deployments restarted, global Traefik watch/RBAC,
runtime Secret, providers, human identities, policies or setup keys changed.

Both native header-only Signal probes subsequently passed (~0.10s / ~0.37s).
`netbird-signal-check.py` now provides a bounded trusted-TLS regression probe,
using ephemeral Signal identifiers only, no request DATA, no management peers or
credentials, and deterministic cancellation. It requires `grpcio` locally.

## Separate DNS regression caught by clean reconnect

A clean local down/up flushed the old DNS cache and exposed public NXDOMAIN.
Google and Cloudflare recursive answers both returned status 3. All three host
renderers had the pre-NetBird hash and lacked the approved `netbird.socrat`
entry, although the concurrent `bot.socrat` entry was present. Current main also
lacked NetBird. The exact actor/deployment causing replacement was not established.

- Added only the NetBird failover name to **current-main-based** source in an
  isolated worktree; added regression coverage including preservation of Bot.
- Commit `0eb93c9` was fast-forwarded into the local main worktree. A concurrent
  dirty Argo values file was preserved byte-for-byte. No push is claimed here.
- Captured private mode-0600 originals on socrat-0/1/2. Three bounded installer
  Jobs atomically inserted only that line under fresh per-host SHA guards; no
  broad renderer replay, DNS/IdP/VPN restarts, host PID, chroot or sudo changes.
- Before SHA256: `bac6858f7c232a293cb5b55f26fc15c2cf0319abfe1b9fad275e864750e0e6c6`.
  After: `aebdbbb112f589e1c92fb8e15c4b7bb8d3648b976d9263f2a0c651c01e79999d`.
- Normal existing timers reloaded DNS. Both public authoritative entrances now
  return NOERROR and both approved A addresses; all three renderers retain Bot.

## Final actual result and boundaries

After macOS resolution recovered, ordinary **`netbird up` exited 0: Connected**.
Full JSON status now completes: daemon Connected, management and Signal connected
without errors, relay 1/1 available. Independent native management API readback
confirms exactly one owner peer, connected=true, approval_required=false,
login_expired=false; policies=0, setup keys=0. Server-side verification used an
in-memory address override while its resolver cache lagged; trusted CA/hostname
verification stayed enabled. No persistent hosts/DNS override was installed.

The existing inter-node WireGuard was not disabled or reconfigured. This proves
actual initial client connection, not personal GUI acceptance or Grafana/SSH
reachability. No destination machine peers/policies exist yet; zero remote peers
is expected default-deny behavior. Ownership transfer, narrow service access,
revocation/session/outage tests and old-VPN retirement remain separate work.
