# Mac: NetBird internal access alongside Tunnelblick

## Current operating state (verified 2026-11-06)

**NetBird is the primary homelab client. Tunnelblick stays connected.** The
standalone `wg-socrat-admin` profile is retained as a disconnected recovery option,
not used to claim NetBird acceptance. Do not silently replace NetBird with it.

The NetBird daemon profile persists these effective settings:

- `disableDns: true`: do not replace or manage the Mac's DNS.
- `disableClientRoutes: false`: accept the selected internal resources.
- `disableServerRoutes: true`: this Mac is a client, not a routing peer.
- Explicit selected networks: `wg-socrat-0`, `wg-socrat-1`, `wg-socrat-2`,
  `wg-socrat-3`. Do **not** select `all`, which also accepts future resources.

These resources are precisely `10.250.0.1/32`, `.3/32`, `.2/32`, `.5/32`.
No exit node, default route or LAN-wide route is needed. Ordinary SSH aliases
remain internal IPs on port 2222 with retained pinned keys and `ProxyJump none`.

## Why disable DNS

The active Tunnelblick profile monitors DNS, restores primary DNS changes and
restarts on other DNS changes. NetBird had DNS management enabled. This is a
plausible conflict mechanism, **not a reproduced causal proof**: do not deliberately
break a required Tunnelblick connection to establish it.

The standalone WireGuard profile does not set DNS and has narrow host routes,
which explains why its configuration has less opportunity to interfere. NetBird
can operate in that same limited role. DNS management is not required for SSH
aliases whose `HostName` is already an IP.

Leave Tunnelblick's configuration and monitoring alone. Existing split resolver
files are separate owners; do not delete them or claim NetBird manages them when
its DNS handling is disabled. If new homelab DNS is needed, design scoped
resolution separately rather than replacing Tunnelblick's global DNS.

## Changing settings safely

Before acting, record the OpenVPN process identity, internet route gateway/interface,
primary resolver and restart/start counts. Never print corporate profiles,
authentication links, private keys or raw diagnostic bundles.

For this NetBird version (0.82.0), an `up` command while already connected did not
apply changed flags. Check `netbird debug config` privately, emitting only selected
non-secret booleans. If a change is required, reconnect **only NetBird**, not
Tunnelblick:

```sh
netbird down
netbird up --disable-dns --disable-client-routes=false --disable-server-routes
netbird networks select wg-socrat-0 wg-socrat-1 wg-socrat-2 wg-socrat-3
```

Confirm effective settings after connection; a zero exit status is not proof of
configuration change. Preserve the existing daemon identity and enrollment.
Do not run login/deregister or rotate keys to fix routes. If authentication is
required, hand login to the operator without exposing SSO links/tokens.

For an initially unknown route inventory, connect with `--disable-client-routes`
temporarily, inspect available resources, explicitly select only the four allowed
resources, then reconnect with client routes enabled. Do not install unknown exit
routes for the sake of discovery.

Do not run the standalone WireGuard and NetBird simultaneously for the same four
host routes during acceptance: overlapping `/32` routes can mask a broken path.
Stop **only** `wg-socrat-admin` once NetBird is connected and ready; leave the
unrelated Tunnelblick/OpenVPN connection untouched. Allow NetBird's route/peer
synchronization to complete before testing. If NetBird does not become usable,
restore the known recovery profile; do not change SSH to public addresses or add
an SSH bastion.

## Acceptance evidence

- NetBird management and signal connected; 4/4 peers connected; zero DNS groups.
- `wg-socrat-admin` disconnected. All four `route -n get` results use `utun100`
  (the verified NetBird interface on this machine; don't assume that name elsewhere).
- Twelve new SSH connections, three per node, succeeded using ordinary aliases,
  multiplexing disabled, internal destination/port and no SSH jump. Server source
  was not the standalone WireGuard client `.4`. Existing NetBird routing-peer
  masquerade is expected; do not demand the standalone WireGuard source identity.
- Tunnelblick's OpenVPN PID unchanged; its current log still had one completed
  initialization and no `SIGUSR1` restart; both sampled internet routes unchanged.
  Primary DNS matches the VPN server's pushed DNS.
- The **full** `scutil --dns` dump hash differs from the baseline where standalone
  WireGuard was active. Do not claim byte-identical system DNS output after
  removing an interface; distinguish primary VPN DNS from interface-scoped state.

This proves the observed concurrent session, not indefinite future compatibility
or application-level acceptance of every corporate service. Do not change VPN
monitoring, routing policy or session lifetimes without separate need.

Private local evidence is in `/tmp/netbird-tunnelblick-safe/`; keep it private.
The daemon also created a local root-owned mode-0600 anonymized debug archive;
it was not uploaded or read by the unprivileged session. No Tunnelblick service,
process, profile, preference or DNS policy was deliberately changed.
