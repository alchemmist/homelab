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
