# Private ingress: named TLS source rehearsal, 2026-11-26

**Decision boundary:** a Traefik 3.7.19 process can serve and rotate a TLS
certificate without a Kubernetes API token or collection access to Secrets.
This was a synthetic cross-namespace experiment, not an installation of the
web stage and not a test using a production key. No public traffic was moved.

## What ran

Each run used two disposable namespaces. One held a freshly generated, short-lived
TLS Secret for `tls-proof.invalid` plus an unrelated Secret. The other held a
single non-root, tokenless-by-default Pod on `socrat-1`. There was no Service,
host networking, public port or persistent volume. NetworkPolicy denied ingress
and limited egress to the Kubernetes API. Only the source container mounted a
short-lived projected service account token. The cross-namespace RoleBinding
allowed exactly `get` on the one named fixture Secret. Access reviews returned
no for `get` on the unrelated name, `list` and `watch`. The successful reads
and handshakes also exercised the granted path; the negative access reviews
were not attempts to retrieve any real application data.

The source container used the API's namespaced GET endpoint over verified HTTPS.
It served an in-memory dynamic configuration to Traefik's stock HTTP provider
on loopback, with a single exact host, an inert internal service and inline TLS
material. Traefik listened on another loopback port and polled every two seconds.
No PEM, token or provider response belongs in a log, evidence file or repository.
An exec-capable principal or another container in the Pod could access loopback;
this is a key-bearing trust boundary, not a multi-tenant API.

## Observations on fresh TLS connections

| Operation | Result |
| --- | --- |
| Start with synthetic leaf A | Trusted handshake for the fixture name, exact SHA-256 leaf fingerprint matched. |
| Replace the same Secret with independently generated leaf B | New handshake matched B without restarting the Pod. Old trust anchor and wrong hostname both failed verification. |
| Remove the RoleBinding; try a source implementation that emits an empty HTTP/TLS configuration on 403/404 | The old certificate was still accepted during the bounded observation. Do not treat an empty snapshot, a failed poll or an API error as proof of withdrawal. |
| Repeat with an explicit nonempty withdrawal configuration | On denial the source emitted a snapshot with no certificates, a sentinel router for a different invalid hostname and strict default SNI. A new fixture-name TLS connection no longer verified. |
| Restore the RoleBinding on the same Pod, then delete the fixture Secret | The exact current leaf returned after restoration; after deletion the source again emitted the withdrawal snapshot and the fixture-name TLS check failed. |

The successful withdrawal test confirmed the source actually returned the
withdrawal snapshot before testing the peer. It did not establish which one
of the snapshot differences was sufficient, nor invalidate already-established
connections. All temporary Pods, permissions and synthetic keys were removed
with their namespaces. No production Secret was read for this experiment.

## Two sources and a multi-name certificate

Two further disposable runs used two independent source Secrets and separate
single-name `get` Roles/RoleBindings. One synthetic leaf covered one name;
the other covered two. The loopback HTTP provider returned one strict-SNI
snapshot, omitting only a source whose named read returned 403 or 404. A local
fixture backend returned a distinct expected body for each Host. The checks
used fresh trusted TLS connections, exact leaf fingerprints, HTTP 200 and
body equality; an HTTP error was not counted as successful withdrawal.

- Revoking the first binding caused that hostname to be rejected during TLS
  negotiation (unrecognized SNI). The other hostname and alias continued to
  serve the exact original certificate and their own HTTP bodies.
- Restoring the binding restored the first route without a restart. Rotation
  then served the replacement leaf and rejected the old trust anchor.
- In the second run, replacing the first source with a certificate and an
  unrelated private key failed closed for that name. Replacing it with the
  valid pair restored it. Deletion again withdrew only that source.
- Repeated fresh probes of the unaffected names during these transitions
  passed 16/16 in the first run and 22/22 in the second. This is sampled
  availability, not a guarantee that no connection could have failed.
- Revoking the second binding finally rejected **both** names on its SAN list.

Neither business middleware nor real application authorization was exercised.
All certificate material was disposable; the real Schoolbot key was not read.

## Control-plane loss is not explicit revocation

The next runs isolated *only* the disposable reader namespace. No real API
server, node network, ingress controller or VPN was stopped. The fixture
backend continued on loopback. The operator replaced the first synthetic
Secret through a separate API connection after confirming the fault.

| Injected fault | Evidence on fresh TLS + HTTP connections | After restoring the source |
| --- | --- | --- |
| Removed API egress in the fixture policy; the HTTP provider endpoint returned 503 | 10/10 alternating original-first/unchanged-alias samples passed over 15.1 s after rotation. Trust in the replacement alone did not work. | Verified replacement leaf and expected body, unaffected alias and rejection of the old trust anchor within 10.6 s of beginning recovery checks. |
| Stopped only the fixture HTTP configuration listener; confirmed connection refused, while backend kept serving | Same 10/10 result over 14.6 s, including the old leaf on the rotated name. | Same recovery checks completed in 7.2 s. |

