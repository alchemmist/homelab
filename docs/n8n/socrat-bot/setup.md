# Socrat alerts to Telegram

The workflow receives one Alertmanager group and posts each alert on its own to `http://socrat-bot.socrat-bot.svc:8080/v1/messages` as `{chat_id, alert}` with `status`, `labels`, and `annotations`. The bot renders the card, chooses links, and adds Mute 15m, Mute 30m, and Mute 1h. n8n does not build URLs.

JSON: `docs/n8n/socrat-bot/workflow.json`. Chart and addresses: `llm-wiki/socrat-bot.md`.

Live workflow name: `Socrat Alerts` (active). The HTTP node uses the n8n credential `Socrat bot internal` (`httpHeaderAuth`, header `X-Internal-Token`). That value is not in Git. `ownerChatId` in the code node is `891074228`.

Alertmanager receiver `socrat-bot` posts to `https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts` with `send_resolved: true`. The bot token never goes into Grafana.

A repeat of the same object edits the existing Telegram message. A resolved alert updates that message and removes the mute buttons. The next firing after resolve is a new message.
