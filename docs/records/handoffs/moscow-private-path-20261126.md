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

## Follow-up: UDP source observation and isolated authentication

On 26 November the private Traefik Service and both relays were Ready. A
short-lived tokenless probe on socrat-4 sent small synthetic datagrams to the
**private frontend**, not the relay IP or public entrance. NL conntrack was
sampled read-only for UDP flows to 10.250.0.2:32085/32086 from 10.250.0.40.
Only aggregate differences are reported; no packet capture or profile was used.

| Probe | New matching tuples on 32085 | On 32086 |
| --- | ---: | ---: |
| Allowed, two UDP sockets to 32085 | 2 | 0 |
| Allowed, three sockets to 32086, single snapshot | 0 | 2 |
| Denied, two sockets to 32086 | 0 | 0 |
| Same Pod relabeled allowed, two sockets to 32086 | 0 | 2 |

These are concurrent flow observations, not packet delivery percentages. The
repeat with the label change supports the expected source identity on the UDP
path. There was no verified reply, VPN handshake or authenticated payload in
this exercise. An extra repeat on 32085 timed out in the harness and was not
counted. Probe Pods were removed; no NL access rules or listeners changed.

Separately, a disposable 3x-ui 3.11.0 Pod with a fresh database, no Service,
no host networking and deny-all network policy was tested on socrat-1. A new
short-lived Shadowsocks identity was created via its native API. The fixture
allowed only the local echo test destination for the test route. Authenticated
TCP and UDP payloads matched the nonce; a wrong credential failed both, the
correct credential passed again, and neither worked after native client removal.
The namespace was removed. This was not the Moscow/NL topology and did not use
production clients, keys or panel state. In particular it is not acceptance of
production WireGuard or AmneziaWG. Do not combine the independent fixture and
one-way flow observations into an end-to-end pass or a public cutover decision.
