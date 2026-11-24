# LiteLLM proxy env-only runtime wiring

The LiteLLM proxy (pinned image `harbor.socrat.alchemmist.xyz/homelab/litellm`,
tag `eb6e7f61e4fa0fa1425461e4e92145c8eab73bef@sha256:b39c5a8c...`, upstream
BerriAI/litellm 1.105.1) has, by upstream design, one configuration interface
for runtime credentials: environment variables referenced from the proxy config
via `os.environ/<NAME>`. There is no file-based alternative for these values.
See `deploy/platform/litellm/values.yaml` (`proxy_config.general_settings`:
`master_key: os.environ/LITELLM_MASTER_KEY`, `coordination_redis:
os.environ/COORDINATION_REDIS_URL`, `model_list[].litellm_params.api_key:
os.environ/VLLM_API_KEY|VENICE_BRIDGE_API_KEY|DEEPSEEK_PROXY_API_KEY`),
`environmentSecrets: [litellm-env]` (envFrom secretRef) and `extraEnvVars`
(GENERIC_* OIDC binding from secret socrat-authentik-litellm via secretKeyRef).
Upstream reference: https://docs.litellm.ai/docs/proxy/configs (all keys accept
`os.environ/...` references) and the vendored chart `templates/deployment.yaml`,
which exports `environmentSecrets` only as `envFrom` secretRefs.

Concretely, on the `litellm` Deployment:
- `LITELLM_MASTER_KEY` (secret litellm-env) — proxy auth master key.
- Database credentials (`DATABASE_URL` with `sslcert=/etc/pg-common/ca.crt`) —
  wired by the chart from `db.secret.name: litellm-pg-common` via env.
- `COORDINATION_REDIS_URL`, `VLLM_API_KEY`, `VENICE_BRIDGE_API_KEY`,
  `DEEPSEEK_PROXY_API_KEY` and the GENERIC_* OIDC client bindings — all
  `secretKeyRef` env entries consumed through the proxy's `os.environ/`
  interface, plus the whole `litellm-env` secret exported via envFrom.

Secrets are managed out-of-band (externally-managed runtime secrets, the same
registration class as the harbor/netbird/monori image env contracts).

Container hardening applied in the same pass (values `securityContext` /
`podSecurityContext`): `runAsNonRoot`, uid/gid 1000, all capabilities dropped,
`seccompProfile: RuntimeDefault`, `readOnlyRootFilesystem: true` — the latter is
a first-class supported mode of the vendored chart, which provisions dedicated
`emptyDir`s at `/tmp`, `/.cache` and `/.npm` when the flag is set (see
`charts/litellm/templates/deployment.yaml`). The proxy binds :4000 (>1024),
so no privileged binding is needed.

Release isolation (NetworkPolicy `litellm-isolation` in namespace `llm`):
ingress on :4000 only from edge traefik and the monitoring namespace; egress
limited to platform postgres :5432, shared redis :6379, in-cluster model
backends (vllm :8000 via its real `app: vllm` pod label, venice-api :8080,
deeperseeker :4000), authentik-server :443/:9443 (OIDC issuer) and DNS.
Operator-managed runtime pods (cnpg postgres instances, monitoring-stack
prometheus) are scoped by their dedicated namespaces instead of pod labels,
because those pods are not rendered by any offline Helm source.
