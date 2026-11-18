# Controlled Venice autonomy lab

Status: experimental, not production or an unattended reliability certification.
The lab compares mini-SWE-agent 2.4.6 native tool calls, its text-action variant,
and OpenHands SDK 1.62.0 with a custom isolated bash tool. The latter is **not** a
benchmark of the complete OpenHands UI or its default terminal environment.
All use the existing `litellm` provider configuration and `venice-deepseek` alias.
No paid provider or OpenHands Cloud backend is configured.

## Boundaries

- The model never executes commands in the controller's filesystem. There is no
  local-shell fallback, Docker socket mount, home mount, browser profile mount,
  kubeconfig mount, or credential forwarding into execution containers.
- Docker is a remote Podman-compatible endpoint on this machine. Host bind mounts
  did not transfer Mac fixtures; that initial run was invalid infrastructure, not
  a scored model failure. Files are copied through the Docker API instead.
- Each attempt owns a non-root, network-none container with a read-only root,
  zero effective/permitted/bounding capabilities, no-new-privileges, 512 MiB RAM,
  one CPU, 128 PIDs, a 64 MiB temporary filesystem and an owned 32 MiB tmpfs volume.
  The tmpfs volume uses private SELinux relabeling (`:Z`), not label disabling.
- Runtime capability checks and a positive workspace write probe run before the
  first model request. An earlier named-volume attempt failed SELinux writes
  despite mode 0666; it is excluded from model quality comparisons.
- A plain per-container tmpfs disappeared from Podman's paused archive view.
  The owned tmpfs-backed volume allows a real freeze followed by an archive
  snapshot. Only two regular, bounded UTF-8 files are accepted; links, extra files,
  traversal and duplicate members fail closed. Archives are never extracted.
- A fresh credential-free container verifies the frozen candidate. A zero exit
  without complete nonce-bound JSON results is not success. Oracle expectations
  and the acceptance decision live outside the candidate process. Mutation
  observations are produced in the candidate Node process; this is testing, not a
  proof against adversarial JavaScript or container/kernel exploits.
- No automatic commits, pushes, deployments, credential requests or permissions
  changes. Only containers/volumes recorded as belonging to this lab are removed.

## Task and continuation model

There are three small synthetic repair contracts: median, clamp and HTML escaping.
Each has a deliberately buggy baseline and an unchanged visible test. Independent
acceptance adds 64–65 cases, including seeded randomized cases and input mutation.
These are **not** broad SWE-bench tasks or autonomous research in the Venice repo.

The controller processes task × engine × round entries serially. A final answer
ends an attempt, not the queue. Failed acceptance permits one fresh-context
rework attempt with verifier feedback, then marks that entry blocked. Every new
attempt starts from the same buggy fixture, not a previous model's patch.
`queue_finished` means entries were processed; consult accepted/blocked counts.

The default matrix is native mini and OpenHands. Text-only mini is opt-in with `--include-text`. A three-round default run has 18 entries; including text restores the historical 27 entries / 54 attempts. The deadline stays the original stored value across restart.
Each child has an outer 900-second limit; shell commands have a 40-second limit.
Mini has an 18-step/600-second budget; OpenHands has an 18-iteration budget.
HTTP requests allow 720 seconds because queueing plus one bridge regeneration can
exceed shorter client timeouts. Client automatic retries are disabled. The bridge's
existing one visible format regeneration is unchanged. Two consecutive recognized
provider exceptions stop the controller. Missing/malformed summaries or recognized
runner integration errors stop immediately instead of wasting the entire queue.
A stop is not silently retried forever. `BadGatewayError` counts as a provider failure, including when the verifier already accepted the artifact. An SDK wrapper counts only when a structured cause, `cause_type`, or `error_chain` names a known provider exception. Unknown exception types stop with an explicit `unknown error type` error. `ContextWindowExceededError` stops as `context_length_exceeded`, and `BadRequestError`, `InvalidRequestError`, `UnprocessableEntityError`, or `RejectedRequestError` stop as `client_input_rejected`. Neither is a provider outage. Message text alone does not invent those types or change the live stop decision. `REPORT.md` keeps artifact acceptance separate from a clean Submitted or finished exit. A null mini `exit_status` is a clean finish only when the stored trajectory has a top-level exit event of `Submitted`. Otherwise it stays unknown. Historical receipts are not rewritten. Process/worker cancellation is not proof
that a non-streaming HTTP disconnect instantly releases the upstream Venice
browser slot; that remains an explicit acceptance gap for these clients.

State checkpoints are fsynced and atomically replaced under an exclusive lock.
Restart preserves the original deadline, terminates a matching orphan child,
cleans only recorded lab resources, and records the interrupted attempt as failed.
It does not accept a partial candidate or resurrect an operator-stopped run.
Source hashes prohibit a changed implementation from silently resuming a run.

## Setup and verification

Use separate private virtual environments; these top-level pins are not a
fully hashed production dependency lock:

```sh
uv venv --python 3.12 /private/tmp/venice-agent-lab/venv
uv pip install --python /private/tmp/venice-agent-lab/venv/bin/python mini-swe-agent==2.4.6
uv venv --python 3.12 /private/tmp/venice-agent-lab/openhands-venv
uv pip install --python /private/tmp/venice-agent-lab/openhands-venv/bin/python \
  openhands-sdk==1.62.0 openhands-tools==1.62.0 openhands-workspace==1.62.0
python -m unittest -v test_lab test_controller_faults
```

`provider_settings()` accepts only an environment-backed key reference from
`~/.pi/agent/models.json`; it never writes that key into configuration or arguments.
The optional `LAB_PI_MODELS` override selects a different trusted configuration.
Private logs can contain task source and model output; keep the root mode 0700.
OpenHands completion pricing is unknown for this alias. Ignore its cost-mapping
warning for this experiment, but **do not describe missing pricing as measured
zero cost**. Bridge token usage is also approximate.