In a separate API-isolation run a **new** Pod with the same spec had a listening
TCP socket but could not establish trusted TLS for either the previous or new
certificate. The warm Pod still served the old configuration. After restoring
only the fixture egress, both Pods served the replacement leaf and expected
HTTP body. An open socket is not a suitable cold-start acceptance check.

These are observation windows and sampled recovery times, not expiration bounds
or reliability targets. Those runs had no freshness lease. The default HTTP
provider retaining its last snapshot preserves availability but can also retain
a rotated or revoked key while disconnected. A producer-only timeout cannot
withdraw a snapshot from an unreachable consumer. A production design must
separately address cold start, validity under a control-plane partition and
what actually stops *new* client connections when a freshness limit expires;
readiness alone does not fence a host-bound listener. Do not fence VPN traffic
as a side effect of a web/TLS freshness check.

## Listener-side fence experiment (not a production policy)

A separate disposable run used an **eight-second experimental freshness
lease** and the same two synthetic keys. The local source atomically refreshed
an in-memory timestamp on producing a successful config response; no key was
written to that shared volume. A supervisor in the tokenless Traefik container
read the timestamp and stopped only its private web listener after expiry. It
checked source freshness before starting a new process. There was no VPN
listener, host port or public Service in this experiment.

- With API egress denied, and independently with the source HTTP listener
  stopped, we rotated the first fixture key out of band. Unlike the unfenced
  runs, actual fresh TCP connects were refused. Three repeat connects also
  failed. From the start of checking after fault confirmation and rotation,
  the observations including repeats took 10.5 s and 10.6 s, respectively.
  These are not measured deadlines from the last authorization decision.
- After restoring the respective dependency, fresh TLS verified the new leaf
  and application body, the alias still verified, and old trust failed.
  Those recovery checks completed in 4.8 s and 4.6 s respectively.
- This fence is **replica-wide**, not per-certificate: it also sacrifices sites
  whose backend and certificate could still have worked. It is not appropriate
  to select an eight-second production limit from this experiment. A produced
  config is not proof that Traefik applied every router; recovery must verify
  real traffic. Restart loops, clock behavior, missing/invalid snapshots and
  established client connections need separate treatment before adoption.

## Matching key does not authorize the leaf SAN set

The fixture provider next compared the decoded leaf SAN set to the exact
approved DNS SAN set for that **source**, before including either its PEM or
its routers in a snapshot. A matching key with only `outside.invalid` was
withdrawn; so was a matching key covering the expected primary name **plus**
`extra.invalid`. For both injections the intended SNI and the unapproved SNI
were rejected at handshake (not an HTTP 404). Restoring the approved pair
restored the exact fingerprint and HTTP marker without restarting. A second
independent multi-SAN source remained valid: 30/30 fresh sampled TLS and HTTP
checks across its names passed. The source retained only named GET access;
both disposable namespaces were deleted. No production leaf/key was fetched.

This is evidence for provider-side SAN authorization, not an assertion that
Traefik alone enforces it. The fixture's test-only certificate decoder is not
a production parser. Production code must validate the leaf actually served,
use an audited parser, and bind the expected names to reviewed source ownership,
not just infer authorization from the presented certificate.

## Synthetic catalog-size scans, one replica at a time

35 disposable named Secrets, 37 distinct DNS names including two aliases, one
fixture owner namespace. Sequential exact GETs with a deliberate 250 ms pause
per request limited one reader to at most four starts/s. No list/watch, key
cache, production certificate access or public socket. Each run used a fresh
fixture, scanning on the actual candidate node, not three concurrent readers.
Fresh trusted TLS, expected fingerprint and host-specific HTTP body passed for
all 37 names before and after rotating the final multi-SAN source. Previous
trust failed. Observed results with a 30 s poll interval and 25 s poll timeout:

| Node | Completed scan durations (s) | Seconds from acknowledged replacement to first observed new alias |
| --- | --- | --- |
| HOME | 9.82, 11.41 | 36.32 |
| NL | 20.69, 15.67 | 41.55 |
| Moscow | 15.57, 11.48 | 36.42 |

Each reported scan completed 35 GETs and produced 35 certificate entries,
about 33 kB serialized with short synthetic leaves. Three independent full
scans would cost **105 named GETs per round**; these measurements do not prove
API capacity under simultaneous load, production chain sizes, a 24-namespace
RBAC layout, or a maximum revocation time. The earlier HOME attempt with a
15 s poll interval and no explicit poll timeout did not converge; its exact
cause was not measured. The first Moscow Pod lacked the placement toleration
and did not become ready; no TLS result is attributed to it. Do not roll out
these timings or the experimental eight-second fence: measured scan durations
alone exceeded eight seconds. Separate refresh completion, consumer apply and
key withdrawal in the production freshness design.

## Three concurrently polling replicas, one shared synthetic catalog

Each candidate node ran its own key reader and Traefik, reading the **same**
35 named fixture Secrets. One rotation changed the last two-SAN key for all
three. To limit the combined request rate, this run paused 800 ms per named
GET per source (at most 1.25 starts/s per reader on average during a scan;
requests can align). Poll interval 55 s, timeout 50 s. Both rounds overlapped
across all three nodes. Each completed round used 105 exact GETs; 210 across
the two recorded rounds, with no Secret list/watch. Serialized snapshots were
33109 bytes per replica. Kubernetes `/readyz` returned `ok` before and after;
this is not a control-plane performance or saturation benchmark.

