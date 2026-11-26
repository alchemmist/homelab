# Moscow private relay rehearsal

The production values render only the existing host-network Deployment. The
opt-in `podRehearsal` renders a second Pod on socrat-4 and a ClusterIP Service
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