Example invocation from a frozen private copy of the scripts:

```sh
python controller.py --root /private/path/run \
  --mini-python /private/tmp/venice-agent-lab/venv/bin/python \
  --openhands-python /private/tmp/venice-agent-lab/openhands-venv/bin/python \
  --duration-seconds 5400 --rounds 3
```

`state.json` is authoritative. `REPORT.md` summarizes only externally verified
results. Model trajectories, executed commands, candidates, security receipts,
verifier output and errors remain alongside it. Tests using fake children are
explicit controller fault tests, not model acceptance evidence.

Initial compatibility checks: mini native completed a median repair with actual
commands and independent tests; text-only stopped on multiple-action format
errors. OpenHands SDK completed a median repair with 65 fresh-container cases.
Those one-off checks establish compatibility, not relative latency or multi-hour
reliability. An initial controller run was also stopped for a runner integration
bug: the mini observation dictionary lacked `exception_info`. It is not scored.
The replacement run retains the original absolute deadline instead of granting
another 90 minutes. Cancellation cleanup covers both agent and verifier resources. Earlier scaffold failures are retained separately and not scored.

## Same-conversation continuation

`continue_openhands` runs once when no acceptance callback is supplied. With a
callback it runs at most three times and sends another turn only when
`facts['continue'] is True`. A non-boolean value does not authorize another run.
After the third rejection it returns `exhausted` and does not call
`send_message`. OpenHands sets `execution_status` to idle when a message is
sent without a following run, so an exhaustion notice would hide a finished
third run. The rejection receipt remains in `acceptance-rounds.jsonl`. An exception from `conversation.run` propagates
without a replay. `repository_runner.py` calls `run_openhands(..., acceptance=...)`
from this worktree; it does not exec a rewritten copy of the function.
Round and final artifact acceptance share `artifact_accepted`: a functional
pass is not enough when new comments, protocol edits, or edits outside the two
allowed methods are present. `overall_success` also requires a clean finish and
the absence of provider, infrastructure, and cleanup errors. A valid artifact
after a provider error stays accepted as an artifact and still fails the process. Paths,
image, snapshot and output root come from `AUTONOMY_*` environment variables.

Unit coverage is `test_continue.py`. The verifier contract from
`fix/autonomy-verifier-contract` (`f11e35ea`) is combined here: cases go to the
verifier on stdin, the host seals the execution, and archive names are checked
before acceptance. Owned-resource cleanup labels from this branch stay in place.
The combined unit suite is `test_lab`, `test_controller_faults`, and `test_continue`. A live OpenHands run through this adapter,
receipt directory `live-20261117-234501`, finished in 176.587 seconds with
`accepted=true`, `clean_finish=true`, `ConversationExecutionStatus.FINISHED`,
11 recorded commands, one acceptance round and `continue=false`. That receipt
does not exercise rejected-then-continued acceptance.

`live-20261117-235900` is a later run of the same adapter with
`AUTONOMY_FORCE_CONTINUE_ONCE=1`. It finished in 314.009 seconds:
`accepted=true`, `clean_finish=true`, `ConversationExecutionStatus.FINISHED`,
18 commands, visible repro `462306b47604…`, and no cleanup error. Acceptance
rounds were: round 0 `real_accepted=false` because new comments were present
(`continue=true`; the force flag was also set, but the real verdict was already
a rejection); round 1 same candidate hash, `real_accepted=false`, `continue=true`
with the force flag unset; round 2 `real_accepted=true`, `continue=false`,
comments gone. The final container grade passed, including the two-method
boundary. An earlier continuation attempt, `live-20261117-235439`, stopped on
`BadGatewayError` after round 0 and is not a success. Neither receipt is a
multi-hour autonomy result. Missing model-price mapping is not measured zero cost.
The historical grader now lives in this tree as `protocol_regression.py`.

## k3s direction

See `../../charts/venice-agent-lab/README.md`. That chart is an undeployed worker
**draft**, not a running OpenHands service. No Argo Application activates it.

Current upstream sources:

- <https://github.com/SWE-agent/mini-swe-agent> (v2 recommends native tool calls)
- <https://github.com/OpenHands/software-agent-sdk>
- <https://github.com/OpenHands/OpenHands/blob/main/docs/SELF_HOSTING.md>
- <https://github.com/OpenHands/OpenHands/blob/main/docs/architecture.md>

The SDK includes `AgentSandboxWorkspace` backed by kubernetes-sigs/agent-sandbox.
It requires optional dependencies, cluster CRDs/controllers and a warm pool;
gVisor/Kata is an explicit infrastructure decision, not automatically provided.
Default remote conversations move agent execution to the remote server. The
standard Agent Canvas launcher grants shell/filesystem access on its host.
Neither should be dropped into the existing cluster with production credentials.

## Historical Python grading safeguards

The historical grader preserves method signatures as well as code outside the
allowed methods. Each selected unittest must exit successfully and emit its
one-test, non-skipped completion summary; a zero exit before test completion is
not a pass. Both subprocess output channels have a 128 KiB limit and a deadline.
A failed Docker start cannot be overwritten by a zero inspected container status.
Continuation receipts include bounded failed-test diagnostics so the model can
act on a rejection rather than seeing only a candidate hash.

These are regression and resource safeguards, not a tamper-proof Python runtime.
Candidate Python and unittest execute in the same interpreter inside the isolated
worker. Deliberately hostile Python can tamper with interpreter state or forge
unittest output. The Docker boundary protects the host; it does not make that
in-process test result cryptographically trustworthy. The sealed JavaScript
fixture verifier and this historical Python exercise have different trust models.
