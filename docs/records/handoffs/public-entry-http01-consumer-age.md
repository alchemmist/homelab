# HTTP-01: publisher silence is not listener withdrawal

Closed timing rehearsal, not a production timeout recommendation. One isolated
Docker network, no published ports, no API credentials, no real challenge,
issuer or DNS. The tested solver-batch generator was at `bbfaf7ffc` on #636.
The same pinned Traefik and two `v1.16.2` acmesolvers used in the exact-route
rehearsals served different synthetic paths for one `.invalid` name. A third,
ordinary HTTP backend on that name returned a distinct fixed marker. The
fixture suppressed request logging, removed containers and network afterward,
and did not export tokens or response bodies.

## What changed, what was observed

Each successful sweep opened fresh HTTP connections for five requests: both
exact challenge paths, ordinary `/`, a near miss and a different Host. It
compared bodies, not just HTTP 200: the first path after withdrawal had to
return the ordinary marker and the second its own solver response. The near
miss went to the ordinary backend and the other Host returned 404.

| Condition | Successful listener observation |
| --- | --- |
| Both routes installed, no more publications | Both solver responses still available 9.48 s after baseline. This is a lower bound, not a maximum. |
| Independent fixture timer ran at the listener | First response replaced by ordinary marker; second solver and ordinary controls intact. First confirming sweep finished 1.53 s after the fixture deadline. |
| Timer process paused across deadline, Traefik left running | Both responses still available in a sweep finishing 4.62 s after deadline. The timestamp is for the sweep, not the instant of its first GET. |
| Timer resumed | First confirming withdrawal sweep finished 6.25 s after the original deadline. Second solver still served. |
| Explicit fixture reauthorization | Both original responses verified again; ordinary configuration file checksum unchanged. |

Only the disposable timer process was paused, not a controller, node, VPN or
production watchdog. It used integer seconds from `/proc/uptime` on the
listener's kernel, targeted the sampled integer plus seven, and polled about
every 150 ms. At expiry it atomically moved in a **precomputed fixture file**
without the first router; the second router never changed in the experiment.
This precomputed file must not be replayed in a live fleet: it could restore a
later-revoked second route. The file provider also takes time to apply a change.
The reported timings include polling, Docker exec and probe overhead; they do
not establish a hard maximum or continuous availability between samples.

## Design consequence

A successful LIST, a written deadline or a running listener cannot by itself
certify that an expired response is no longer served. An independent timer
helps when the publisher stalls, **not** when the timer itself stalls and the
listener keeps accepting requests. No production solver key read, TLS change
or replica-wide web/VPN fencing is justified by these results. Before choosing
a budget, test enforcing each presentation's age on the request path (including
when the enforcer is unavailable), stale generation replay, restart, clock
basis, and requests crossing the expiry boundary. Compare fresh responses and
unchanged routes independently. Public issuance and renewal remain separate.
