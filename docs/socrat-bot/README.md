# Socrat Bot

Socrat Bot connects the cluster to Telegram: it delivers alert cards to approved subscribers and lets the owner send announcements to people who opted into a topic.

- **In Telegram:** open the bot and use `/start` to select interests. Select **Alerts** to request alert delivery; it requires owner approval. `/unsubscribe` stops alert delivery without revoking that approval.
- **From a cluster service:** use the internal API, not the public Telegram webhook. The [Socrat Bot wiki page and OpenAPI reference](https://wiki.socrat.alchemmist.xyz/platform/socrat-bot/) describes the endpoints and how to call them.
- **To change the bot:** its implementation and `openapi.yaml` live in the [Socrat Bot repository](https://github.com/alchemmist/socrat-bot). This homelab repository owns the [deployment and integration runbook](operations.md).
