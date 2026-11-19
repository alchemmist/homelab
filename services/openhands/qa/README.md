# Local Monori QA orchestrator

Canvas 1.41 / SDK 1.62: `socrat-qa-orchestrator`, `v-deepseek-uc`, native
`task_tool_set` (`openhands.tools.task.definition`), no parent terminal/editor,
MCP or secrets. Started via `/api/conversations` with programmatic
`agent_definitions` derived from `roles.json`, inherited model and parent
confirmation policy, no recursive task tool. `qa-scenario` requests no working
tools; the other five roles request terminal/editor. These are workflow roles,
not security boundaries. Children share the QA workspace. Use one writer per
worktree; independent browser jobs require separate SQLite, ports and artifacts.
The legacy QA conversation ca1e0cce was paused before starting e153dc62.
Mutation work is independent. Check ActionEvent(task, subagent_type) and
ObservationEvent(task_id,status,is_error); plain text about delegation proves
nothing. SDK TaskExecutor blocks until its child returns, unlike a durable async
queue. Global model concurrency is two; the Venice bridge emits one tool call
per response. No guarantee of parallel child execution, automatic crash recovery,
GitHub issue/media publication or end-to-end PR readiness from this setup alone.
