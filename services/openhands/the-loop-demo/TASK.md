# Socrat the-loop acceptance fixture

Implement `merge_intervals` in intervals.py. Return sorted merged intervals, merging
both overlapping and touching ranges; handle empty, nested and negative ranges;
reject reversed intervals with ValueError; never mutate caller input.

First read this TASK.md through the configured socrat-workspace filesystem MCP.
Then run the existing unittest suite to observe the baseline failures, fix the
implementation (do not modify tests), rerun tests, and inspect the actual output.
Write HANDOFF.md with the red/green commands/results and limitations. No package
installation, internet, production access, GitHub writes or credentials required.
Finish only after all ten tests pass. The operator will independently validate the
candidate with the original tests in a fresh no-token/no-network restricted Job.
This fixture is NOT a claim of a completed PR/CI/bot-review lifecycle.
