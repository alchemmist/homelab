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
