# Авторизация приложений: текущий B2C контракт

**External пароль:** [страница смены пароля](../authentik/operations/password-self-service.md) —
https://auth.socrat.alchemmist.xyz/change-password; `/if/user/` для External закрыт.

Это актуальная точка входа для выдачи доступа отдельным людям. Исторические
owner-only/observer bootstrap описания не заменяют этот контракт. Технический
runbook и private receipt references: [app access groups](app-access-groups.md).

## Что делает владелец в UI

1. Создаёт/выбирает личную активную учётную запись Authentik. Тип **External**
   допустим: Internal/External не является разрешением на приложение.
2. Назначает только требуемые app-группы из таблицы.
3. Передаёт человеку обычный адрес входа безопасным способом. Пользователь сам
   проходит первый вход/MFA; ассистент не сбрасывает пароль/MFA и не входит за него.

| Группа | Приложение и роль |
|---|---|
| `app-litellm-user` | LiteLLM `internal_user`, свои ключи/кабинет, не proxy admin |
| `app-open-webui-user` | Open WebUI, обычный пользователь |
| `app-grafana-viewer` | Grafana Viewer |
| `app-grafana-editor` | Grafana Editor, не GrafanaAdmin |
| `app-wiki-reader` | Wiki reader |
| `app-wiki-editor` | Wiki editor |
| `app-lms-student` | LMS student |
| `app-lms-teacher` | LMS teacher; при обеих LMS группах teacher имеет приоритет |

Одна app-группа даёт допуск только своему приложению. Существующие дополнительные
права аддитивны: добавление viewer не понижает уже существующего администратора.
LMS роль не означает доступ ко всем урокам: lesson grants остаются отдельными.
Обычно native аккаунт появляется при первом успешном SSO-входе (JIT), а не сразу
при создании человека/добавлении в группу. Глобального копирования всех людей во
все приложения нет. Публичные страницы не становятся приватными из-за этой схемы.

Не выдавать B2C-пользователю `homelab-owner`, `homelab-platform-operator`,
Authentik Admins/Read-only или automation/admin groups. `homelab-observer` — старый
широкий staff-профиль нескольких сервисов, не замена отдельной app-группе.
`homelab-chat-user` остаётся legacy доступом к чату; новый выбор —
`app-open-webui-user`. Наличие VPN/NetBird, SSH, sudo или kubectl — отдельные права.

## Что делает код/Ansible

- Источник ролей: `deploy/identity/services.json` (`appRoles`, `accessManagement`).
- Общий `identity_app_access` hook вызывается при штатной регистрации Authentik
  приложений и настройке native integrations; создаёт `app-<slug>-<role>` группы
  и проверенные admission bindings. Отдельно вручную создавать группы/PK не нужно.
- Reconciler также обнаруживает уже зарегистрированные Authentik приложения.
  Неизвестным создаёт пустую зарезервированную user-группу **без допуска**.
- Для нового приложения ассистент описывает его SSO, native роли и проверенный
  adapter, затем общий механизм создаёт группы. Новый Pod/Ingress сам по себе
  не сообщает приложению подходящие роли и не подключает SSO автоматически.
- Ручная регистрация вне Ansible обнаружится при следующем reconcile. Постоянного
  watcher/фоновой записи нет; обычный Git push сам не запускает этот IdP writer.
- Членство B2C людей задаётся в Authentik UI, не обязательными per-human строками
  Git. Общий reconciler людей не меняет. Старый `prepare_app_iam.py` — исторический
  ограниченный инструмент миграции, не текущая команда onboarding.

Plan по умолчанию GET-only для API; apply — свежий hash, lock, private preimages,
CAS/drift guards. Не управляет паролями/MFA, не удаляет группы, не ротирует client
secrets. Неожиданная привилегированная группа/сложная policy/чужое владение — stop,
не автоматическое исправление. Отдельный playbook и команды — в runbook выше.

## Native совместимость и идентичность

Wiki role map принимает новые reader/editor группы. В app-local OIDC claims
Open WebUI получает нужный legacy user-role alias, LMS — student/teacher aliases.
Это **не** добавляет глобальное членство observer и не открывает соседние сервисы.
Default scope mappings не менялись; выбирать их надо по точному upstream имени,
а не все mappings с `scope_name=profile`, иначе возможна утечка aliases между apps.

LiteLLM: неизменяемый UUID → `authentik:<UUID>`; app member → `internal_user`.
Только проверенный owner UUID получает `socrat-admin` / `proxy_admin`. Совпадение
email/username не превращает человека во владельца. Владислав теперь состоит
только в `app-litellm-user`; его прежний аккаунт сохранён, direct user binding и
UUID role exception сняты, `litellm-users.json` пуст. В проверенном срезе всего
3 LiteLLM пользователя; консервативный gate текущей версии — **5 total users**.
Группы не обходят лицензию и не дают неограниченный B2C provisioning.

## Что пока не выдавать как готовый B2C доступ

Зарезервированные `app-n8n-user`, `app-harbor-user`, `app-rancher-user`,
`app-argocd-viewer` и обнаруженные NetBird/SPI/RustFS группы не получили новый
допуск. Их наличие в списке не означает рабочий native аккаунт/роль.

- n8n: нет принятой native OIDC/JIT схемы; IdP gate не создаёт n8n аккаунт.
- Harbor: нужны project grants и отдельная проверка CLI/session revocation (#134).
- Rancher/Argo CD: staff-инфраструктура и отдельные native RBAC/cache adapters,
  не автоматические B2C cluster privileges.
- NetBird/SPI/RustFS: отдельные владельцы/контроллеры и политики сохранены.

## Отзыв и границы проверки

Снятие app-группы блокирует новый SSO-допуск, **не доказывает мгновенный logout
всех сессий/ключей**. Для offboarding отдельно отозвать native sessions/API keys
по правилам приложения. Wiki проверяет текущее членство с ограниченным кешем;
LMS сессия может сохранять роль до нового входа/expiry; LiteLLM API keys независимы
от возможности заново войти через Authentik. Не удалять пользователя с данными
вместо корректного отзыва. Ранее принятый observer revoke не является приёмкой
новых app-групп во всех приложениях.

Принятый срез: 8 native mapping/admission-graph случаев с отключённой passwordless
fixture (удалена), реальные owner/Vladislav mapping results, native LMS выбор роли,
пустой live reconcile plan, LiteLLM read-only preflight, isolated Ansible plan
`changed=0`. 125 выбранных offline tests: 124 passed/1 skipped. Сохранены прежние
группы/членства, LiteLLM identities/roles и master/OIDC Secret data; приложения Ready.
Это не полный browser/MFA/JIT E2E и не универсальная session/key revocation
приёмка. Git publication не добавляет runtime доказательств; живые права уже были
применены до текущего documentation/source closeout.
