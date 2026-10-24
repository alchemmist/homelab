# Exact context budgeting for Qwen chats

The inference gateway checks every `/v1/chat/completions` request after Open WebUI and LiteLLM have assembled the messages, tool definitions and images. It asks the running vLLM `/tokenize` endpoint for the actual chat-template token count. The pinned Qwen renderer counts expanded image tokens and tool definitions; documents, reasoning settings and template options are forwarded consistently.

Compaction starts when the request no longer fits the model window together with the requested output allowance (in practice above roughly 98,000 input tokens for the default 16,384-token answer), and its target is at most 90,000 input tokens within the 114,688-token model window. Short chats are not padded or compacted. Whole tool-call/result groups are retained where possible; a large boundary result is shortened to retain as much useful recent context as fits. The first user goal and latest request are carried into the checkpoint.

Old images are the first eviction priority once compaction is triggered. The latest visual message/tool batch and images in the latest text-bearing user request are retained initially; older image parts become text markers. If this frees enough room, all text is preserved and no summary is generated. Otherwise textual compaction follows. Images remain in saved chat history and file storage. This policy deliberately permits an active context smaller than 90,000 tokens rather than keeping obsolete screenshots just to fill the budget.

Older history is summarized directly by vLLM while the gateway owns the inference slot, avoiding a recursive call through the scheduler. Summaries must end with an "Already attempted" list of tool calls tried so far and their outcomes, so a continuation does not repeat completed work. Summary requests are independently token-counted and bounded. A small in-memory LRU caches repeated summaries. On summary failure, deterministic pruning continues automatically. Older images, large tool output and historical text can be omitted; extreme inputs can require dropping tool definitions or shortening instructions. These are lossy transformations of the active request, not edits to saved chats or terminal files. Published artifacts remain unchanged.

Before token counting, tool results whose full text is byte-identical to a later identical result are replaced with a short duplicate marker; the newest copy remains in full. Repeated identical verification output is the main fuel of context growth in long agent loops, and collapsing it slows that growth without losing the informative latest copy.

The final request is counted again before inference. Context-related backend rejections are intercepted before response streaming and retried with smaller budgets. A tokenizer/backend outage can still produce an infrastructure error; oversized verified payloads are never knowingly dispatched. Other APIs (`/v1/responses` and `/v1/completions`) retain their existing behavior and are outside this chat-budget contract. The existing 64 MiB HTTP body limit is separate from the token budget.

The multimodal processor cache is disabled in both the vLLM chart and gateway model profile (`--mm-processor-cache-gb 0`). With vLLM 0.31.0, a long image history caused `/tokenize` to return HTTP 500 with `AssertionError: Expected a cached item for mm_hash`: an entry classified as a hit was no longer available when merging image tensors. Disabling this cache avoids that path; image preprocessing is repeated and can take longer. This does not disable image support or the text KV/prefix cache. Gateway error logs identify the failure stage and tokenizer HTTP status without logging chat contents.

The failing chat's 27-image payload reproduced that HTTP 500 before the change and passed three consecutive tokenization checks afterward (23,230 tokens). A live image-priority check combined those images with a long text context: 105,746 tokens became 83,804, keeping the newest image and every text message unchanged, with no summary generation. Saved files and chat messages were not edited.

Open WebUI's native percentage-based compaction is disabled to avoid a second, more aggressive reduction to 40 percent of messages. Full saved history remains in WebUI, while only the outgoing inference payload is compacted. The gateway exposes `X-Context-Input-Tokens` and `X-Context-Compacted` response headers and a `context_compactions` counter in its authenticated status endpoint. The process does not ask users for confirmation.

Deploy the gateway, wait for readiness, and then configure WebUI:

```sh
cd ansible
ansible-playbook playbooks/llm-context-budget.yml
```

When the single model profile is unchanged, the chart uses a rolling gateway update: the new pod becomes ready before the old pod drains its active response. If model profiles change or multiple models are configured, the playbook requires idle inference and the chart uses Recreate to avoid competing model switches. The context playbook does not itself restart vLLM or change model arguments. `open-webui-compaction.yml` applies only the WebUI side. The local administrative helper preserves unrelated chat settings and requires a single administrator without MFA; with MFA, use the authenticated administration interface.

Validation covers exact recount, output reserve, tool pairs, oversized individual results, summary failures, retention near the target, images, retry before streaming, history immutability and request admission cleanup. Live vLLM checks counted a 120,012-token input despite its 114,688-token window and counted a 512px image as part of the prompt.

On 2026-10-18, a live request with 198,085 input tokens and a 16,384-token output allowance was compacted to exactly 90,000 input tokens. vLLM confirmed `prompt_tokens: 90000` and returned the requested `CONTEXT_BUDGET_OK` marker. The same request through WebUI's configured LiteLLM endpoint also succeeded with 90,000 prompt tokens. The saved conversation history was not involved in this synthetic test.

References:
- https://docs.openwebui.com/troubleshooting/context-window/
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/utils/context_compaction.py
