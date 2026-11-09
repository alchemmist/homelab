# Интеграции Authentik и добавление нового сервиса

> Текущий срез7 ноября: [логины, первый вход и native роли](identity-current-state.md),
> [NetBird/сеть](network-access.md), [владельцы мониторинга](observability-current.md).
> Датированные rollout/smoke ниже — история своего этапа, не общая readiness.

Начало: [identity.md](identity.md). Не путать native SSO, proxy gate и обычную
плитку. Сетевые entrances/роли актуализированы 6 ноября: [network-access.md](network-access.md). Старые session evidence ниже датированы; изменения версий требуют нового review.

## 1. Реестр и исходники

| Слой | Где менять |
|---|---|
| Каталог восьми foundation services | `deploy/identity/services.json` |
| Reviewed люди / старые application IDs | `deploy/identity/account-mappings.json` |
| Общий intent ролей | `deploy/identity/access-policy.yaml` |
| Providers, scopes, application bindings, MFA | `ansible/roles/authentik/files/configure.py` |
| Native app controllers | `ansible/roles/identity_integrations/files/integrate.py` |
| LiteLLM dedicated controller | `ansible/roles/identity_integrations/files/litellm_oidc.py` |
| Argo CD, вне foundation registry | `ansible/roles/argocd_oidc/files/configure.py`, `deploy/argocd/values.yaml` |
| Сводный live status | `docs/identity/access-management.md` |
| Санитизированные результаты | `deploy/identity/migration-evidence/` |

`migration` strings каталога — исторические hints, не oracle live readiness:
например `candidate` может остаться у уже проверенного сервиса. Проверять реальный
provider, runtime settings и evidence. Foundation catalogue содержит девять dashboard applications с локальными иконками: восемь registry apps плюс отдельно управляемый Argo CD. Дополнительные public gates находятся в отдельном `deploy/public-web/services.json`; это не полный cluster-wide auth inventory.

## 2. Grafana

URL `https://grafana.socrat.alchemmist.xyz/` доступен через оба публичных HTTPS входа с native SSO, не требует workstation DNS overrides.
Нативный Generic OAuth/OIDC + PKCE, refresh token. Callback `/login/generic_oauth`.
Settings: `deploy/identity/grafana-oidc-values.yaml`; Secret
`cattle-monitoring-system/socrat-authentik-grafana` хранит client secret.

`homelab-owner` -> `GrafanaAdmin`; `app-grafana-editor` -> `Editor`; прочие admitted groups -> `Viewer`. Admission и native роль — разные проверки.
`ALLOW_INSECURE_EMAIL_LOOKUP=false`, strict role mapping. Anonymous org access **выключен**, OIDC auto-login включён; прежний proxy gate retired после проверки native ролей. Public policy блокирует BasicAuth/POST login/metrics/debug, сохраняет bearer API/WebSockets и private recovery. Публично без входа доступен **только** явно shared `socrat-traffic-light`, не вся организация.

Первый отказ `Login provider denied login request` был protocol issue: отсутствовал
`grant_types: authorization_code, refresh_token`. Исправление — явно разрешить
нужные grants в provider, не отключать MFA/TLS и не расширять admin groups.

Проверены реальный temporary observer/MFA/code flow и Grafana API role, не owner
имперсонация. Private gateway очищает Authorization header намеренно; browser
cookies работают. Cleanup/API automation использовали internal API, а не ослабление gateway.

## 3. Harbor

URL `https://harbor.socrat.alchemmist.xyz/`, native OIDC, callback `/c/oidc/callback`.
Controller использует supported `CONFIG_OVERWRITE_JSON` из Secret
`harbor/socrat-authentik-harbor`; persistence также учитывается ролью Harbor.
Owner group -> system admin; project grants остаются отдельными.

Перед переключением проверялись старые non-admin local identities: нельзя
переключить auth mode и осиротить пользователей. Локальный `admin` сохранён;
известный stale initial password не сбрасывался ради теста. Его реальная recovery
приёмка/rotation требует владельца. Robot accounts и scoped project credentials
остаются способом CI push / private pull; не применять к registry API browser gate.

