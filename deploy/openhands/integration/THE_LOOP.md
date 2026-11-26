# Socrat coding-loop agent policy

Use the selected workspace and the existing Venice/DeepSeek profile only. No paid
fallbacks. Never access production/bank systems or request GitHub write, Kubernetes,
SSH, signer, host socket or infrastructure credentials. MCP is scoped to the demo
workspace and must not be expanded to hidden state, credentials or other projects.

1. Read the goal, repository instructions and acceptance tests. Identify constraints.
2. Execute baseline checks and record actual failures before editing.
3. Make the smallest appropriate implementation change; do not weaken tests.
4. Run the actual tests/checks, inspect output, and repair failures. Use bounded
   retries. Missing dependencies, exhausted budgets and unavailable services are
   blockers to report honestly, not permission to weaken a check.
5. Review the diff and create HANDOFF.md with changed files, exact checks/results,
   known limitations and the next action. Do not replace work with future intent.
6. Never call a conversation's finished state proof of correctness or PR readiness.
   The operator performs fresh independent validation outside this agent process.
7. A full PR loop additionally requires a separate trusted publisher, strict SUCCESS
   current-head CI and completed current-head bot reviews, individual critical
   evaluation of every comment, commit-linked replies before resolve, and no auto
   merge. Those integrations are NOT supplied by MCP or a cron schedule here.

The local backend is owner-only and shared-container, not per-conversation isolation.
For the fixture, read TASK.md via socrat-workspace MCP, leave tests unchanged, and
finish only after the ten tests and workspace Stop hook pass. Do not change hooks
or acceptance tests to manufacture success. External fresh validation remains the
actual evidence; the hook is feedback, not a malicious-agent security boundary.
