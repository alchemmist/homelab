# Rollback

Disconnect the managed WireGuard profile before changing its DNS configuration.
Restore the previous profile from a private backup if needed; never regenerate
its keys as part of DNS rollback.

For split DNS, restore the previous `/etc/resolver/socrat.alchemmist.xyz` file
if one existed. Remove that managed file only when explicitly retiring this
configuration. Existing per-host resolvers are preserved by deployment and
must be reviewed separately. Leave unrelated resolver files and
`/etc/resolv.conf` unchanged.

For system DNS, restore the previous profile's DNS field and reimport or edit
it in the WireGuard application, then reconnect. The generated file alone does
not update an already imported tunnel.

Removing DNS configuration does not revoke network access. Remove the Mac peer
from each node separately only when intentionally decommissioning that client.