| Node | Scan 1 / scan 2 (s) | First fresh rotated alias observed after acknowledged write (s) |
| --- | --- | --- |
| HOME | 29.25 / 29.65 | 69.82 |
| NL | 38.22 / 35.02 | 87.32 |
| Moscow | 30.77 / 30.12 | 76.78 |

All 37 fresh TLS fingerprints and per-host HTTP markers passed on every node
before and after rotation; the old trust failed on all three. These are sample
observations, not a maximum convergence time. The 55 s interval was not the
end-to-end refresh period: in this run the gap between successive **completed**
scans on each node was approximately 55 s plus the following scan duration.
Do not dimension listener fencing against the nominal interval alone. This
single rotation with short fixture chains and one owner namespace does not set
a production load budget, validate ongoing API latency, or settle per-source
withdrawal during a partial scan. Neither a timing nor an RBAC change to the
live fleet was made.

## A later failed read can mask an earlier explicit denial

Two single-node, closed catalog-size runs on HOME (35 sources, 37 names).
Sources 0 and 34 each owned two names; the other 33 sources (including 15
and 22) each owned one. Thus a complete snapshot had 35 sources / 37 names.
With both single-name sources omitted it had 33 sources / 35 names, then
34 / 36 after restoring source 22, then 35 / 37 after restoring source 15.
The earlier aborted snapshot did not replace the previously applied 35 / 37.
The fixture Role lost only `get` on source 15. The source confirmed the API
actually returned 403 for that exact name; other named GETs remained allowed.
After 22 attempted reads the fixture injected a local failure **before** the
GET for source 22. No Kubernetes server fault or real key was involved.

- **Abort the snapshot:** the HTTP provider returned 503. Fresh trusted TLS
  and expected HTTP bodies still passed for **all 37**, including the name
  already explicitly denied. Thus even an observed revocation did not reach
  Traefik. Removing the later fault (keeping the 403) allowed the next valid
  snapshot to withdraw the revoked SNI: strict handshake rejection observed
  11.74 s after clearing the fault, with the other 36 names intact.
- **Complete a nonempty snapshot without either unavailable source:** both
  affected SNIs were strictly rejected, and all 35 other names passed. Removing
  the transient fault restored that name only (36 passing); the explicit 403
  still caused handshake rejection. Restoring its exact GET returned all 37.

Treat explicit denial as independent of unrelated read failures. Omitting a
transiently failing source also withdraws its healthy website, so do not infer
that policy is universally preferable: specify outage scope, freshness and
availability budgets explicitly. Neither approach delivers a withdrawal when
Traefik cannot receive a snapshot. These were isolated tests, not a persistent
revocation ledger or proof across a config-source restart.

## Source restart after real denial but before snapshot delivery

A closed HOME run separated the tokenless marker backend/observer from the
key-bearing source. On an actual 403 for fixture source 15 the generator wrote
only a test synchronization marker and exited with status 19 **before returning
a snapshot**. Kubernetes restarted that container once; the restarted generator
waited on a test barrier before listening. The Pod UID stayed the same and
Traefik and the marker backend had zero restarts. The observer did not mount
the API token. No snapshot, PEM or production data was saved in the barrier.

With the restarted source held, two complete fresh sweeps of 37 names still
verified the previous fingerprints and HTTP bodies, including the revoked SNI.
After releasing the barrier the source re-read the still-effective denial;
strict rejection of that name was observed 18.86 s after release. The other 36
still verified. Restoring the one named GET restored all 37. This measures one
interleaving, not a revocation deadline. In particular recovery relied on the
denial **still being present**. A denial marker or successful source restart is
not consumer acknowledgement. A design requiring bounded withdrawal must test
its consumer fence and recovery separately; do not persist key-bearing
snapshots just to survive generator restarts.

## Gates before any real web deployment

- The existing `kubernetesIngress` informer still needs list/watch. This proof
  used a different stock provider; swapping TLS delivery alone does not make
  the current chart safe to deploy. Keep the DNS-only fleet unchanged.
- Generate the whole router configuration from reviewed app-owned inputs:
  preserve path priorities, explicit auth middleware, backend TLS verification,
  source references and exclusion of private routes. Compare with production
  semantics, not just a successful TLS handshake.
- Preserve the two-source withdrawal and rotation checks above. Still test
  a production freshness policy with an explicit availability budget, complete source-container loss,
  and sustained production API and latency budgets beyond the bounded concurrent run. Retain the wrong/extra SAN regression checks.
  An unreachable HTTP provider is not equivalent to a valid withdrawal snapshot.
- Test with reserved synthetic inputs on each candidate node before granting a
  production name. Do not copy TLS Secrets, add cluster-wide Secret access, or
  treat the observed distinct failure for `inform.sch1357.ru` on NL/Moscow as
  permission to change external DNS. Public DNS and VPN handoff remain separate.
