# PostgreSQL Socrat: рабочая карта

Срез после переключений 20 ноября 2026. Описание для пользователей — [страница wiki](https://wiki.socrat.alchemmist.xyz/platform/postgresql/), эксплуатация и ротация CA — [runbook](../docs/postgres-platform.md). Владелец конфигурации — `charts/postgres-platform`, Argo Application `postgres-platform`, namespace `postgres`.

| Адрес записи внутри кластера | БД → сервис | Контракт |
|---|---|---|
| `pg-common-rw.postgres.svc.cluster.local:5432` | `umami`, `lms`, `certification`, `socrat` (бот), `litellm`, `registry` (Harbor) | Обычно primary на NVMe `socrat-0`, async standby на HDD `socrat-5`. Подтверждение не ждёт HDD; аварийное повышение может потерять ещё не доставленный WAL. |
| `pg-critical-rw.postgres.svc.cluster.local:5432` | `authentik` | Три экземпляра на `socrat-0/1/5`; `synchronous_commit=on`, `ANY 1`, `dataDurability=required`, `failoverQuorum=true`. Потеря всех standby блокирует подтверждения; не ослаблять настройки автоматически. |

Фактический primary определяет CNPG (`.status.currentPrimary`); после переключения нода может отличаться от исходной. Клиенты используют проверку имени TLS и отдельные роли. `lms-ha` выведен из эксплуатации; его CronJob удалён. По отдельному решению владельца PVC, PV и локальные каталоги `lms-ha-1/2/3` окончательно удалены. Ночные физические копии и тест восстановления: [runbook](../docs/postgres-physical-backups.md). WAL архивируется на socrat-3; PITR каждого кластера проверен между двумя транзакциями. По обе стороны смены timeline окно не считать подтверждённым без отдельного теста. При деградации начать с `up{job="postgres-platform"}`, состояния репликации и места на **реальной** ФС; `Bound` у PVC не означает, что место физически свободно.

## Закрытие миграции: не путать приёмку с хранением

- Владелец подтвердил ручную проверку LMS после исправления маршрута на вход: всё работает. Приёмка пользовательского входа закрыта по подтверждению владельца, а не по HTTP-редиректу или административной сессии.
- Старые источники: из исторических 9 PVC экспериментальные 3 удалены; оставшиеся 6 сверены по UID/PV и `Bound`, активных подов-потребителей не обнаружено; прямой mount старого hostPath Umami не найден. Операционное решение — **удерживать**, а не удалять сейчас. [Задача на ревизию после 2026-12-05 UTC](https://github.com/alchemmist/homelab/issues/216) содержит условия отдельного решения; это не таймер удаления. [Инвентарь](../docs/postgres-retained-pvcs.tsv).
