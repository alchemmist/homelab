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

The initial run has a fixed 90-minute deadline and at most 27 entries / 54 attempts.
Each child has an outer 900-second limit; shell commands have a 40-second limit.
Mini has an 18-step/600-second budget; OpenHands has an 18-iteration budget.
HTTP requests allow 720 seconds because queueing plus one bridge regeneration can
exceed shorter client timeouts. Client automatic retries are disabled. The bridge's
existing one visible format regeneration is unchanged. Two consecutive recognized
provider exceptions stop the controller. Missing/malformed summaries or recognized
runner integration errors stop immediately instead of wasting the entire queue.
A stop is not silently retried forever. Process/worker cancellation is not proof
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
