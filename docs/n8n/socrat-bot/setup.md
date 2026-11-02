# Socrat alerts to Telegram

The workflow receives one Alertmanager group, turns firing and resolved alerts into one English text, and posts it to `http://socrat-bot.socrat-bot.svc:8080/v1/messages`. The button is `alert.silence`, labeled `Silence for 1h`. The idempotency key is the sorted fingerprints of the group.

JSON: `docs/n8n/socrat-bot/workflow.json`. Chart and addresses: `llm-wiki/socrat-bot.md`.

Live workflow name: `Socrat Alerts` (active). The HTTP node uses the n8n credential `Socrat bot internal` (`httpHeaderAuth`, header `X-Internal-Token`). That value is not in Git. `ownerChatId` in the code node is `0` until `TELEGRAM_OWNER_ID` is known. With `0`, the bot returns a bad gateway and the n8n execution is an error.

Alertmanager receiver `socrat-bot` posts to `https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts` with `send_resolved: true`. The bot token never goes into Grafana. Voice and the red light stay in this same workflow when they are added.

A repeat webhook with the same fingerprints must reuse the action idempotency key so the bot does not send a second card.
