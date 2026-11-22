# Remark42 manifest findings and remaining decisions

The chart now disables automatic ServiceAccount token injection (the application
has no Kubernetes API requirement) and uses the upstream `/ping` endpoint for
both liveness and readiness. Offline Helm-render tests assert those settings and
that existing data, CSS, Service and host placement contracts remain unchanged.

The other findings require owner input or runtime evidence and are deliberately
not papered over:

- `hostNetwork`: retain it for now. Decide whether the pod can use ordinary
  cluster networking while preserving its required reachability from clients
  over the `socrat-2` WireGuard/node address. Approval must include testing
  ingress, blog/OAuth callback reachability and Telegram notification delivery
  from a disposable/candidate deployment before changing the network mode.
- Writable host mounts: `/srv/remark42` holds the comments/data and custom CSS.
  A supported copy/restore plan must preserve comments, ownership/permissions and
  CSS before replacing hostPath. Do not relocate or mutate live data as part of
  this manifest change.
- Read-only root filesystem and non-root execution: first confirm the pinned
  upstream image's numeric UID and all runtime write paths (including temp,
  cache and any generated files); then provide writable ephemeral mounts and
  verify startup, comment operations, OAuth and Telegram behavior with positive
  and negative tests. No guessed UID or writable-path exception is introduced.
- Isolated network policy: define actual ingress/egress peer identities and
  prove required DNS, ingress, OAuth and Telegram flows plus denial of unrelated
  traffic before adding policy.

These residual decisions do not weaken the shared lint gate or suppress findings.