Harbor 2.15.4 / chart 1.19.4 и HA work описаны отдельно в [harbor.md](harbor.md).
OIDC не устраняет single-node storage/PG/Redis риски и не завершает HA.

## 4. Rancher

Native Generic OIDC + PKCE, callback `/verify-auth`; restricted access, subjects
на базе Authentik user UUID. Old local users не переписывались в external principal.
Из-за immutable `principalIds` созданы reviewed external identities
`u-authentik-alchemmist` / **`u-authentik-tim-v2`**, которым зеркалируются конкретные
старые global/cluster/project grants. Это не повод выдавать всем cluster-admin.

Tim сейчас входит как `antropophag`; UUID пересозданной identity закреплён в
account mapping. Старые `u-authentik-tim` и `u-22wv2` disabled, grants/history
сохранены. Native `principalIds` immutable: не обходить webhook и не менять
старый principal in-place. `rancherOidcUserId`/`rancherBindingPrefix` сохраняют
reviewed replacement при следующем reconcile. [Текущие связи](identity-current-state.md).

Source: Rancher branch `integrate.py`, reviewed old IDs в account mapping.
Client secret — `cattle-global-data/genericoidcconfig-clientsecret`.
Local emergency identities остаются. Group name сам по себе не Rancher user ID;
при новых grants проверять actual principal и namespace/project scope.

## 5. Open WebUI

`https://chat.alchemmist.xyz/`; основной callback `/oauth/oidc/callback`.
В каталоге также есть reviewed legacy callback другого hostname; не добавлять
произвольные aliases. Settings: `deploy/identity/open-webui-env.json`, Secret
`llm/socrat-authentik-webui`. Post-Helm: `identity-webui-reconcile.yml`.

Старые users/chats сохранены через точные UUID/OAuth-ID links
(`Users.update_user_oauth_by_id`), без email merge. Owner admin, Tim обычный user.
Нельзя ставить `Auth.active=False` как универсальный способ убрать local login:
установленная реализация `utils/mfa.py:get_auth` этим также выключает OAuth.
Простое скрытие password form не делает старые local sessions недействительными.

Existing OTel environment сохраняется reconciler; не заменять весь env списком
из OIDC-примера. WebUI -> LiteLLM machine virtual key независим от browser SSO.

## 6. Wiki

`https://wiki.socrat.alchemmist.xyz/login` -> native OIDC, callback
`/api/auth/oidc/callback`. Не просто proxy перед редактором. Runtime source —
соседний `hugo-docs/runtime/oidc.py` / `auth.py`, а homelab хранит immutable image,
chart/Secret wiring и reviewed account mapping.

Authlib authorization code + PKCE, state/nonce, signature/audience/expiry и pinned
issuer. Secret `wiki/socrat-authentik-wiki` содержит настройки и session signing key.
При reconcile signing key сохраняется, чтобы не инвалидировать sessions случайно.
Access logs callback отключены (`UVICORN_ACCESS_LOG=false`) для приватности code/state.

Owner -> существующий admin ID. Tim -> существующий editor ID, отдельное reviewed
subject role override. Другие admitted observers -> reader. Email не используется
как доказательство владения старой записью. Хранятся `oidc_accounts` и `oidc_sessions`
в accounts SQLite; чаты/контент этим не подменяются.

`/login?local=1` работает только для existing local owner ID. Non-owner local
passwords и старые local sessions отсекаются **на сервере**, не только UI.
Это наиболее полно проверенный owner-only fallback в текущей миграции.
Public read и machine MCP credentials сохранены; missing/invalid auth для write/MCP
не должен превращаться в browser redirect. Проверялись MFA, write 403 для reader,
invalid callback 401, сохранность старых owner/Tim IDs. Wiki placement/storage
менялись параллельно: не брать старое расположение pod за current truth.

## 7. LiteLLM

Owner подтвердил рабочий вход. Нативный Generic OIDC + PKCE на **1.105.1**:

