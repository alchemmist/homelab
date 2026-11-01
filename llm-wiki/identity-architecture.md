# Авторизация Socrat: архитектура и границы доверия

Срез внедрения **1 ноября 2026**. Начало справочника: [identity.md](identity.md).
Это описание реально внедрённой системы и её ограничений, не обещание завершённой
миграции всех endpoints. Для изменений сначала сверять текущие manifests и live state.

## 1. Что именно централизовано

Authentik — Identity Provider (IdP): личные пользователи, пароль, обязательная MFA,
группы, разрешение входа в приложения, выдача OIDC tokens. Приложения остаются
отдельными системами со своими данными, локальными ID, правами, сессиями и API keys.

Нельзя смешивать четыре разных слоя:

1. **Сеть:** WireGuard, private gateway, публичный ingress, TLS, NetworkPolicy.
2. **Аутентификация:** кто человек и как он доказал личность; здесь Authentik/MFA.
3. **Авторизация:** какие приложения, проекты, namespaces и операции ему разрешены.
4. **Машинные credentials:** robots, service accounts, virtual keys, webhooks, MCP.

Успешный MFA не выдаёт автоматически cluster-admin. Видимая плитка не доказывает,
что backend использует SSO. Доступ к IP/порту не равен доступу к данным. OIDC не
переносит пользовательскую базу и не объединяет аккаунты сам по себе.

## 2. Реальное размещение

- Публичный IdP: **https://auth.socrat.alchemmist.xyz/**.
- Namespace `identity`, Authentik chart/app **2026.8.5**.
- По одной реплике server и worker на `socrat-0`; PostgreSQL **17.11** там же.
- Внешний для chart PostgreSQL: StatefulSet/Service `authentik-postgres`.
- `authentik-data`: PVC для `/data`; отдельное persistent storage БД.
- PV сохраняются с `Retain`; это защита от случайного удаления claim, не backup.
- Runtime Secret `authentik-runtime`; ServiceAccount `identity-runtime`, без
  автоматически смонтированного API token. Server/worker не должны управлять кластером.
- Embedded outpost обслуживает proxy integration n8n. Не надо ставить outpost
  перед каждым приложением: для нативного OIDC браузер идёт прямо в приложение.
- Статика Quiet Mono — отдельный sandboxed nginx `socrat-authentik-theme`, тоже
  на `socrat-0`. Подробнее [identity-frontend.md](identity-frontend.md).

Источники: `deploy/authentik/values.yaml`, `foundation.yaml`, роль
`ansible/roles/authentik/`, playbook `ansible/playbooks/authentik.yml`.
Chart закреплён версией и SHA-256 в defaults роли; assets и nginx — также хешами.
Не переписывать version guard, пока новая версия не проверена.

**Это не HA.** Два публичных ingress IP и несколько control-plane не реплицируют
IdP PostgreSQL, PVC или `/data`. Потеря `socrat-0` может лишить новых входов и стилей.
Уже выданные сессии некоторых приложений могут ещё работать, но это не гарантия.
Распределённая HA, независимые резервные копии, escrow ключей и полный DR — отдельные задачи.

## 3. Server, worker, БД и frontend

Server обслуживает API, flow executor, OIDC endpoints, UI и embedded outpost.
Worker выполняет фоновые задачи. PostgreSQL содержит пользователей, группы,
flows/stages, providers/applications, bindings, токены и служебное состояние.
Секретный ключ инсталляции, signing keys и client secrets — часть идентичности
системы: восстановить одну БД без соответствующего secret material недостаточно.

Frontend — **штатные Lit/Web Components Authentik**, не наша форма с собственной
проверкой пароля. Страницы имеют вложенные shadow roots; flow executor получает
challenge от сервера и загружает нужный native stage. Наш production frontend —
Brand CSS + локальная статика + несколько явно управляемых presentation fields.
Синтетический offline-прототип в `prototypes/authentik/` в аутентификации не участвует.

Не переносить сюда устаревший универсальный рецепт с Redis из другой версии:
состав действующего deployment определяют наши manifests и pinned chart.

## 4. Объекты Authentik

| Объект | Роль |
|---|---|
| User | Личная identity, UUID, активность, группы, MFA devices |
| Group | Набор пользователей; имя группы может идти в signed claims |
| Flow | Сценарий authentication / authorization / invalidation / enrollment |
| Stage | Один шаг: identification, password, MFA, consent, login и т.д. |
| Stage binding | Порядок/условия включения stage в flow |
| Plan | Рассчитанное выполнение flow с контекстом и текущими bindings |
| Provider | OIDC/proxy protocol config, callbacks, signing key, scope mappings |
| Application | Плитка/launch URL и связь с provider; admission policies |
| Policy binding | Условие доступа к приложению/объекту: группа или policy |
| Property/scope mapping | Код формирования claims; security-sensitive configuration |
| Brand | Домен, логотип/favicon/background, CSS, defaults языка/темы |
| Outpost | Proxy/forward-auth компонент для ненативных интеграций |

Имена default flows важны для reconciler. Не переименовывать и не удалять их
вслепую: automation ищет конкретные slug/name и должна остановиться при неоднозначности.

## 5. Путь обычного входа

```text
браузер -> приложение -> authorize Authentik
                       -> admission / authentication flow
                       -> пароль + MFA, если действующей сессии ещё нет
                       -> authorization flow / consent
                       -> точный callback приложения с одноразовым code
приложение -> token endpoint Authentik (client credentials + PKCE verifier)
           -> проверка tokens/identity -> собственная сессия приложения
```

