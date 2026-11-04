# Inference client reliability contract

Operator policy adopted 4 November 2026: model capacity is shared and time is
available. A temporarily busy model must defer a task, not exhaust it permanently.
This is a required client design contract, NOT proof that every client implements it.

- Persist accepted work, due time and validated checkpoints before acknowledging.
- Treat known LLM429, transient5xx and transport timeouts as safe deferred work;
  retry without a task-attempt limit, with backoff/jitter and Retry-After handling.
- Bound each attempt; release leases/concurrency slots between deferred attempts.
  Do not keep an n8n execution sleeping for hours or overwhelm shared inference.
- Keep total attempts diagnostic. Deferrals must not consume independent terminal
  budgets needed by subsequent stages. Retain visible pending/error and queue age.
- Resume validated work only when its input/snapshot identity is unchanged.
- Malformed request/auth/configuration errors need operator attention. Repeated
  invalid/unsafe output must never bypass validation just to complete a task.
- Model retry is not permission to repeat external side effects. Preserve durable
  publication intents/reconciliation; never blindly retry ambiguous GitHub writes
  or speech. Recheck deadlines/freshness before time-sensitive actions: patient
  model preparation does not justify speaking an obsolete calendar reminder.
- Promise retained work and safe recovery, not unconditional success, exactly-once
  remote delivery, or completion against permanently failing/changing dependencies.

Implementation status: SPI hardening is recorded in `spi-incident-triage.md` and
`docs/n8n/spi/setup.md`, section Patient LLM client retries. Calendar, blog and other
clients still need a separate audit; they are NOT claimed compliant by this file.
Do not change calendar speech policy or enable blog writes as part of retry work.
