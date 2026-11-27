# Closed solver gate: restart and stale confirmations

`services/public_entry/solver_lease.py` is an in-memory rehearsal for **one**
independently approved Host/path. It is not a deployed server or an API reader.
A round starts with a new random ticket and a deadline from the consumer's
monotonic clock. Completion is accepted once, only for the latest outstanding
ticket. The deadline starts at **begin**, not on delivery of the result. An
interrupted read cannot extend an existing grant. Confirmed absence removes
it. Start a new process empty; never restore a pending ticket or active lease.

The caller must independently verify the Challenge UID and perform a genuinely
fresh, complete read for that round. A ticket authenticates no caller and does
not prevent a trusted verifier from relabeling stale input with a new ticket.
The three-stage request check is: capture a nonempty witness for the intended
UID, obtain and check a bounded backend body, require the *same* witness before
starting the response. Checking only that the UID is currently allowed misses
revocation followed by re-admission of that same UID.

## Runtime observations

Two real pinned v1.16.2 solvers, a fixture gate, an ordinary marker backend and
Traefik ran on an internal Docker network with no published ports. The control
channel was local to the fixture. UID confirmations were synthetic, not Kubernetes
or CA attestations. Both solvers and the ordinary routing file stayed in place.

- Held a verified upstream response, confirmed absence, then re-admitted the
  **same** UID under a fresh round. The buffered request got 410 without its
  solver body. A fresh request succeeded; the other solver still worked.
- Terminated only the gate process and checked that its PID changed. Both
  exact paths returned 410; neither solver had been fetched by the new process.
- Started new rounds for both slots, then delivered prior-process completions.
  Both were rejected, still 410/410 with zero upstream reads. Confirmed only
  the second current round: 410/200. Confirmed the first: 200/200. Final reader
  counters were one and two, respectively. Ordinary root and near miss still
  returned the ordinary marker; wrong Host returned 404.

Unit controls also cover changed UID, late results, duplicate delivery, abort,
superseded rounds, and expiry at the exact deadline. This does not cover saved
process images/clock rollback, a compromised authority, multi-worker coherence,
a pause after the last check, or bytes already written. No production trust,
timing budget or real issuance is implied. No keys or account data were used.

## Bind renewal to the namespace scan

`ScannedSlot.refresh` starts its ticket **before** page one of `scan_namespace`
and accepts the resulting single-slot grant only for the same UID, exact
Host/token rule and verified backend URL. It does not accept a precompiled
snapshot argument. A complete scan without that exact presentation revokes;
a raised/incomplete scan cancels only its outstanding ticket. No later result
can move the deadline to its receipt time. This is a single-slot fixture,
not a plan to rescan a whole namespace separately for every production token.
The callbacks still must read fresh authoritative data; correlation cannot
make an untrusted reader truthful. Separate resource lists are not atomic.

An operator rehearsal seeded a slot using synthetic observations, then
injected a second-page 410. The previous witness remained unchanged and was
absent after its original three-second fixture window, without renewal. A
fresh synthetic admission followed by a real terminal empty Challenge LIST
in a disposable namespace removed the slot without child lookups. No real
Challenge, issuer or account was created. Unit controls also exercise child
read interruption, a late complete scan and a new ready destination IP not
renewing the old address. These are gate-state observations, not listener
handshakes or public issuance.

## Scan interruption observed through the running listener

In an internal Docker network two stock acmesolvers, Traefik and an ordinary
marker stayed live. Both exact paths went through the gate using the actual
`ScannedSlot.refresh` and request-time witness checks. A loopback fixture API
served Kubernetes-shaped pages and child observations over HTTP, not a real
Kubernetes API or CA. No grant bodies, challenge paths, or tokens were logged.
Only the first slot was refreshed in the fault stages; this does not model an
atomic namespace-wide update. Initial fixture windows were 35 s and 180 s.

