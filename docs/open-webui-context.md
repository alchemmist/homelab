# Exact context budgeting for Qwen chats

The inference gateway checks every `/v1/chat/completions` request after Open WebUI and LiteLLM have assembled the messages, tool definitions and images. It asks the running vLLM `/tokenize` endpoint for the actual chat-template token count. The pinned Qwen renderer counts expanded image tokens and tool definitions; documents, reasoning settings and template options are forwarded consistently.

Compaction starts above 95,000 input tokens, or earlier if the requested output allowance requires it. Its target is at most 90,000 input tokens, leaving room for the normal 16,384-token answer within the 114,688-token model window. Short chats are not padded or compacted. Whole tool-call/result groups are retained where possible; a large boundary result is shortened to retain as much useful recent context as fits. The first user goal and latest request are carried into the checkpoint.

Older history is summarized directly by vLLM while the gateway owns the inference slot, avoiding a recursive call through the scheduler. Summary requests are independently token-counted and bounded. A small in-memory LRU caches repeated summaries. On summary failure, deterministic pruning continues automatically. Older images, large tool output and historical text can be omitted; extreme inputs can require dropping tool definitions or shortening instructions. These are lossy transformations of the active request, not edits to saved chats or terminal files. Published artifacts remain unchanged.

The final request is counted again before inference. Context-related backend rejections are intercepted before response streaming and retried with smaller budgets. A tokenizer/backend outage can still produce an infrastructure error; oversized verified payloads are never knowingly dispatched. Other APIs (`/v1/responses` and `/v1/completions`) retain their existing behavior and are outside this chat-budget contract. The existing 64 MiB HTTP body limit is separate from the token budget.

Open WebUI's native percentage-based compaction is disabled to avoid a second, more aggressive reduction to 40 percent of messages. Full saved history remains in WebUI, while only the outgoing inference payload is compacted. The gateway exposes `X-Context-Input-Tokens` and `X-Context-Compacted` response headers and a `context_compactions` counter in its authenticated status endpoint. The process does not ask users for confirmation.

Deploy the gateway, wait for readiness, and then configure WebUI:

```sh
cd ansible
ansible-playbook playbooks/llm-context-budget.yml
```

The playbook waits for current gateway work to finish before rolling out; it does not restart vLLM or change model arguments. `open-webui-compaction.yml` applies only the WebUI side. The local administrative helper preserves unrelated chat settings and requires a single administrator without MFA; with MFA, use the authenticated administration interface.

Validation covers exact recount, output reserve, tool pairs, oversized individual results, summary failures, retention near the target, images, retry before streaming, history immutability and request admission cleanup. Live vLLM checks counted a 120,012-token input despite its 114,688-token window and counted a 512px image as part of the prompt.

On 2026-10-18, a live request with 198,085 input tokens and a 16,384-token output allowance was compacted to exactly 90,000 input tokens. vLLM confirmed `prompt_tokens: 90000` and returned the requested `CONTEXT_BUDGET_OK` marker. The same request through WebUI's configured LiteLLM endpoint also succeeded with 90,000 prompt tokens. The saved conversation history was not involved in this synthetic test.

References:
- https://docs.openwebui.com/troubleshooting/context-window/
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/utils/context_compaction.py
