# Single-GPU model serving

Qwen3.8-27B INT4 (`qwen3.8-27b`) is the only installed model and the Open WebUI default. It uses 114688 tokens of context, a suggested output allowance of 16384 tokens and a 95% GPU-memory target on the RTX 3090.

Image analysis is enabled for up to eight images per request with a 1MP processing cap; video is disabled. See [vision configuration](llm-vision.md).

The path is Open WebUI/client -> LiteLLM -> `llm-switcher` -> vLLM. The gateway admits one inference stream at a time. Profiles are allowlisted in `charts/llm-switcher/files/profiles.json`; the Qwen profile is also the vLLM chart default and is preserved in `deploy/vllm/profiles/qwen3.8-27b.yaml`. Unknown models are rejected rather than silently mapped to Qwen.

The scheduler retains support for future profiles: 90 seconds of grace for tool continuations and a 600-second batch window before another waiting model gets a turn. Active responses are never interrupted by scheduling. With only Qwen installed there are no model switches.

There is no durable job queue. Up to 32 in-flight handlers are admitted, bodies are limited to 4 MiB, queue waiting has a 5400-second deadline and loading/inference has a separate 1800-second deadline. LiteLLM permits 7200 seconds and enables `cancel_on_disconnect`. A disconnected client releases its waiting request; this was verified through LiteLLM. Restarting the gateway can interrupt clients, so upgrades should drain active requests first.

The internal gateway requires the backend bearer key. Its NetworkPolicy admits only LiteLLM; RBAC permits only get/patch on `llm/deployments/vllm`. It cannot read Secrets or create pods. Only synchronous Chat Completions, Completions and Responses inference are forwarded; background Responses are rejected.

Deployment: `ansible-playbook playbooks/litellm.yml` from `ansible/`. Initial GPU deployment remains `playbooks/llm.yml`. Preserve the Qwen cache PVC and API Secrets.

Validation covers authentication, invalid model rejection, serialization, failure cleanup, model batching, fairness, cancelled waiters and queue expiration in `tests/test_llm_switcher.py`. Live Qwen tool rounds were admitted in 0.2 and 0.0 seconds without reloading the model. An earlier request waited 770.4 seconds without timing out.

Open WebUI disables unrelated skills/tasks/notes/automation tools for the coding model and retains terminal/file tools. Tool iteration count is unlimited (`CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS=-1`), as requested by the user. Tag and follow-up generation are disabled.

GLM-4.7-Flash was removed at the user's request on 2026-10-16 after repeated generation loops. Its serving profile, model registrations and downloaded checkpoint were removed; existing conversations remain as history.
