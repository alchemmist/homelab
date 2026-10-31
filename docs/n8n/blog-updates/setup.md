# Blog Updates automation — dry-run rollout

## Components

- `docs/n8n/blog-updates/workflow.json`: Exactly four visible nodes: GitHub Push → LiteLLM validation →
  LiteLLM generation → PR creation. Each stage has its own authenticated internal
  worker endpoint. The native GitHub Trigger verifies signatures before forwarding.
- `scripts/blog_updates/engine.py`: event/diff/model validation and Markdown rendering.
- `scripts/blog_updates/github.py`: compare pagination, snapshot reads, PR writer.
- `scripts/blog_updates/run.py`: analyze push using Qwen via LiteLLM; dry-run default.
- `scripts/blog_updates/server.py`: serialized internal executor, token authentication.
- `deploy/blog-updates/worker.yaml`: pinned Python image, nonroot, read-only root,
  no service-account token, ClusterIP only, `WRITE_ENABLED=false`.
- `scripts/blog_updates/deploy.py`: reproducible source ConfigMaps and deployment.

No auto-merge exists. The writer can modify only `site/content/updates.md`.
Branches are deterministic by full head SHA. Existing PRs, including closed ones,
are not recreated. Advanced main causes a fail-closed result rather than overwrite.
An interrupted write after branch creation currently needs manual recovery; it
will fail closed on duplicate ref, not overwrite/reopen a proposal.

## Local secrets (never commit)

Under `~/.config/n8n/`, mode 0600:
`blog-github-token`, `blog-litellm-key`, `blog-worker-token`,
`blog-credentials.json`, `blog-workflow-id`.
GitHub credentials need Contents/Pull requests read-write and Webhooks read-write
for the native trigger to create/delete its own subscription. Worker secret
`automation/blog-updates-worker` contains GITHUB_TOKEN/LITELLM_KEY/WORKER_TOKEN.
The LiteLLM virtual key is restricted to qwen3.8-27b and 6 requests/minute.

## Current live state

Worker deployed and healthy; writes disabled. n8n workflow **active in dry-run**.
Read-only model test on commit 1e508b9 succeeded: model declined an announcement
for a minor navigation-code change. No branches/PRs/webhooks created.
GitHub Webhooks permission granted and native signed webhook registered.

## Before activation

- Add front-matter extraction, draft/publication checks and verified Hugo URLs.
  Current generated text deliberately disallows model-supplied links.
- Evaluate new content/translation/design examples, not only a skip case.
- Test real PR creation and existing/closed PR behavior in GitHub.
- Add persistent job status/retry handling: HTTPServer serialization is not a durable
  queue; n8n receives webhook before worker completes, so failures need replay.
- Configure workflow ID/credential upsert provisioning (currently imported once).
- Then explicitly enable writes and monitor initial real pushes.

Tests: `python3 -m unittest discover -s tests/blog_updates -v`.
Deployment: `python3 scripts/blog_updates/deploy.py` (does not create Secrets).
Code ConfigMap changes require restarting worker so imported Python modules reload.
The blog homepage's first-five template change is local and not yet committed.

### Webhook verification update (2026-10-31)

Webhooks permission now returns 200. Native trigger activated in dry-run mode;
GitHub registration ping returned 200. An unsigned POST was rejected with 401.
A signed simulated push with a real historical before/after range traversed
n8n → worker → GitHub compare → LiteLLM/Qwen: execution 1406 succeeded, result
`skipped` for a minor navigation refactor. Initial execution 1400 uncovered a
ConfigMap symlink path issue; fixed via explicit PROMPT_FILE in deployment.
Worker writes remain disabled. Successful execution saving enabled during testing.
This verifies a signed simulation, not yet a real new GitHub push delivery.

### Content and real PR verification (2026-10-31)

Historical push introducing `vessel-is-empty.ru.md` tested against real Qwen.
Initially it also proposed routine book-status changes; tightened editorial
prompt and repeated: now only `New verse (Ru): Сосуд опустошенный` is proposed.
Binary image assets are supplied as metadata, not treated as missing text diffs.

Real draft PR https://github.com/alchemmist/blog/pull/71 used an explicit
AUTOMATION TEST marker and historical poem output against current main.
Verified exactly one changed file (`updates.md`), +1/-0. Repeat returned the same
PR. Closed without merge and deleted the test branch; repeat after closure did
not reopen PR. Poem public URL returned 200. This tests the actual writer API,
not a full real-new-push publication. CI build status was not awaited.
Writes remain disabled. Automatic URL generation/publication checks and durable
retry handling remain rollout prerequisites, as listed above.

### Four-stage rollout verification

`stages.py` implements separate `/validate`, `/generate`, `/create-pr` endpoints.
Both editorial stages independently call LiteLLM. Negative validation returns an
empty array, stopping n8n without an extra IF node. Generation is restricted to
selected source paths. PR writes are still disabled by deployment configuration.
Signed historical push tests: execution 1781 succeeded and stopped at validation;
execution 1782 succeeded through all four nodes and returned the expected poem
entry in dry-run. Health checks are served in separate threads while a lock
serializes analysis operations; slow inference no longer removes Service endpoints.
No sticky notes are included. These tests do not establish durable delivery or
complete automatic publication/link checks.