- launch: `https://llm.alchemmist.xyz/sso/key/generate`;
- callback: `https://llm.alchemmist.xyz/sso/callback`;
- provider `homelab-litellm`, app `litellm`, production admission `homelab-owner`;
- custom scope mapping `homelab-litellm-reviewed-identity`, scope `litellm_identity`;
- Secret `llm/socrat-authentik-litellm`, Generic SSO env; Helm optional Secret refs.

В этой версии free SSO допускает до пяти billable users. Controller консервативно
проверяет общее число DB users <=5 и pinned versions. Исходных user rows было две.
Лицензию не подменяли и Enterprise check не обходили.

Mapping выбирает existing `socrat-admin` / `proxy_admin` **по reviewed IdP UUID**
из account mapping и private journal, не по email/username. Нужный existing email
подставляется после выбора immutable identity. Другие UUID получают отдельный
`authentik:<uuid>` / `internal_user_viewer` и synthetic address под собственным
`sso.socrat.alchemmist.xyz`; это тестируемая безопасная ветка, а не production grant observers.
Адреса под `.invalid` были отвергнуты upstream email-validator — не использовать
их там, где runtime ожидает валидируемую email-domain модель.

Native browser roundtrip проверен на random read-only fixture: пароль -> TOTP ->
consent -> PKCE callback 303 -> server `/user/info`. Временный одиночный admission
binding, обе identity records и UI keys удалены. Реальному owner никто не
выдавал тестовую MFA и не читал его пароль. Исходные IDs/roles/emails/password
hashes/SSO IDs сравнены неизменёнными. Старый Open WebUI virtual key продолжает
читать models, без key по-прежнему 401. Master/salt/DB Secret data, config и явный
OTel env сохранены; vLLM не перезапускался. LiteLLM прошёл обычный graceful rollout.

Owner DB password recovery: `/fallback/login`, маршрут HTTP 200. Пароль не
сбрасывался; его реальная recovery-проверка не следует из подтверждения SSO.
`identity-litellm-reconcile.yml` вызывается после `litellm.yml` и `llm-vision.yml`
только при уже существующем activation Secret. Fresh Helm install не включает
SSO неожиданно. Foundation не создаёт placeholder app без reviewed custom scope.
Полный runbook/rollback: `docs/litellm.md`.

## 8. Argo CD

Native direct OIDC, Dex выключен. Live GitOps source —
`deploy/platform/argo-cd/values.yaml`; bootstrap mirror — `deploy/argocd/values.yaml`,
`ansible/roles/argocd_oidc/files/configure.py`, playbook `argocd.yml`.
Issuer `/application/o/argocd/`, callback
`https://argocd.socrat.alchemmist.xyz/auth/callback`, client `socrat-argocd`.
Secret key `oidc.authentik.clientSecret` в Argo CD Secret, без значения в values.

Dedicated scope `groups`; scopes openid/profile/email/groups/offline_access. Application admission
сейчас owner + platform-operator. Argo RBAC owner/operator -> admin; maintainer/
observer в role table -> readonly, но это **не даёт им admission** через IdP.
Default readonly также не отменяет application gate. Built-in admin break-glass
сохраняется до отдельной owner recovery-приёмки. Native server теперь
`server.insecure=false`: verified HTTPS также от обоих ingress к backend,
чтобы refresh сохранял Secure cookie. Bootstrap и live values проверяются на
семантическое равенство; ServersTransport управляется через extraObjects.

В этой сессии у уже существующего app добавлена только официальная pinned icon;
его provider/policies не перенастраивались icon uploader. Не добавлять Argo CD
в foundation catalog без явного переноса ownership между controllers.

## 9. n8n и Kuma — исключения, не готовое native SSO

**n8n:** Community не даёт нужную native SSO integration без лицензии. Embedded
outpost Authentik охраняет browser UI/rest owner-only, после MFA n8n может ещё
просить свой логин. Конфигурация `charts/n8n/templates/access.yaml` и proxy settings
в catalog. Webhooks, waiting webhooks, forms, healthz, `/api/v1` и OAuth credential
callbacks обходят browser gate по reviewed route boundary. Это не делает API
анонимным: оно продолжает проверять собственные keys/signatures.

