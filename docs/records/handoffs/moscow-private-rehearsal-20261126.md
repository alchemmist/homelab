# Private Moscow ingress rehearsal: preflight, 26 November 2026

**Decision: hold both opt-ins.** At 10:52 UTC both Applications were Synced and
Healthy, but the Moscow controller had no Pod and the relay had no rehearsal
Service. Healthy here means the disabled state reconciled. The original relay
remained Ready, with k3s-agent active and the native relay inactive.

| Memory on socrat-4 | Snapshot |
| --- | ---: |
| Kubernetes allocatable | 335192 Ki (327 Mi) |
| Current Pod requests / limits | 96 / 288 Mi |
| Additional private pair requests / limits | 112 / 384 Mi |
| Overlap total requests / limits | 208 / 672 Mi |
| Host MemAvailable | 357616 Ki (349 Mi) |

Requests fit; limits are not reservations. The private pair alone could consume
more than current host MemAvailable, and the node has a configured 128 Mi eviction
threshold. No current MemoryPressure does not establish safety under load. Do not
lower kube/system reserves, disable fencing, or drop live VPN to make room.
Prefer a Moscow VM RAM increase (e.g. to 2 GiB), then repeat the inventory after
boot and verify the existing VPN before any rehearsal. An increase is not itself
acceptance. No resize or reboot was performed.

The worker reported the node-local relay image. The API did not list the pinned
Traefik image on that worker; this neither proves it is absent nor that a pull
will succeed. A request from the Moscow **host** directly to the blog ClusterIP
with its Host header returned 200 (12 ms); the blog Certificate reported Ready.
This checked neither the future Pod path, trusted TLS at Moscow, nor NetworkPolicy.

After capacity review and private activation, get the actual `traefik-moscow`
ClusterIP from its Service. From the labeled probe Pod with Python 3 and a trusted
CA bundle, run `python3 check-moscow-private-blog.py <service-ip>` using the
[repository client](../../../scripts/check-moscow-private-blog.py). It connects to that
IP without a proxy or public DNS, checks SNI, certificate chain, hostname and blog
content for both names, and prints no response body. Use an outer 30-second
timeout. Repeat from an unlabeled Pod: confirm connection denial, not a TLS or
content failure, and repeat the positive control. Use authorized profiles for the
separate TCP and UDP tests; verify the observed source at NL without logging
credentials. DNS and all public listeners stay unchanged throughout.
