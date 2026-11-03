# LMS: кабинет курса

Срез на **2 ноября 2026**. Памятка, не замена проверки живого пода. Секреты клиента и пароли сюда не писать.

## Где это живёт

| Что | Где |
| --- | --- |
| Код | репозиторий `alchemmist/lms` |
| Сайт ученика | Hugo + тема hugo-docs. Это не React-прототип в `teacher/` |
| API | FastAPI, `backend/app` |
| База | PostgreSQL `lms-postgres`, Secret `lms-db`, ключ `LMS_DATABASE_URL` |
| Образ | `ghcr.io/alchemmist/lms` |
| Выкладка | `.github/workflows/publish-image.yml` → `alchemmist/deploy-to-socrat@v1` пишет `image.tag` и `image.digest` в `deploy/lms/values.yaml` и `charts/lms/values.yaml`. Argo CD application `lms` синкает chart |
| Адрес | https://lms.alchemmist.xyz |
| Локально | `http://localhost:8000`. `127.0.0.1` даёт 403: local mode сверяет Host с `LMS_PUBLIC_URL` |

Последний успешно выкатанный образ этой сессии: tag `521b39731a7e0a837418532580a300e8d6a30775`, digest `sha256:55f7befcea8046177aea2465c6ab8edd5be4adc28a2363a0c0ee322aad11cf64`. Под Ready. Workflow **Checks** при этом часто красный: `runner/tests/test_catalog.py` ждёт 78 задач, в дереве их сотни. На публикацию образа это не влияет. Публикация падает отдельно, если падают backend/OIDC тесты, и тогда tag в homelab не меняется.

## Вход

Только Authentik. Своих паролей LMS не хранит.

- Issuer: `https://auth.socrat.alchemmist.xyz/application/o/lms/` (слэш в конце обязан совпасть).
- Client id: `socrat-lms`. Redirect: `https://lms.alchemmist.xyz/auth/callback`.
- Scope: `openid profile email groups`. Groups в ID token — список имён. Выражение маппинга должно возвращать `{"groups": [group.name ...]}`, не голый список.
- Неавторизованный заход сразу уходит на Authentik (`/login` → `/auth/login`), без кнопки на промежуточной странице. Так только когда issuer и секрет заданы.
- Допуск: пересечение групп токена с `LMS_OIDC_ALLOWED_GROUP` (по умолчанию `lms-students`, список через запятую) или с `LMS_OIDC_TEACHER_GROUP` (по умолчанию `lms-teachers`). Роль пишется в сессию. Если человек в обеих группах, он учитель.
- `alchemmist` добавлен в `lms-teachers` и остаётся учителем. Тестовый ученик Authentik: логин `lms-student`, только группа `lms-students`. Пароль в git не хранить.
- После смены групп нужен новый вход: старая сессия помнит старую роль. Роль пользователя в таблице `users` обновляется при логине.

Секрет клиента: `socrat-authentik-lms` в namespace `lms`. Политика приложения Authentik пускает `homelab-owner` и `lms-students`. Группа `lms-teachers` заведена живьём и записана в `deploy/identity/services.json`; ansible сам по git push не бежит.

## Что видит человек

Интерфейс английский: Sign in, Sign out, Submit solution, View solution, View tests, поиск, ошибки API. Названия курса, блоков, уроков и сам текст остаются русскими.

Роль и Sign out стоят одной строкой в правом нижнем углу. Они берутся из `data-role` на `<html>`, который бэкенд вписывает при отдаче страницы, и не ждут отдельный круг до `/api/session`.

Учитель на странице задачи видит те же Submit solution плюс View solution и View tests. Панель выезжает справа поверх страницы. Повтор той же кнопки или клик мимо панели её закрывает. Решение — блок кода Python в классах chroma темы, без заголовка и кнопки Close. Тесты — таблица Input / Expected на всю ширину панели, без колонки Origin.

Справочник решений не читает базу генератора. Он запечён в образ: `backend/app/data/reference.json`. На момент сборки там было около 22 задач с сохранённым текстом решения, из них 4 сертифицированы. Остальные в панели пустые. Ученик этот API получает 403.

## Открытие уроков

Таблица `lesson_access` (`lesson_path`, `user_id`). Ученик видит в меню только открытые ему уроки; прямой URL закрытого урока — 404. Пока ни одного гранта нет, меню ученика пустое. Учитель видит всё. Local mode (`LMS_AUTH_MODE=local` на loopback) фильтр не включает, иначе локальный кабинет был бы пустым.

Управление на странице Textbook, перед текстом урока: теги имён, **+** открывает список ещё не добавленных учеников, **Add** пишет грант, крестик по наведению снимает. В списке только пользователи, которые уже входили как student. Учитель после нового входа в этот список не попадает.

## Чего не коммитить вместе с LMS

В рабочем дереве `lms` лежат сотни правок `statement.md`, незакоммиченный `migration/pipeline.py` и отдельный прототип `teacher/`. Это не сайт ученика и не образ, пока специально не закоммичено. Генератор описан в [lms-generation.md](lms-generation.md).

## Копия базы в HA-кластер

Продакшен-веб по-прежнему ходит в `lms-postgres`. Чарт умеет выключить этот Deployment через `database.legacyReplicas` и, когда `database.ha.enabled: true`, примонтировать CA `lms-ha-ca` в `/etc/postgres-ca`. По умолчанию HA выключена. Веб-Deployment катится стратегией Recreate: очередь сдачи работ живёт в процессе, два веб-пода одновременно нельзя.

`scripts/lms-ha-copy.py` создаёт разовый Job `postgres:17`. Он читает пароли из Secret `lms-db` и `lms-ha-app`, снимает custom dump с `lms-postgres`, шифрует его на PVC `lms-database-backups` и восстанавливает в `lms-ha-rw` с `verify-full`. Репетиция (`--rehearsal`) не требует остановки веба и не сверяет отпечаток таблиц. Финальная копия требует `--confirm-web-stopped` и нулевые реплики Deployment `lms`. В лог Job попадают только SHA-256 и факт совпадения отпечатка, не строки таблиц.
