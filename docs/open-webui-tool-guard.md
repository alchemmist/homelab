# Terminal validation and repeated failures

Open WebUI receives the correct Open Terminal JSON schema, including the required `target` and `replacement` fields inside `replace_file_content.replacements`. A model can still send `old_text` and `new_text`. Previously the terminal rejected these calls with HTTP 422, echoed their source code in the error, and the model repeatedly rendered the unchanged file.

The managed WebUI middleware now validates native terminal calls against their published schema before execution. Invalid arguments return a short error with missing fields or expected types, without echoing the supplied code. Terminal HTTP 422 responses are also compacted. Valid terminal calls and unrelated tools retain their normal behavior; built-in URL fetching has the deadline described below.

Within one response, three failures of the same tool with the same normalized arguments stop the native tool loop. Successful intervening calls do not erase a recurring failure. The final failed call and an explanatory error remain in the chat; existing files and conversation history are retained. A new response starts with a fresh counter. This detects repeated invalid calls, not every possible form of unproductive reasoning, changed-argument retries, text repetition or runtime failure.

## Repeated valid calls

Long agentic responses are intentionally unbounded (`maxToolCallIterations: -1`): the model may iterate as long as each step makes progress. On 2026-10-24 a Minecraft HTML build entered a degenerative loop for hours: the model repeated byte-identical terminal commands every round, the context gateway summarized away the difference each iteration, and the model replayed the same actions indefinitely. The context compaction alone cannot break such a loop; iteration caps would also punish productive long work.

The guard therefore detects repetition, not duration. Successfully executed valid calls are remembered by a fingerprint of tool name and normalized arguments. When the executed sequence ends with three identical cycles of a short block (period 1, 2 or 3 commands), the next identical call is not executed and the model receives an explicit error: the exact sequence was already run, repeating further will stop the response, verify state differently or finish. If the model immediately repeats the same block again, the tool loop stops with a distinct message; the conversation and files are preserved. A genuinely new command clears the warning, so normal work — changed-argument edits, different commands varied with repeats — is unaffected. Only tracked failures and executed calls count; skipped identical calls do not. The live run was interrupted manually; the Stop button correctly cancelled the active stream, but a fresh full request was posted immediately after each stop (frontend cause under investigation), so pod restart was the reliable way to break the cycle.

## Repeated unresolved calls

A loop can persist without executing anything at all. On 2026-10-24 (second incident, 19:32–21:51 MSK) a single browser request drove a two-hour loop in which the model emitted the same unresolvable tool call every round: `resolve_tool_call` rejected it before execution, the failure never reached `guarded_execute` (so neither the invalid-call nor the repeat-call guard could see it), the terminal stayed silent, and the round repeated at ~90k input tokens per iteration. The context gateway deduplicated tool results, but the loop consumed GPU minutes without any progress.

The patch therefore also records round health at the tool-loop continuation anchor. For every generated response round, `record_no_progress_round` inspects the new output items: a round whose every `function_call_output` carries `status: failed` executed no tool at all. Fingerprints of such degenerate rounds are kept per response; three identical cycles of a period 1–3 pattern stop the tool loop with a message naming the likely fix (tool disabled, name or schema mismatch). Any round with a resolving/executing call clears the pattern, so ordinary retry-then-succeed sequences are unaffected.

The deduplication and compaction of the context gateway remain necessary: they keep this and other loops from growing the context, while the no-progress break terminates them at the WebUI tool loop in bounded time.

The helper and a verified-anchor patch are delivered by the Open WebUI Helm chart. An init container patches the middleware from the pinned image into an ephemeral volume; the original image is unchanged. If an upstream upgrade changes an expected anchor, initialization fails rather than silently losing protection. Disable `toolGuard.enabled` and redeploy to use unmodified upstream middleware.

Apply to an existing installation with `ansible-playbook playbooks/open-webui-tool-guard.yml` from `ansible/`. It preserves existing Helm release values and performs an atomic upgrade. WebUI restarts; the terminal and model do not. Apply `playbooks/open-terminal-instructions.yml` as well to refresh the file-editing guidance.

Run focused checks with `uv run --with jsonschema python -m unittest discover -s tests -p test_webui_tool_guard.py -q`.

The live check runs inside the WebUI container: `kubectl -n llm exec -i deployment/open-webui -- python - < scripts/check-webui-tool-guard.py`. It uses a unique temporary terminal file, verifies three invalid edits never execute, verifies a corrected edit in a new response changes the file, checks failed display produces no card, and removes the fixture. Validation on 2026-10-19 passed against the deployed middleware and real terminal API; 15 focused unit tests also passed. This check exercises the tool execution boundary without asking the model to generate a project.

## Bounded URL fetching

On 2026-10-21 a Thanos documentation response stalled midway through its body. The native `fetch_url` call waited almost two hours until the user stopped it. `web.loader.timeout` was empty, leaving the synchronous Requests loader without a read timeout. Detailed tool state is stored in `chat_message.output`; the legacy `chat.chat` JSON alone does not describe the current execution state.

The same playbook now sets `WEB_LOADER_TIMEOUT` to `15` seconds through the authenticated retrieval configuration API, preserving and verifying all other settings. This is a network inactivity timeout, not a total duration limit.

The guard executes only the built-in, non-direct `fetch_url` in a disposable Python process with a 45-second deadline. The child uses the installed upstream fetch implementation, persisted loader settings, content truncation, and SSRF validation. Timeout or Stop kills and reaps the child, rather than abandoning a blocked worker thread. Empty results and worker failures become explicit tool errors; successful page text retains its original format. Each fetch pays the cost of importing WebUI in the child. Disabling `toolGuard.enabled` removes process isolation, but the persisted 15-second loader setting remains.

Run `uv run --with jsonschema python -m unittest discover -s tests -p 'test_webui*.py' -q`. The fetch tests cover successful and empty responses, failed workers, deadline/Stop cleanup, invalid arguments, and isolation from external/direct tools. Live verification: `kubectl -n llm exec -i deployment/open-webui -- python - < scripts/check-webui-fetch-timeout.py`; it checks the installed middleware, deterministic deadline cleanup, and bounded completion against the original Thanos URL without changing conversation history.
