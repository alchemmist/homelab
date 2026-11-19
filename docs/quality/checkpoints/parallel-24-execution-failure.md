# Twenty-four-worker execution failure — not an accepted repair

Workflow d5448cf3-75a3-4775-96ba-834502d4db7e, mission
6a87d53d-dc0a-4e83-b0e9-296943dc389b, base573690b8. All lanes
used managed isolated worktrees and cursor/grok-4.7. No alternate CLI/model,
purchase, blanket retry or worktree mutation was used for recovery.

The parent inspected workflow status after failure/attention notices. The final
state was failed:15children ended as completed,9failed. Saved completed outputs
were introductory/progress statements, not implemented repair reports.

Failures included: empty-output/cold-start classification (not a proven root
cause), missing virtualenv, missing mypy with an unpinned global Ruff0.17.5,
malformed grep invocation lacking pattern, a provider request timeout, and a
nonzero format-diff command. These are execution failures, not source findings
cleared or checks passed. The global Ruff result is not accepted locked-tool
evidence. Completed workers supplied no claimed source commit to review.

Parent separately inspected all24corresponding Git branches/worktrees read-only:
- zero commits beyond573690b8 in every branch;
- zero changed/untracked files in every worktree at inspection time;
- no implementation is available to cherry-pick or count as progress.

Late no-activity notices do not authorize revival of already completed/failed
children. No old worker was silently restarted. Worktrees and retained logs were
left intact; no pruning/reset or other agents' workspace writes.

The operator's original requirement is NOT complete. PR182remains draft/red at
bd7f3071357e8125ab237e3f65bd00328e870620. Its last complete exact-head audit
is50580blocking findings;702fast tests/1existing skip/329subtests. Those figures
are historical evidence for bd7f3071, not a new audit of this documentation-only
checkpoint. No main merge, native admission success or full-CI success occurred.

Before another broad launch, execution reliability must be diagnosed and the
locked environment setup made reliable in isolated workers. Altering global
agent/provider configuration, purchasing credits or switching CLI is not an
implicit consequence of the homelab source-repair mandate. Failure is reported
rather than hidden behind more fan-out or completed-process labels.
