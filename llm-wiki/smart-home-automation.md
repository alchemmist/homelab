# Умный дом Яндекс: публичный API и узкое исключение для озвучки

Актуализировано **3 ноября 2026**. Пользователь разрешил внутренний API **только
для динамических календарных уведомлений с автоматическим обновлением сессии**.
Не распространять исключение на остальные интеграции.

## Каналы

- Лампы, розетки, обычные сценарии — публичный `api.iot.yandex.net`, IoT OAuth
  scopes iot:view/iot:control, native credentials.
- Календарь → Станция Миди — native **CUSTOM.yandexStation** в n8n. Внутри
  x-token login → Cookie/CSRF в памяти → update dedicated scenario → execute.
- Старый yandex-voice/Glagol/HTTP proxy не возвращать. Native node — содержательная
  авторизация, обновление, сериализация и обработка ошибок, не дополнительный pod.
- Код ноды/credential/client: `charts/n8n/extensions/`, read-only ConfigMap mount.
  Пин базового образа сохранён, deployment Recreate предотвращает двух SQLite writers.

## Активные workflow

1. Календарь: `Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Announce via Yandex Station → Mark Announced`.
   Динамическая фраза «Через … начинается “Название”», 50% громкости, без возврата
   прежней. Токен/персональные IDs — `yandexStationApi` credential, не JSON.
2. **Yandex Session Maintenance**: каждые 15 минут, silent check реального PUT без
   исполнения. Здоровая сессия переиспользуется до 6 часов; 401/403 подготовки
   запускает однократное обновление. Cold start после рестарта тоже автоматический.

Cookies/CSRF не сохраняются в outputs/logs. Revoked x-token нельзя восстановить без
авторизации пользователя: будет явная ошибка X_TOKEN_REJECTED. Обновить credential
в обоих workflow через поддерживаемые UI/API, никогда не редактировать SQLite.
При смене token ключ кэша меняется, следующая операция логинится заново.

## Наблюдаемость

Grafana **Automation / Yandex calendar**: финальная ошибка session/announcement
(окно 20 минут) и отсутствие успешного maintenance 40 минут. Sanitized events в
Loki; никаких токенов, заголовков, upstream response body или названий встреч.
Receiver **Yandex calendar via Socrat Alerts** → существующий Telegram bot.
Он не зависит от Яндекс-сессии, но зависит от n8n: полный отказ n8n может задержать
доставку. Не выдавать этот маршрут за независимый от всей платформы.

Источники: `docs/n8n/yandex-session-alerts.json` и
`scripts/n8n/provision_yandex_alerts.py`. Глобальная notification policy не менялась.
Live checks: 1804 auth, 1809 dynamic voice, 1817 maintenance, 1819 Socrat Alerts;
Grafana contact test 200, обе rule evaluations Normal/ok. 28 тестов проходят.

## Почему не public-only для речи

Публичный token читает Миди и запускает готовый сценарий. Но прямой volume дал
400 invalid capability для устройства, TTS/audio_player — 400 unknown capability
**type**, PUT сценария — 404. GET metadata audio_player не означает доступный POST.
Фиксированный сценарий работал, но не произносил название встречи. Проверки:
`docs/n8n/yandex-public-api-assessment.md`. Эта история не должна возвращать старый
запрет на согласованное выше исключение или разрешать внутренний API вообще везде.

## Границы

- n8n — пользовательские условия; CronJob — инфраструктурные задачи, без дублей.
- Предпочитать прямые API/nodes; не плодить пустые capability proxy. Blog worker
  остаётся ради реальной проверки диффов/файловой логики.
- Primary не включает Y-team. Только explicit popup overrides; defaults пока не
  разворачиваются. Dedup best-effort: не обещать exactly-once или outage replay.
- Не ретраить неоднозначный POST запуска; не считать HTTP 200 с JSON error успехом.
- Не говорить тестовые фразы без предупреждения. Разводить silent auth check и speech.
- Workflow JSON, renderer, тесты, alert rules и wiki отражать в git.
- Старый repo yandex-voice архивирован, workloads/chart/Secret удалены. Приватный
  архив сохранил исходники с незакоммиченными изменениями; удалять его не нужно.
- Полный runbook и ручное восстановление: `docs/n8n/setup.md`.
