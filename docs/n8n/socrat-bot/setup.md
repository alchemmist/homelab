# Socrat bot: алерты в Telegram

Workflow принимает webhook Alertmanager, складывает firing и resolved одной группы в один текст и отправляет его во внутренний API бота. Кнопка в сообщении одна: тип `alert.silence`, подпись `Silence for 1h`. Матчеры берутся из общих меток группы, а если их нет — из меток алерта. Ключ идемпотентности — отсортированные fingerprint этой группы.

JSON: `docs/n8n/socrat-bot/workflow.json`. Чарт и адреса: `llm-wiki/socrat-bot.md`.

## Импорт

1. Открыть `https://n8n.socrat.alchemmist.xyz`.
2. **Workflows → Import from File** и выбрать `docs/n8n/socrat-bot/workflow.json`.
3. Не включать workflow, пока в n8n не задан credential ниже.
4. После правки в UI экспортировать JSON обратно в этот файл. Значение credential в git не попадает.

Имена нод на английском: **Alertmanager Webhook**, **Group Firing and Resolved**, **Post Telegram Message**. Webhook слушает путь `socrat-alerts`. Alertmanager уже шлёт на `https://n8n.socrat.alchemmist.xyz/webhook/socrat-alerts` и просит `send_resolved: true`. В его конфиге нет пароля и токена.

n8n отвечает Alertmanager сразу, затем нода **Post Telegram Message** делает `POST http://socrat-bot.socrat-bot.svc:8080/v1/messages`.

## Credential только в n8n

Заголовок `X-Internal-Token` в JSON оставлен выражением `{{$credentials.socratBot.internalToken}}`. `chat_id` — `{{$credentials.socratBot.ownerChatId}}`. Это заглушки: в файле нет ни токена, ни chat id.

Сам credential живёт только в n8n. После импорта задать его в UI ноды **Post Telegram Message**:

- `internalToken` — значение ключа `INTERNAL_TOKEN` из Secret `socrat-bot-env`;
- `ownerChatId` — число из ключа `TELEGRAM_OWNER_ID` (для личного чата владельца это и есть `chat_id`).

Если выражение `$credentials.socratBot` в этом экземпляре n8n не резолвится, заменить заголовок на Header Auth с именем `X-Internal-Token` и подставить `chat_id` из того же credential. В git по-прежнему остаются заглушки, не значения.

## Токен бота не попадает в Grafana

`TELEGRAM_BOT_TOKEN` лежит только в Secret `socrat-bot-env` и читается процессом бота. Grafana, Alertmanager и этот workflow его не получают. В Grafana не добавлять контакт Telegram и не вставлять токен в contact point. Доставка идёт так: Alertmanager → публичный webhook n8n без учётки → кластерный `POST /v1/messages` с внутренним токеном.

## Голос и красный свет

Их в этом файле пока нет. Когда они появятся, ноды остаются в этом же workflow, следом за текстом алерта: отдельный workflow для станции и лампы не заводится. Календарные напоминания по-прежнему живут в `docs/n8n/calendar-voice-reminder.json` и сюда не переносятся.
