# Qwen image analysis

The previous `--language-model-only` setting deliberately skipped Qwen's vision
encoder. Open Terminal `read_file` can return an image, which Open WebUI forwards
to the model after the tool result. vLLM consequently rejected those requests
with `At most 0 image(s) may be provided in one prompt`.

The pinned RedHatAI/Qwen3.8-27B-INT4 checkpoint supports vision. Its encoder uses
BF16 weights even though the language weights are INT4. The current profile on
the RTX 3090 enables it with these bounds:

- 114688 tokens of total context (112K), including image tokens and output.
- At most eight images in the complete request, including conversation history.
- Images resized to at most 1048576 pixels, approximately 1024 tokens each.
- No video input; one active inference sequence; 2048 batched tokens.
- FP8 KV cache, eager execution and a 95% GPU memory target.
- A 0.25GiB multimodal processor cache per relevant process in host memory.

The gateway still limits request bodies to 4MiB. This applies to the encoded JSON
before image resizing; image count and pixel limits do not bypass it. Compress
large inputs before submission. Raising this limit requires an aggregate memory
budget for queued requests, not just a larger per-request limit.

Live profiling on 2026-10-17 measured 17.71GiB for model loading and 4.1GiB for
KV cache, with capacity for 121856 tokens and 1.06x concurrency at the selected
114688-token limit. The former 131072-token context does not fit this measured
vision configuration. Desktop GPU usage can change the available budget.

## Deployment

The backend values, standalone profile and gateway profile must agree:

- `charts/vllm/values.yaml`
- `deploy/vllm/profiles/qwen3.8-27b.yaml`
- `charts/llm-switcher/files/profiles.json`

The gateway compares live backend arguments against its profile on every
admitted request. Updating only the backend would therefore be reverted.
LiteLLM's advertised context must also match in `deploy/litellm/values.yaml`.

From `ansible/`, use `ansible-playbook -i inventory/hosts.yml playbooks/llm-vision.yml`.
This requires the existing deployed vLLM, model gateway and LiteLLM releases. It
checks that inference is idle, pauses the gateway, upgrades both profiles through
Helm, and updates LiteLLM context metadata while preserving other live settings.
Upgrade failures trigger recovery attempts using the previous Helm revisions.

## Verification

`scripts/check-llm-vision.py` takes `LLM_BASE_URL`, `LLM_API_KEY`, and optional
`LLM_MODEL`. It needs Pillow and sends synthetic random-code images without
reading or modifying user chats. It checks single-image OCR and a two-image
conversation containing a simulated `read_file` result. Both passed through
Open WebUI's configured LiteLLM endpoint after deployment.

Open WebUI's Continue operation can resume an interrupted native tool loop using
the same assistant message ID and stored tool outputs. Regenerate starts a new
attempt and is inappropriate when completed tool work must be retained. Back up
the chat before recovery and verify the existing output prefix afterward.
