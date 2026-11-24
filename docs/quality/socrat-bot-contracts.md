# Socrat Bot runtime env contract

The socrat-bot release (`charts/socrat-bot`, pinned image
`harbor.socrat.alchemmist.xyz/homelab/socrat-bot`, tag
554df3ff..., namespace socrat-bot) runs the Telegram bot. It reads its entire
runtime configuration from environment variables; there is no file-based
configuration interface for these values. The chart's
`socrat-bot.secretEnv` helper binds each credential as a `secretKeyRef` env
entry (from the configured `envSecret` / `databaseSecret`):
- `DATABASE_URL` - postgres connection string (pg-common),
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_OWNER_ID`,
  `INTERNAL_TOKEN` - the bot + webhook + internal API tokens.

The image defaults to uid 65532 (non-root) and runs the module
`python -m socrat_bot`; Docker-verified it imports and starts as uid 65532
under a read-only root filesystem. Container hardening (runAsNonRoot,
read-only rootfs, drop ALL, RuntimeDefault) was applied in the same pass.

Secrets are managed out-of-band (externally-managed runtime secrets, the same
registration class as the litellm/harbor/grafana/monori env contracts).
