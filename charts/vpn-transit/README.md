# Moscow private relay rehearsal

Bare chart defaults render only the existing host-network Deployment. The
production Application enables `podRehearsal`, which renders a second Pod on socrat-4 and a ClusterIP Service
`vpn-transit.vpn-transit.svc`. The Service selects only that Pod. Its config
contains fixed destinations, not client profiles. It must not mount the host
configuration or request host sockets. No change to DNS, NL ACLs, the public
port owner or the native watchdog is part of this stage.

Review the opt-in render offline with `helm template vpn-transit charts/vpn-transit
-n vpn-transit --set podRehearsal=true` (one command). Do not enable it until
socrat-4 has capacity for both replicas and the private Moscow Traefik, the
local relay image is available, and NetworkPolicy enforcement is confirmed.
The future private Traefik Pod must match both selectors in the policy.
Observe the source address at NL and verify authenticated TCP **and UDP** via
the private path; a successful connect probe is not acceptance. Do not widen
NL ACLs if Pod egress identity differs. Keep the old path throughout rehearsal.

The config is immutable. Before changing a deployed rehearsal config, retire
the rehearsal resources explicitly and verify their deletion: the production
Application does not automatically prune. Never delete the legacy Deployment
as part of rehearsal cleanup. Public port handover is a separate fenced window.

## Prepare the public owner's release and return (offline only)

The Application keeps `legacyPortOwner: serving` via chart defaults. In a future
approved handoff, `legacyPortOwner: parked` declares **zero replicas on the old
host-network Deployment only**; the Pod-network relay must still have one replica.
Do not use the shared `replicas: 0`, delete a Deployment, or rely on prune.
Parking is a desired state, not proof that the node has released any sockets.

Before allowing this change in GitOps: verify authenticated profiles on the
private path, prepare and review both Applications' rollback revisions, fence
the native watchdog and automated reconciliation (including parent and in-flight
syncs) as specified in the [handoff plan](../../docs/plans/independent-public-ingress.md).
Confirm the private Service has a Ready endpoint. With the old owner parked, wait
for its Pod to terminate; verify TCP 80/443/32053/32083/32084 and UDP
443/32085/32086 are free before enabling a new host-level listener. The chart
neither performs these checks nor activates a public Traefik.

Rollback keeps the Pod-network relay available: first stop the new public
listener, confirm its ports are free, then restore `legacyPortOwner: serving`
with one replica. Verify old socket ownership and real client traffic before
restoring reconciliation and watchdog policy. Never run two public owners at once.
