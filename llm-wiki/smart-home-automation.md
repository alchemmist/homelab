# Умный дом Яндекс: только публичный API

Актуализировано **3 ноября 2026** после согласованного перехода календаря на
фиксированное уведомление. Пользователь запретил внутренние API и обходы.

## Текущая архитектура

- n8n напрямую вызывает `https://api.iot.yandex.net` с IoT OAuth-токеном,
  scopes `iot:view` / `iot:control`. Токен — native credentials, не код нод.
- Лампы/розетки управляются стандартными объявленными умениями публичного API.
- Календарные напоминания: **запуск готового сценария**, не динамический TTS.
  `POST /v1.0/scenarios/{id}/actions`, без тела, с Bearer-токеном.
- Native Header Auth **Yandex IoT Bearer Token**, header `Authorization`.
  Не выдавать это за OAuth2 credential с автоматическим refresh.
- Сценарий **Calendar reminders** содержит фиксированную фразу и громкость 50%.
  Пока фраза **«Напоминания из календаря настроены»**. Изменить её на обычное
  напоминание нужно один раз в официальном приложении **Дом с Алисой**.
  Публичный API не редактирует сценарий; не использовать для этого внутренний.
- Workflow **активен**. Схема:
  `Every Minute → Select Calendars → Get Upcoming Events → Match Due Reminders → Run Fixed Yandex Scenario → Mark Announced`.
- Отдельный voice-сервис, обновление сценария и цикл больше не нужны. Старый
  Cookie/CSRF credential n8n удалён. Glagol и внутренний Quasar запрещены.
- Repo `alchemmist/yandex-voice` архивирован (DELETE не разрешён scope CLI-токена).
  Deployment/Service/Argo/Fleet/chart и старый Kubernetes voice Secret удалены.
  История исходников и незакоммиченные изменения сохранены приватно.

## Что доказано, а не предположено

- Существующий IoT token читает нашу Миди и запускает готовый сценарий.
- Пользователь услышал фиксированную фразу через публичный API. n8n execution
  **1587** проверил тот же POST с native bearer credential и dedup; временный
  scheduled workflow удалён, исходный календарь активирован.
- Прямой `range:volume` даёт 400: умение недопустимо для нашей Миди.
- `quasar` TTS и `audio_player` POST actions дают 400 unknown capability type.
  Наличие audio_player в GET не означает, что public POST умеет им управлять.
- PUT сценария на публичном маршруте дал 404. Динамическое произнесение названия
  встречи через проверенный документированный публичный API не поддерживается.
- Громкость достигается **сохранённым действием сценария**, не прямой публичной
  командой volume. Прежняя громкость не восстанавливается.
- Детали и официальные ссылки: `docs/n8n/yandex-public-api-assessment.md`.

## Владельцы логики и правила

- n8n — пользовательские условия, календарь, уведомления, webhook, домашние правила.
- CronJob Kubernetes — инфраструктурные задачи: бэкапы, метрики, housekeeping.
  Один сценарий — один владелец, не дублировать расписание отдельным pod.
- Прямые HTTP-ноды предпочтительны, если backend был бы только пустым proxy.
  Blog Updates worker остаётся: содержит содержательную проверку и файловую логику.
- Не возвращать обязательные capability-сервисы; старое архитектурное правило
  отменено пользователем. Home Assistant сейчас не требуется.
- Сохранять JSON, renderer, тесты и документацию. `sync.py` запрещает непубличные
  HTTP URL и требует native bearer credential; меняет только inactive workflow.
- Поведение фиксированной фразы согласовано; не обещать названия событий в речи.
  Только явные popup overrides; календарные defaultReminders не разворачиваются.
  Нужные календари primary + Y-team задаются локальным mapping вне git.
- Dedup после `status=ok`, best-effort, не exactly-once. Принятый API запрос не
  равен доказанному звуку. Не говорить тестовые фразы без предупреждения.
- Runbook: `docs/n8n/setup.md`; source: `docs/n8n/calendar-voice-reminder.json`;
  renderer: `scripts/n8n/sync.py`; тесты: `tests/n8n/`.
