# Moscow private rehearsal: live application path, 26 November 2026

**Partial acceptance, no public handoff.** Argo reconciled #593 at `2dcb0366b`
without a manual sync. Both Applications were Synced/Healthy. The private
Traefik and Pod-network relay were Ready on socrat-4. The relay Service endpoint
pointed only at `vpn-transit-rehearsal`; the original host-network Deployment
remained Ready. The tests below used the private ClusterIP, not Moscow's public IP.

## Controls on the actual workloads (13:14–13:18 UTC)

Two short-lived non-root Pods without API credentials ran the repository blog
probe in the `traefik-moscow` namespace, on socrat-4 and socrat-1 respectively.
For each source, both `alchemmist.xyz` and `www.alchemmist.xyz` passed hostname,
CA chain, HTTP status and expected content checks. Setting that same Pod's
`homelab.alchemmist.xyz/moscow-probe` label to `false` resulted in TCP refusal
by the private frontend. Restoring `true` restored trusted HTTPS for both names.
Neither authorized web probe could connect directly to TCP/443 on the relay
Service. These are live TCP controls, not a test of every protocol or identity.

With `vpn.alchemmist.xyz` as SNI the private frontend completed trusted TLS 1.3.
Two short controlled TCP connections to its dedicated port 32083 were held while
observing established sockets at 10.250.0.2:32083 on NL. Two new peer tuples
from Moscow's 10.250.0.40 were present during the hold and absent before and
after. This supports preserved source identity for this TCP path; it does not
prove UDP source identity or authenticated forwarding. No profile or credential
was used. The probes were deleted; neither DNS nor public ports were modified.

## Still required

- Run authorized real TCP and UDP profiles from a permitted private client against
  the rehearsal Service, retaining the profile's actual SNI, and demonstrate
  payload transfer. Use protected local credentials; do not commit or paste them.
  Ordinary `kubectl port-forward` is not a UDP test. Confirm the observed UDP
  peer at NL during the controlled session; keep NL access restrictions intact.
- Characterize any existing ambiguous TCP/443 or raw TCP/80 profiles and migrate
  them before considering the fenced public-port handoff. The operator's earlier
  confirmation concerned the old **public** path, not this private path.
- The blog check is not an all-service or DNS-failover result. Do not advertise
  Moscow for ordinary hostnames or declare a survivor scenario passed from it.