Проверки: UI/rest -> 302 на IdP; health -> 200; API без ключа -> 401; отсутствующий
webhook -> 404. Исходный Fleet ingress/cert сохранялись. Нельзя wildcard-защитой
`/` заставить robots и callbacks получать HTML login вместо protocol response.

**Открыто, 2 ноября 2026:** owner сообщил о проблеме n8n login/session. Оба edges
прошли anonymous redirect в native Authentik, health200, keyless API401 и проверку
Running/Ready pods. Это не owner/native-login/editor-after-idle acceptance;
конкретный симптом пока не уточнён. Настройки не менялись. Не переносить fix
nginx forward-auth3x-ui на n8n proxy-mode без воспроизведения. См.
[журнал диагностики](identity-gateway-troubleshooting.md#4-n8n-открытое-сообщение-владельца-не-исправленная-проблема).

**Uptime Kuma:** native OIDC не внедрён и не заявляется. Но разделение входов **завершено**: status `/status/socrat`, status/heartbeat APIs/assets/badges и token push публичны; public Socket.IO/неизвестные admin APIs закрыты, legacy admin paths ведут на `kuma.socrat.alchemmist.xyz`. На admin host personal MFA owner/`uptime-kuma-web-admins`, затем исходная native Kuma auth. MFA не делает человека native admin. Проверены scoped MFA, WebSocket 101/namespace и denial native `getSettings`; fixtures удалены.

При application restart обнаружен Secret/SQL credential mismatch, был наблюдённый ~35min heartbeat gap. Recovery создал отдельный schema-only app account без изменения старых SQL passwords и без DB restart; Secret data изменились, native Kuma account/auth сохранились. Не регенерировать Secret/не менять DB username: [MariaDB runbook](../docs/uptime-kuma-mariadb.md), [итог и ограничения](network-access.md#6-kuma-восстановление-после-инцидента-не-zero-downtime).

### Публичные aliases и Syncthing

`deploy/public-web/services.json` хранит admission allowlist; публичные Ingress/proxy принадлежат соответствующим Argo Applications (локальные чарты либо `deploy/platform/<app>/public-entry` в той же Application), отдельный `public-web-entry` удалён; не смешивать их с foundation registry. Search admission owner/`netbird-internal-admins`; app authorization за aliases остаётся native, machine APIs не переводятся на browser redirect. Rancher публичен с native OIDC/ролями и policy proxy против local-password mutations; agents/bearer/WebSockets/private recovery сохранены. Grafana MCP — public verified TLS + отдельный read-only bearer, не human MFA gate.

На node0 `/sync/` — personal MFA owner/`syncthing-web-admins`, затем неизменённый исходный BasicAuth, prefix снимается. Node1 отвечает 410 gateway-only: новую device/identity ради GUI не создавали. Existing BasicAuth, sync process/config/data не менялись. Реальный owner Basic login остаётся отдельной опциональной приёмкой. [Подробности публичного closeout](../docs/public-web-migration.md).

## 10. Как подключить новый сервис: безопасный порядок

### Шаг 1. Inventory до конфигурации

Записать version/image/chart, все hostnames и auth paths, текущих людей/IDs/roles,
локальные способы входа, уже выданные sessions, machine consumers и публичные
routes. Проверить native OIDC/SAML support, реальную лицензию установленной версии,
PKCE/claim support. Не ориентироваться только на документацию newest release.

Сделать encrypted pre-change backup DB/config/Secret references. Не выводить
secret bodies в общий terminal/log. Подготовить owner recovery и критерии rollback.

### Шаг 2. Выбрать механизм

Предпочтение — native OIDC. Auth proxy допустим только с описанным разрезом
browser/machine/public paths. Если безопасный boundary неизвестен, статус blocked,
а не «SSO готово, ведь плитка появилась». OIDC code flow требует backend/client
support; нельзя заменить его рекламным frontend JS или хранить client secret в браузере.

### Шаг 3. Спроектировать identity/roles

Определить immutable subject mode **до первого входа**. Проверить старые IDs и
создать exact linking map, сохранение данных и конфликтную политику. Специально
проверить другого пользователя с тем же email/display name: он не должен стать owner.
Определить минимальные app/project roles отдельно от IdP admission groups.

### Шаг 4. Provider и application

Для foundation-managed сервиса добавить reviewed catalog entry: unique slug,
name, launch URL, exact redirect, approved groups, icon, explicit migration mode,
при необходимости `subMode` / custom scopes. Не добавлять client secret в JSON.
Создание runtime provider выполняет owner automation с protected credentials.

Provider: confidential client для server apps; нужные grant types явно, default
native authentication/MFA flow, подходящий authorization/consent flow, signing key,
strict callbacks, минимальные claims/scopes. Foundation validity сейчас access
5 минут / refresh 8 часов; это не обязательно lifetime local app cookie.

Проверить custom property mappings: это исполняемый security-sensitive код.
При missing mapping controller должен остановиться/отложить приложение, а не
выдать широкую роль по запасному email. Существующий provider без private client
journal не перегенерировать — сначала восстановить/проверить credentials.

Минимальный пример **шаблона**, не готовой интеграции (URL/slug заменить после review):

```json
{
  "example-service": {
    "name": "Example service",
    "url": "https://service.example.org/",
    "description": "Reviewed native OIDC integration",
    "redirect": "https://service.example.org/oauth/callback",
    "groups": ["homelab-owner"],
    "subMode": "user_uuid",
    "migration": "native-oidc-pending-backend-acceptance",
    "icon": "service-icons/example-service-REPLACE_WITH_DIGEST.svg"
  }
}
```

Не копировать это в production без проверки actual callback, allowed users и app
backend. `REPLACE_WITH_DIGEST` — placeholder: сначала добавить reviewed asset и
provenance в `assets/service-icons/sources.json`, получить реальный digest/name,
затем проверить served icon и обновить соответствующие regression tests. Generic controller умеет сейчас `grafana`, `harbor`, `rancher`,
`open-webui`, `wiki`; `litellm` идёт отдельной веткой роли. Для нового slug нужно
написать/review backend adapter или его declarative equivalent: catalog entry
сам по себе не создаёт OIDC support внутри нового приложения.

### Шаг 5. Настроить backend приложения

Передать client ID/secret через private runtime Secret; issuer/discovery и scope
настроить согласно установленной версии. Добавить source-controlled references и
post-upgrade reconcile, не оставлять только ручной Deployment patch. Сохранить
OTel/env/volumes/machine keys и unrelated chart values. Не повторять blind whole-env
replacement. Проверить readiness/graceful rollout, не force-delete draining pods.

### Шаг 6. Проверка и публикация

- Positive: password + реальная временная MFA + callback + server-verified ID/role.
- Negative: unadmitted identity denied, non-admin не админ, exact callback/state,
  wrong issuer/audience/expired token не принимаются, никакого arbitrary email merge.
- Existing data и IDs сохранены, owner recovery отдельно принят владельцем.
- Public routes и machine key requests сохраняют semantic HTTP status, без HTML redirects.
- Fixture users/keys/devices/temporary policy bindings удалены даже при ошибке.
- Отдельная проверка уже выданных local sessions; UI hide не enforcement.
- Документация/evidence без cookies/codes/seeds; tests и narrow commit; push не
  считать deploy до проверки running config/images/controllers.

Не объявлять «все сервисы migrated» после одного успешного app flow.


## Фоновый refresh Argo CD и backend TLS

Внедрён `offline_access` (mapping + requested scope), упреждающий refresh `60s`,
политика Argo session `8h`; access/ID token остаётся `5min`. В Argo CD 3.5.6
renew-cookie зависит от `!server.insecure`, поэтому backend теперь HTTPS с
проверкой существующего сертификата и SNI через `argocd-verified-tls`.
VPS CRD provider ограничен namespace argocd и label выбранного transport;
без skip-verify/cross-namespace/ExternalName. DNS, WireGuard и MFA не менялись.

Ingress управляется Argo selfHeal: временная пауза только traefik-edge, публикация
исходников, hard refresh до новой revision, затем восстановление исходного autosync.
Иначе ручной Helm upgrade откатывается. Статус приёмки/fixture cleanup и подробный
runbook: [Argo CD refresh](../docs/identity/argocd-refresh.md). Старым сессиям нужен
один новый SSO authorization, чтобы получить refresh token. Остальные приложения
этой настройкой не изменяются; 8h refresh validity само по себе не доказывает,
что конкретный клиент получает/использует refresh token.


## 3x-ui: owner MFA gateway (не native SSO)

Публичная VPN-панель защищена Authentik forward-auth (`xui-panel`), только `homelab-owner`; после IdP остаётся native логин 3x-ui. Никакого account/email merge, подмены MFA или автоматического входа в native admin нет. Прямой public TCP 18082 закрыт persistent panel-only nft rule; private/loopback recovery — отдельная доверенная граница с native credentials.

Подписки text/JSON и Trojan WebSocket сохраняют прежние backends и обходят только human gate, не собственную machine authorization. Native API exception требует Bearer и удаляет Cookie; неверный токен даёт 401, cookie-only browser API требует MFA. VPN/ingress не перезапускались; прошли реальные tunnel/subscription и оба public-edge MFA fixture tests.

Bearer lifetime — 5 минут; offline-access/8h refresh настроены только новому proxy provider. Но expiry-тест выявил native browser roundtrip к IdP, а не бесшовный refresh; возможен reload панели при истёкшем proxy cookie. Не переносить на этот шлюз утверждение о silent refresh, доказанное для Argo CD. Личная owner recovery/native-login и valid API token acceptance остаются отдельными.

Источники, инсталляция host rule, воспроизводимая приёмка, limits и rollback: [docs/identity/xui-gateway.md](../docs/identity/xui-gateway.md). Узкий controller `xui_gateway.py` не replay foundation и не изменяет пользователей/базу панели.


### 3x-ui: исправление Login Failed to fetch

При отсутствующей gateway-cookie фоновый POST раньше уходил в cross-origin
OAuth redirect и давал TypeError: Failed to fetch. Теперь XHR/fetch и unsafe
methods получают same-origin401; native 3x-ui3.11 самостоятельно запускает
обычную top-level навигацию. CSRF, MFA, native пароль и machine Bearer policy
не обходятся. Проверены оба edges: native CSRF/empty-login JSON200, missing-cookie
401 без redirect и **реальная native кнопка Login →401 → возврат через SSO**.
Тестовые credentials до native backend не дошли, fixture users/bindings удалены.
Owner native-password acceptance остаётся личной. Бесшовный refresh не обещан.
Подробности: [диагностика gateway](identity-gateway-troubleshooting.md#3-3x-ui-исправленный-failed-to-fetch-на-login).


## Машинный admin API: не Default Admin

Для identity controllers выделен `homelab-identity-automation` (service account),
а Outpost сохраняет свою отдельную техническую идентичность. `akadmin` удалён
после переноса token и recovery drill. Human IDs/links/roles не переносились.
Legacy credential key AUTHENTIK_BOOTSTRAP_TOKEN сохранён как alias нового key,
так что текущие consumers совместимы; runtime Secret исключает admin bootstrap
env. Детали и широкие privilege boundaries:
[admin-automation.md](../docs/identity/admin-automation.md).

## SPI queue native OIDC — prepared 9 November, not activated

Standalone `spi.socrat.alchemmist.xyz`; source in the full `spi-triage` repo.
Native confidential Code+PKCE, state/nonce and RSA issuer/audience/expiry checks;
no RustFS forward-auth or client secret in JS. Dedicated SPI identity catalog/
plan controller follows the separately owned native-provider pattern; do not
replay foundation or change existing human memberships. Frontend-only Secret,
canonical callback and app-owned Ingress/TLS/policy are prepared. Built native
image341tests/zero skips; GET-only live Authentik plan succeeded. No live writes
or protected publication approval: operator kubeconfig is unreachable and SSH
lacks its trusted saved host key. See [SPI OIDC runbook](../docs/identity/spi-triage-oidc.md)
for activation, bounded five-minute local sessions and explicit acceptance gates.
