# Socrat alerts to Telegram

The workflow receives one Alertmanager group and posts each alert on its own to `http://socrat-bot.socrat-bot.svc:8080/v1/messages` as `{chat_id, alert}` with `status`, `labels`, and `annotations`. The bot renders the card, chooses links, and adds Mute 15m, Mute 30m, and Mute 1h. n8n does not build URLs.

JSON: `docs/n8n/socrat-bot/workflow.json`. Chart and addresses: `llm-wiki/socrat-bot.md`.

Live workflow name: `Socrat Alerts` (active). The HTTP node uses the n8n credential `Socrat bot internal` (`httpHeaderAuth`, header `X-Internal-Token`). That value is not in Git. `ownerChatId` in the code node is `891074228`.

Alertmanager receiver `socrat-bot` posts to `https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts` with `send_resolved: true`. The bot token never goes into Grafana.

A repeat of the same object edits the existing Telegram message. A resolved alert updates that message and removes the mute buttons. The next firing after resolve is a new message.

## Authenticated durable SPI handoff

The original workflow ID is preserved. `Alertmanager Webhook` is now native
`CUSTOM.socratAlertWebhook`, using encrypted `socratAlertIngress` and worker Header
Auth credentials. It validates bearer auth, excludes request headers from execution
data, sanitizes the alert group and durably queues SPI before HTTP acknowledgment.
If queuing fails, HTTP503 requests sender retry while sanitized Telegram processing
still runs. Repeated deliveries edit the existing card and do not duplicate SPI jobs.

Grafana contact points and Alertmanager use an independent ingress bearer Secret;
Alertmanager mounts `spi-alert-ingress` via a credentials_file, never inline git data.
The legacy unauthenticated Telegram-only migration switch is OFF. Do not re-enable
it as a permanent workaround. An unauthenticated POST must return HTTP401.

Slow analysis is in the separate active **SPI Incident Triage** workflow. Queue and
publication are not dependent on a successful Telegram API response. GitHub titles,
descriptions and generated comments MUST be English, with `[SPI]` title prefix.
SPI publication is enabled after dry-run verification; the unrelated blog remains
dry-run. Full design, limits, credentials and recovery: `../spi/setup.md`.
