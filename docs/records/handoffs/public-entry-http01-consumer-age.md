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

## Request-path age gate, including an in-flight response

A separate internal-network fixture put a loopback HTTP gate between **both**
exact solver routes and their two pinned real acmesolvers. Neither route had a
direct fallback. Ordinary traffic still used its separate backend. The gate
had an initially empty in-memory table indexed by exact Host and path; a
fixture-only control armed it once with deadlines from the gate's own
monotonic clock (7 s and 120 s). There was no renewal or subsequent publication.
It checked the deadline before opening an upstream connection, bounded and
verified the synthetic upstream body, then checked time again before starting
the downstream response. No token, payload or request log was exported.

| Probe | Listener result and control |
| --- | --- |
| Cold, before arming | 410 on both exact paths; no backend fetches. |
| Immediately after arming | 200 and the correct distinct bodies, one fetch per solver. |
| First response held in the gate after a successful backend read, then released after its deadline | 410, without the buffered solver response. Checking age only before the fetch would miss this boundary. |
| Two fresh sweeps after the first deadline | 410/200 each time. Backend fetch counts changed from 2/2 to 2/3 between sweeps: no new request reached the expired solver. |
| Gate stopped, Traefik and both solvers still running | Both exact paths returned 502 without solver bodies. The ordinary root and near miss still returned their ordinary marker; the wrong Host remained 404. |

The ordinary provider file stayed byte-identical; the disposable containers
and network were removed. This distinguishes **suppression of an expired
answer** from **withdrawal of the router**: the gate returned 410 rather than
routing the exact path to the ordinary backend. Loss of this shared fixture
gate sacrificed availability of the other challenge as well. It did not take
down the ordinary site. This deliberately limited gate is not deployed code.

These results do not establish a hard deadline for bytes already written to
a socket, a client that reads slowly, or a process suspended *after* its last
time check. No persisted leases were trusted or replayed. A real design must
also bind renewals to a current generation and fresh completed observations,
reject replay across restart, define the clock domain and fail behavior, and
measure the cost of an unavailable gate. The fixture's 7/120 s values are
not certificate renewal or production availability budgets.
