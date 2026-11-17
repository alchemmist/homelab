# Parent repair of the native PSI regression

The small Grok pilot392bf002-4332-491b-be5d-6a278acba7f4did not deliver a repair:
its saved response is introductory prose and its terminal assistant message is
thinking-only. The handoff nevertheless says completed. Its temporary worktree
was already absent at parent inspection. No source commit was supplied or
accepted. No retry/model/CLI fallback or global agent configuration edit followed.
The parent implemented the source change in the authorized parent worktree.

## Source and native-test preservation

- tests/test_socrat4_contention.py: Ruff ALL97findings before, zero after;
  strict mypy2errors before, zero after; formatter passes.
- All11case tuples are identical to eb0e2935, including the socrat-4CPU29/31minute
  boundary, non-firing CPU/memory/IO cases and the other node's original limits.
- A comparison harness used one real offline Helm render and captured both old
  and new test generation. All4complete YAML documents and all3native argv vectors
  (normalizing only executable basenames) match, including historical old.yml.
  This comparison is supplemental, NOT a substitute for native execution.
- Real Helm/promtool regression and quality-system/evidence tests:121passed,
  exit0. The real test still invokes both promtool suites with failure checking;
  there is no daemon-availability skip or fallback.

## Shared checked execution boundary

Rather than inventing a process-launch wrapper in the test, the native regression
uses the existing common.command checked, captured, bounded execution boundary.
Added an optional cwd: Path | None keyword; omitted/None preserves repository ROOT.
This supports promtool's private temporary fixture directory without process-wide
chdir. It retains120second default timeout, allowed-exit validation, captured text
and refusal without arbitrary failure-output disclosure. Three added regression
cases prove default/explicit cwd behavior and that an explicit directory cannot
turn a nonzero exit into success or disclose the captured payload.

Native executables are resolved explicitly and missing prerequisites fail. Local
Helm is the existing /opt/homebrew/bin/helm4.3.2, not a newly installed or claimed
checksum-locked Helm. Promtool is the repository checksum-locked tool. No tool
version, source alert threshold, image or runtime configuration was changed.
The shared runner's own remaining security/style findings, if any, are not
suppressed by this refactor and remain in the complete repository audit.

## Main integration

Before this batch, fetched main6ecb677b (including60c3b4ac) and merged as eb0e2935.
Resolved charts/venice-api/values.yaml using main's new tag/digest, with only YAML
framing/quote representation retained from the strict branch. Verified the full
ordered composed graph, scalar tags/values and alias sharing of BOTH Venice values
files against main. No image override or deployment operation was performed.

This checkpoint records scoped checks, not full green CI, native artifact admission
or permission to merge a red branch. Whole-repository exact-HEAD validation follows.
