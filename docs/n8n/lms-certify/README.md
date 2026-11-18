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
