# pgAdmin

`pg.socrat.alchemmist.xyz` → Traefik → `postgres/pgadmin` (one replica, persistent settings).
Native OAuth2 only, provider `homelab-pgadmin`, strict `/oauth2/authorize` callback,
`homelab-owner` binding and matching group claim. The bootstrap account has no local web login.
PostgreSQL login is separate from Authentik: use an authorized database role, not the bootstrap password.
Shared server definitions use the three CNPG `-rw` Services and per-cluster CA certificates.
Owner-only shared connections use `pgadmin_browser`, a non-admin CNPG-managed login per cluster.
Provision distinct Kubernetes basic-auth Secrets `pgadmin-browser-{common,critical,internal}`
(username `pgadmin_browser`, independently generated passwords) before deploying. The named
password helper accepts only OAuth2 and the exact database hosts, port and login. Keep the
Secrets outside Git. No password saving or master-password prompt. Rotate through CNPG;
never enable the postgres superuser for UI access.
The removed async standby was outside `pg-critical`'s synchronous quorum.

Desired state: `charts/postgres-platform/templates/pgadmin.yaml`. Keep `pgadmin-bootstrap`
and `pgadmin-oidc` Secrets out of Git. The DNS playbook `pgadmin-public-dns.yml` checks all
four authoritative zone writers before a serial approved record addition; don't use a client
hosts override to declare the public deployment complete. Verify public TLS, anonymous redirect,
owner sign-in, and denied access for a nonmember before acceptance.

DNS is HOME-only: the VPS ingress does not watch namespace `postgres`. Do not grant the edge controller watch access to database Secrets to publish this UI.

Non-owner SharedServer rows omit the owner's CA filename. Keep `verify-full`; the init container builds libpq's default `root.crt` from only the three public CNPG CA certificates. Roll pgAdmin when a cluster CA rotates. Verify a connection **without** supplying `sslrootcert`, using the shared login and its password helper.

## Доступ: срез на 22 ноября 2026

**Действует:** вход через Authentik по `homelab-owner`; все три общих подключения работают от `pgadmin_browser`. В PostgreSQL видна эта общая роль, а не имя пользователя SSO. Доступ к данным определяется SQL-привилегиями, не ролью администратора интерфейса.

| Кластер | Баз, проверенных из pod pgAdmin |
|---|---:|
| `pg-common` | 18 |
| `pg-critical` | 7 |
| `pg-internal` | 1 |

На момент проверки `pgadmin_browser` мог подключиться ко всем 26 нешаблонным базам с разрешёнными подключениями. Выданы `CONNECT` на базы, `USAGE` на прикладные схемы и `SELECT` на существующие таблицы, представления и последовательности. Это точечные SQL-гранты, не `pg_read_all_data`; новые базы и объекты автоматически их не наследуют. RLS не отключали.

**Подготовлено, но не включено:** в Authentik созданы `pgadmin-reader`, `pgadmin-writer` и `pgadmin-admin`. Членство `alchemmist` в `pgadmin-writer` проверено. Само по себе оно пока не даёт ни входа вместо `homelab-owner`, ни записи. На каждом кластере есть отдельная SQL-роль `pgadmin_writer` (`NOLOGIN`): чтение и `INSERT`/`UPDATE`/`DELETE` на существующих прикладных таблицах, права на использование последовательностей. Ей не выдавали `TRUNCATE`, DDL, `SUPERUSER` или `BYPASSRLS`. Подключения pgAdmin эту роль пока не используют.

**Критерий завершения перехода:** проверить в браузере, что writer может выполнить DML на тестовой таблице с откатом транзакции, а reader получает отказ, в том числе при попытке использовать подключение writer напрямую. Отдельно проверить допуск администратора интерфейса и отказ пользователю без групп. Расширять общую роль `pgadmin_browser` нельзя. Запись во все базы распространяется в том числе на данные Authentik: членство в `pgadmin-writer` после включения будет высокопривилегированным.

**Диагностика:** если сервер раскрывается, но одна база возвращает `permission denied for database`, проверять `CONNECT` именно на этой базе. Если libpq сообщает об отсутствии `root.crt`, проверять файл в работающем pod, не отключать проверку TLS. После исправления CA временный пользователь в Chrome прошёл OAuth2 и TOTP и раскрыл все три сервера; тестовая учётка и профиль удалены. Эта проверка подтверждала подключение, не права записи.