OIDC использует authorization code, не пароль пользователя в приложении.
`state` связывает callback с начатым запросом; `nonce` — ID token с этим входом;
PKCE связывает code с инициатором. Приложение проверяет issuer, подпись, audience,
expiry и прочие protocol invariants. TLS verification не отключать.

Если MFA-сессия Authentik уже есть, повторного экрана пароля может не быть.
Короткий `Redirecting` — нормальный переход, не новый вход и не ошибка.
Вход через плитку и через кнопку SSO приложения должен вести в один доверенный IdP.
Старая локальная сессия приложения может не вызвать OIDC до logout/expiry.
Для проверки нового входа нужен отдельный private browser context, не сброс owner MFA.

## 6. Endpoints и subjects

Для foundation-managed OIDC стандартные endpoints на IdP:

- authorize: `/application/o/authorize/`;
- token: `/application/o/token/`;
- userinfo: `/application/o/userinfo/`;
- issuer/discovery конкретного приложения: `/application/o/<slug>/` и его
  `.well-known/openid-configuration` (проверять metadata установленной версии).

Issuer нужно копировать точно, включая path/trailing slash. Не выбирать issuer
по недоверенному token payload и не разрешать произвольный discovery URL.
Callbacks — точный HTTPS URL с `matching_mode: strict`, без `*`.

**Immutable subject — не email и не username.** Некоторые наши providers используют
`sub_mode: user_uuid`, другие сохраняют прежний `hashed_user_id`. Нельзя менять
subject mode после включения и ожидать, что приложение узнает старые аккаунты.
`request.user.uuid` — UUID записи Authentik; `uid` в Authentik может зависеть от
секретного ключа инсталляции и не является заменой этому UUID. LiteLLM mapping
явно использует UUID; это исправлено после проверки upstream source.

Где уже есть данные, до первого входа составляется reviewed map:
**Authentik subject/UUID -> конкретный существующий application user ID**.
Ни совпадение email, ни одинаковое отображаемое имя не доказывают владение старым
аккаунтом. Реестр: `deploy/identity/account-mappings.json`; реальные UUID/IDs там
метаданные, а не bearer credentials. Пароли и tokens в этот файл не добавлять.

## 7. Admission, app roles и sessions — разные проверки

`deploy/identity/services.json` определяет foundation apps, callback, допущенные
группы, иконку и protocol hints. `groups` приложения ограничивают возможность
пройти через IdP; role mapping внутри приложения определяет конечные права.
Общая политика foundation application — `any`: достаточно одной разрешённой
группы. Это не означает «пускать всех», но лишний permissive binding опасен.

Допуск observer в приложение не должен автоматически давать Editor/Admin.
IdP superuser и app admin — разные роли, соединённые только явными mappings.
Даже после отзыва IdP group уже выданная app cookie может оставаться действительной.
Logout одного приложения, logout Authentik и отзыв всех app sessions не одно и то же.
Полную offboarding-процедуру см. [identity-operations.md](identity-operations.md).

## 8. Вход в приложение не выдаёт SSH / kubectl

Полная процедура: [Linux/SSH и RBAC](identity-host-access.md).

Linux и Kubernetes — отдельные контуры. На четырёх нодах настроены личные SSH
public keys, закрыты password logins управляемых ограниченных пользователей,
нет неявного sudo/docker/root-equivalent членства. Ключи задаются по хостам.

`/etc/rancher/k3s/k3s.yaml` на `socrat-0`: **0640 root:alchemmist**, owner-only group.
Раньше файл был world-readable; chmod закрывает новое чтение, но не отзывает
раньше скопированный admin certificate. Историческую экспозицию надо оценивать
отдельно; ротация CA в этой работе не выполнялась.

`homelab-project-observer` ClusterRole существует без human bindings. Разрешены
get/list/watch определённых workload/network объектов; нет Secrets, exec, logs,
node access. Имя IdP group само не становится Kubernetes/Rancher principal.
Namespace RoleBinding и project grants требуют отдельного решения владельца.

Root внешней ноды — trust boundary для workloads/secrets этой ноды. RBAC не может
сделать root недоверенным наблюдателем запущенных там pod. Namespace maintainer,
способный создавать pods/exec, также потенциально получает доступ к secrets namespace.
Не называть эти полномочия безвредным read-only.

## 9. Сеть и публичные входы

Доверенные публичные edges: `109.173.40.247`, `176.98.185.59`. Во время проверки
использовались process-local resolver overrides с сохранением Host/SNI/TLS, не
изменения DNS или WireGuard. Grafana/Rancher сохраняют private-network ограничения.
Текущий private WG gateway имел отдельную проблему TLS/virtual hosts; нельзя
«лечить» её `verify=False`, публикацией private admin UI или изменением VPN в branding.
NetBird отложен; WireGuard этой миграцией не заменялся.

Harbor обеспечивает приватные images/robots для workload delivery, но его OIDC
не заменяет registry robot passwords. HA Harbor тоже отложена; см. [harbor.md](harbor.md).

## 10. Что не считать завершённым

- Kuma не мигрирован; n8n — MFA gateway, не native SSO.
- Полный inventory всех человеческих auth paths и lifecycle старых sessions ещё нужен.
- Owner-only local fallback полностью server-side проверен для Wiki; не переносить
  этот вывод на весь кластер. LiteLLM сохраняет owner DB password, но его реальная
  recovery-приёмка отдельно от подтверждённого owner SSO.
- Tim должен получить credential безопасно и зарегистрировать личный фактор;
  fixture TOTP не доказывает его личную готовность. SSH private-key acceptance — тоже отдельно.
- Scheduled independent backups, key escrow, full DR и bootstrap-token retirement
  не реализованы фактом наличия manual backup scripts.
