from services.public_entry import solver_lease


def test_cold_restart_rejects_old_replies_even_with_same_uid_and_open_round():
    first = solver_lease.SolverLease(10**10)
    old = first.begin()
    assert first.complete(old, "same")
    second = solver_lease.SolverLease(10**10)
    assert second.witness("same") is None
    pending = second.begin()
    assert not second.complete(old, "same") and second.witness("same") is None
    assert second.complete(pending, "new") and second.witness("same") is None
    assert second.witness("new") == pending and not second.complete(pending, None)


def test_abort_supersession_and_slow_results_never_extend_the_original_deadline(
    monkeypatch,
):
    tick = [100]
    monkeypatch.setattr(solver_lease.time, "monotonic_ns", lambda: tick[0])
    slot = solver_lease.SolverLease(10)
    t = slot.begin()
    tick[0] = 108
    assert slot.complete(t, "one")
    proof = slot.witness("one")
    p = slot.begin()
    q = slot.begin()
    assert not slot.complete(p, None)
    slot.abort(q)
    assert not slot.complete(q, "one") and slot.witness("one") == proof
    tick[0] = 110
    assert slot.witness("one") is None
    slow = slot.begin()
    tick[0] = 120
    assert not slot.complete(slow, "one") and slot.witness("one") is None


def test_in_flight_witness_changes_on_denial_and_on_same_uid_readmission():
    slot = solver_lease.SolverLease(10**10)
    t = slot.begin()
    assert slot.complete(t, "same")
    before = slot.witness("same")
    assert before is not None
    assert not slot.complete(slot.begin(), None) and slot.witness("same") is None
    assert slot.complete(slot.begin(), "same") and slot.witness("same") != before
