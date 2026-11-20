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

### Supervised convergence fixes

Repair prompts now carry explicit diagnosis and prohibit unrequested case/space
normalization. A per-task `callLimit` can be increased deliberately while
retaining cumulative call counts (default stays 12). Yes/no was resumed with
its eight existing tests and a limit of 16, completing at call 14 in execution
`53853` with 4/4 fault probes. No counters or tests were reset.

Private suite capacity now matches runner's maximum of 16. The former 12-case
cap prevented adding a missing boundary once full. Operator-authored
`targetedCases` enter only the expansion branch and pass the SAME independent
oracle as generated proposals; existing tests remain intact. Reverse parrot
completed in `53858` at 16 tests and 4/4 probes. Regression checks cover preserving
12 existing cases while adding a targeted case, plus bounded repair continuation.

### Continuous differential admission

When no reviewed task or matched equivalent is pending, `Admit next elementary
stdin exercise` selects ONE prefiltered elementary stdin task with canonical
examples. At rollout 160 existing rows satisfied the filter. This does not
admit function tasks, all drafts, or entire courses indiscriminately. For
already reviewed zero-input tasks, the single valid test is derived directly
from `reviewedOutput`; never spend calls repeatedly guessing a known oracle.

New differential certificates have explicit scope `bounded_same_model_differential`:
solution and distinct witness generated in separate calls, blind test author,
semantic review, both solutions accepted against public examples and >=4
private cases, >=3 distinct nonempty fault variants. Every variant must produce
`wrong_answer` on the suite and `accepted` on at least one input. Crashes and
always-wrong variants cannot pass. Surviving variants trigger expansion;
failed audit, witness disagreement, or exhausted budget do not count as success.
These are bounded behavioral checks with correlated model risk, not a human
semantic proof. A separate reviewer model is not wired here. A finite backlog
may eventually exhaust; diagnosis and verified completions are distinct.

Apply `upgrade-differential.sql` on an existing DB before activating. Use
`status.sql` against the private pilot database to report state without leaking
artifacts. Metrics busy/missing/stale continue to block inference. Existing
certificates are not relabeled. For API maintenance if the configured VPN
address is unavailable, use the verified TLS hostname's resolved address via
`N8N_API_RESOLVE_ADDRESS`; do not disable TLS validation.

Busy or unavailable inference telemetry does not block **already admitted
sandbox-only** work. That branch can only lease a public/suite/mutation/witness
execution phase, never admit new work or call LiteLLM directly. At a subsequent
model phase the ordinary per-call admission check still applies. `diggers`
and `greeting-report` required explicit operator source repairs after the old
12-call loop; provenance and previous source are retained privately. Both then
passed the singleton input suite and 4/4 pre-reviewed fault probes in the live
workflow. These two completions are not evidence of autonomous model repair.

Differential probe quality: propose up to five distinct source mutations. Keep
the suite blind to candidate code. A crash is not a kill. A variant wrong on
all sampled inputs is rejected as a control, not counted; continue evaluating
the rest of the bank. Certification still needs at least three distinct
variants with observed correct AND wrong behavior. Any surviving private-suite
variant routes to expansion, not certification. Failed plausibility can request
a bounded new bank. Before semantic approval, a reviewer can identify specific
invalid private cases by index; quarantine only those, preserve all others and
require review again. Never drop approved cases this way.
