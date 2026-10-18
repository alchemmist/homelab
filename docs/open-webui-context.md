# Open WebUI context compaction

Open WebUI v0.12.3 has native context compaction, including between native tool-call rounds. It is disabled by default. The homelab configuration enables it at 75,000 tokens, caps model-specific thresholds at the same value, and retains 40 percent of recent messages at valid turn/tool boundaries. This leaves headroom below Qwen's 114,688-token context for its 16,384-token output allowance and new tool results. The threshold is not an exact request-size guarantee: token estimates and large individual tool results can still exceed the budget.

Apply the persisted settings without restarting WebUI or inference:

```sh
cd ansible
ansible-playbook playbooks/open-webui-compaction.yml
```

The normal `open-webui.yml` deployment also imports this playbook. The helper merges the live chat configuration through the administrative API, preserves unrelated tool settings, and verifies readback. It requires one administrator without an MFA requirement. With MFA, use the authenticated administration interface. Repeated application reports no changes.

The compaction prompt requests a factual continuation checkpoint with goals, constraints, verified results, artifact paths, failures and pending work. It explicitly distinguishes summarizing a transcript from continuing its task. The configured compaction model, or the conversation model when none is selected, generates the checkpoint.

Compaction does not delete saved conversation history or terminal files. It stores a `contextSummary` checkpoint that replaces earlier messages only in the model's active context. Keep a private backup before recovering a previously overflowing chat and inspect the generated checkpoint before resuming.

In v0.12.3, manual branch compaction formats saved assistant prose but can omit native tool calls/results stored in `output`. Preserve relevant verified paths and tool state explicitly when recovering such a chat. Automatic compaction within the tool loop receives expanded tool messages. A successful compaction HTTP response alone is not evidence that its summary preserves enough information.

References:
- https://docs.openwebui.com/troubleshooting/context-window/
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/utils/context_compaction.py