| First slot scan | Fresh exact-path responses (first / second) | Control |
| --- | --- | --- |
| Cold; then both slots independently complete two pages | 410/410; then 200/200 | Correct distinct solver bodies after admission. |
| First page valid, second returned HTTP 410 | 200/200 before original expiry | No child read; witness unchanged. API 410 is not a client-side withdrawal. |
| Both pages valid, first child connection closed without a response | 200/200 before original expiry | One child lookup attempted; witness unchanged. |
| No further successful refresh before the first deadline | 410/200 | First solver fetch count stayed at three; second went from three to four. |
| Complete fresh scan; then terminal empty LIST for the first slot | 200/200; then 410/200 | Empty result required no child reads; final solver counts four and six. |

Each sweep also checked ordinary `/`, a near miss returning the ordinary
marker, and wrong Host returning 404. The ordinary file checksum did not
change. A preliminary run with a shorter window failed a pre-expiry assertion;
it was not counted as passing evidence. The successful run establishes sampled
listener behavior, not a latency bound or a recommendation for production
leases. Next integration concern: refreshing all slots from one complete,
consistent namespace observation, without reopening a removed slot or letting
one consumer see results from a superseded round.

## One shared scan, late successful result

`NamespaceGate` is a fixed-scope, single-process experiment. Start a round
before page one, match all configured slots against one finished namespace
scan, then replace the entire in-memory table under the request reader's lock.
Each slot's deadline is relative to the round's start. Starting a newer round
permanently disqualifies any earlier outstanding one. A failed latest round
leaves the previous table on its original deadlines; it does not authorize
falling back to the superseded scan. A newly committed table gives admitted
slots new witnesses, so even an unchanged in-flight response may be discarded
on recheck. This favors conservative suppression over that request's availability.

In the isolated two-solver listener fixture the initial two-page scan did two
child lookups **total**, not two scans per slot. An older HTTP list with both
Challenges was then held on page two. A newer, one-page list with only the
second Challenge committed. Fresh exact requests got 410/200. Releasing the
older scan let it finish both pages and both child lookups, but it could not
commit; fresh requests still got 410/200 and the first solver fetch count
remained one. A further fresh complete scan explicitly restored both. Ordinary
root, near miss and wrong Host remained independent controls. A concurrent
unit test also forced the newer round to fail: the late success could not
renew or replace the previous witnesses in that case either.

This serializes commits **only in one gate process**. The HTTP API and child
observations were fixture data. No cross-resource transaction, multi-worker
consensus, authoritative CA observation or sustained API load was tested.

## Three independent consumers with one control-plane partition

Three separate Traefik processes and gate processes (independent in-memory
tables and local clocks) shared a synthetic HTTP API on an internal Docker
control network. A separate internal data network carried requests to the two
stock solvers. Each ordinary marker was local to its replica. No host ports,
cluster addresses, VPN peers or real ACME account were used. These are three
logical consumers on one Docker host, **not** geographical survivor tests.

After each consumer admitted both paths from the same two-page inventory,
the third consumer's network namespace was disconnected from the API bridge
only. The API was changed to report just the second task. The two connected
consumers each completed one page and one child lookup; the disconnected one
failed its first page and performed no child lookup. With both solvers alive:

| Fresh HTTP sweep | First consumer | Second consumer | Disconnected consumer |
| --- | --- | --- | --- |
| Before withdrawal | 200/200 | 200/200 | 200/200 |
| After connected consumers saw withdrawal | 410/200 | 410/200 | **200/200** |
| After the first local budget elapsed | 410/200 | 410/200 | **410/200** |
| After control-network reconnect and fresh remaining-only scan | 410/200 | 410/200 | 410/200 |
| After a new two-task inventory and three successful scans | 200/200 | 200/200 | 200/200 |

Pairs refer to the two distinct exact paths. Successful bodies were compared
to their respective solver responses; refusals contained neither. The lagging
consumer fetched the first backend twice (baseline and the stale sweep), not
again on expiry. All ordinary roots, adjacent paths and wrong-host controls
kept their expected results; all three ordinary configuration files remained
byte-identical. Containers and both networks were removed.

The fixture used 30 s and 180 s windows. This demonstrates bounded local age
**at the sampled request checks**, not simultaneous withdrawal or a hard limit
on bytes already in flight. Under prolonged isolation the second slot would
also lose its authorization at its own deadline; this run did not wait for
that deadline. Do not infer independent DNS, public issuance, application
survival or VPN failover from this control-plane partition.
