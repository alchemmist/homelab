# Graph-owned certification pilot

Import `workflow.json` **inactive**. It replaces, not wraps, the legacy
`One certify step` workflow. `python3 scripts/n8n/provision_lms_certify.py` creates the inactive draft
and refuses to overwrite an existing pilot. Regenerate the JSON with
`python3 scripts/n8n/build_lms_certify.py`.

Pilot: imported `basics/conditionals/echo-0`, empty canonical test suite. The
checkpoint starts without either test cases or a solution. The example in the
graph is an operator-authored fixture, not an example extracted from the LMS.
Candidate tests are checked against this specific task's independently simple
output rule; this is not yet a general-purpose semantic adjudicator. The five
fixed fault variants are task-specific probes, not automated AST mutations of
the emitted program. All five must produce wrong answers on **private** tests;
infrastructure failures and runtime errors do not count as killed.

Apply `pilot-state.sql` to a private Postgres database, grant only the documented
privileges, and bind the `CERTIFICATION_DB`, `LITELLM` (Authorization bearer)
and `SANDBOX` (X-Certification-Key) n8n credentials. Replace `REPLACE_RUNNER` with
an internal runner address. Deploy the LMS runner with a separate
`LMS_CERTIFICATION_RUNNER_KEY` and approved Docker daemon/sandbox image. No
credential goes into workflow JSON or the sandbox. Ensure n8n execution-data
retention is disabled for this workflow; checkpoint data is private and not
published to the LMS. The graph and its phase transitions remain inspectable
in the editor, but full execution payloads are not retained by default.

Each successful phase saves a checkpoint and routes back to the visible phase
branches. An occupied/missing/stale model series or HTTP 429 yields and
releases the lease; a process crash leaves the lease to expire. Set the lease
longer than the workflow timeout. Test runner HTTP 5xx is not a grading verdict.
Before activation verify the target cluster's metric labels and freshness,
connectivity and credential bindings with a real isolated smoke run, then
exercise repair and coverage branches before treating the pilot as certified.

Cluster pilot: `deploy_lms_certify_pilot.py` provisions the private services
and binds credentials without activating the workflow. It assumes the sandbox
image `lms-certification-sandbox:pilot` was built ahead of time from
`runner/sandbox.Dockerfile` in the rootless daemon on `socrat-1`. The pilot
uses its own persistent Postgres instance (not the LMS or n8n database).
The current provisioning uses the dedicated instance's bootstrap role; replace
it with the narrower role above before expanding beyond the pilot.

## Reviewed queue rollout (2026-11-19)

The workflow now claims the oldest eligible row using `FOR UPDATE SKIP LOCKED`,
checks for a live lease, and resumes checkpoints by execution owner. It no longer
selects only echo-0. `seed_lms_certify_queue.py` emits idempotent inserts for
four reviewed stdin/stdout tasks: integer sum, string length, parity and sign.
Statements and public examples come from canonical content; parity/sign have
explicit operator fixtures because canonical examples are absent. Existing
public examples never become private tests.

Expected outputs for generated tests are verified by reviewed deterministic
oracles (including Unicode code points and large integer sums), not by the
candidate. Each task has fixed meaningful fault probes; these are still not
AST mutants. This is an incremental finite queue, **not admission of all 781
exercises**. Other contracts require explicit validators before admission.
At queue exhaustion the model is intentionally idle; completed tasks are never
reset merely to create load. The final graph node reports queue counts.

Verified live queue results: sum 3 model responses / 7 tests / 5 fault probes;
length 2 / 6 / 4; parity 2 / 6 / 4; sign 3 / 7 / 4. Sign initially killed only
3/4 probes and entered `expand`; execution `52949` then added cases and reached
`certified` after re-running examples, suite and all probes. `queue-audit.sql`
records sanitized phase transitions keyed by n8n execution ID; apply it to an
existing database explicitly (init scripts only run on empty databases).

## Convergence-first admission (supersedes draft rollout)

Mass draft admission is disabled. Only reviewed contracts (`echo`, `sum`,
`length`, `parity`, `sign`, `leap`) may be claimed. Existing `draft_stdin` rows
remain private and unprocessed. Partially completed reviewed tasks are preferred
on resume rather than rotating across fresh tasks. Drafts are not completions.

Leap-year live result: 2 model responses, 7 oracle-verified private cases,
5/5 fault probes. Independent control `validation/leap-repair-v1` intentionally
started with the wrong rule “divisible by four”. Execution `53737` traversed
`repair -> public -> suite -> mutate -> certified`, preserving all seven cases,
with one model repair and 5/5 killed probes. This control is NOT an additional
completed curriculum task. Audit records distinguish it by its validation ID.

HTTP transport errors now enter the pause/release branch instead of leaving
an orphaned lease until expiry. Errors are retained in private n8n execution
storage for diagnosis; successful payloads are not retained. The exact cause
of the earlier draft stall was not established because error execution saving
had been disabled at that time. Fixed probes still do not constitute automatic
AST mutation or general semantic certification for arbitrary imported tasks.

## Continued reviewed batch

`seed_lms_certify_batch.py` admits ten additional real tasks using explicit
reviewed contracts in `lms_reviewed_batch.py`: repeated strings, exact Python
comparison, empty-string detection, substring matching, yes/no validation,
ordered xmas inputs, forward/reverse parrot, temperature boundaries and numeric
height sorting. No unverified draft contract is admitted. Each has independent
expected-output validation and task-specific fault probes. `coverageHints`
provides targeted input guidance to the blind test author (never candidate code).

Observed on cluster: heights stalled at 3/4 probes because all generated numbers
were three digits. After supplying differing-length numeric coverage guidance,
execution `53812` reached certified with 12 cases and 4/4 probes, preserving
existing cases. Echo-2 then completed with 12 cases and 4/4 probes. The workflow
automatically moved to meow while seven further batch tasks remained queued.
These observations are not a claim that all ten have completed.
