# Авторизация кластера Socrat: главный справочник

**Актуализировано 1 ноября 2026 после owner-проверки LiteLLM и исправления native
inspector/redirect controls.** Это консолидированное описание всей сессии: как
устроены вход, MFA, права, интеграции, фронтенд, deployment и recovery. Не содержит
паролей, токенов, MFA seeds, browser sessions или приватных сохранённых HTML.

**Дополнено 2 ноября 2026:** ограничения gateway/SSO, исправление 3x-ui Login, открытая диагностика n8n и актуальный frontend. Предварительные проверки n8n не означают, что сообщение владельца закрыто.

## Читать по задаче

| Вопрос | Раздел |
|---|---|
| Как устроен Authentik, OIDC, сессии и границы доверия | [Архитектура](identity-architecture.md) |
| Как войти, добавить человека, выдать/отозвать права, работать с MFA | [Ежедневные операции](identity-operations.md) |
| Двойной логин, consent offline_access, Failed to fetch, открытая проблема n8n | [Диагностика SSO и gateway](identity-gateway-troubleshooting.md) |
| Что сделано для каждого сервиса и как подключать следующий | [Интеграции](identity-integrations.md) |
| Как устроен NetBird, добавить админа/ноду, что с отказоустойчивостью | [NetBird: актуальный справочник](netbird.md) |
| Как добавить username + публичный SSH-ключ на ноды одним Ansible playbook | [SSH: короткая инструкция](ssh-user.md) |
| Как отдельно устроены Linux/SSH, sudo, kubeconfig и Kubernetes RBAC | [Host access](identity-host-access.md) |
| Где frontend/CSS, shadow DOM, фото/шрифты/иконки, inspector, rollback | [Quiet Mono frontend](identity-frontend.md) |
| Backups, restore checks, аварии, диагностика, tests и безопасный push | [Восстановление и сопровождение](identity-recovery.md) |

Это единый справочник из нескольких файлов, а не независимые источники
политик. Реальное конфигурирование — source-controlled manifests/controllers плюс
runtime Authentik/app state; подробная карта файлов есть в разделах. Перед операцией
сверять версию и live state. Старые заметки ниже — журнал внедрения, не текущий
перечень незакрытых задач; более поздняя приёмка и исправления описаны выше.

## Краткий текущий статус

- Portal: **https://auth.socrat.alchemmist.xyz/**, Authentik **2026.8.5**,
  server/worker/PG17.11 на `socrat-0`, retained PVC. **Не HA**.
- Owner `alchemmist` — личная MFA identity, единственный в `homelab-owner`.
  `akadmin` выведен из эксплуатации после отдельной миграции API; recovery — node-admin.
  Машинные учётки Outpost и identity automation не являются людьми.
  См. [admin automation](../docs/identity/admin-automation.md).
- Tim — отдельная observer identity, с сохранением reviewed старых app IDs.
  Личная доставка credential/TOTP и реальная private-key SSH-проверка отдельно.
- Native SSO: Grafana, Harbor, Rancher, Open WebUI, Wiki, LiteLLM; Argo CD имеет
  собственный отдельный native OIDC controller. Их роли/ограничения неодинаковы.
- **LiteLLM owner SSO подтверждён владельцем.** Owner-only admission, reviewed
  UUID -> existing `socrat-admin`; machine API keys сохранены. Recovery password
  не сбрасывался и не считается проверенным этим подтверждением.
- n8n — Authentik MFA gateway, **не native account SSO**. Kuma **не мигрирован**.
- Восемь foundation apps плюс отдельно Argo CD: все девять с локальными icons.
- Quiet Mono v5 работает поверх native executor, без replacement auth JS.
  `Redirecting` без raw `%(app)s`; Follow redirect anchor стилизован; лупа выровнена;
  native history сохранена, ограничена по высоте, не сгенерирована прототипом.
- Language picker скрыт, default English/light; старые URL/session locale overrides
  пока не принуждаются к English. Native JSON highlighting/Copy — отдельный backlog.
- Machine APIs/MCP/robots/webhooks не переводятся на browser redirects.
  Межнодовый WireGuard сохранён; NetBird внедрён как human ingress под Argo CD.
  [Текущая схема и добавление админа](netbird.md); legacy recovery WG не отключать.
  Полный cluster-wide human-auth inventory,
  offboarding/old-session enforcement, independent backups/DR и HA ещё не завершены.

## Быстрый ориентир в исходниках

`deploy/identity/{services.json,account-mappings.json,access-policy.yaml}` — intent
и reviewed linking; `ansible/roles/authentik/` — IdP foundation; роль
`identity_integrations` — native backend reconciliation; `deploy/authentik/quiet-mono/`
— production theme и frozen reference; `assets/service-icons/` — pinned artwork;
`scripts/identity-*` — audit/backup/acceptance tools. Не все scripts read-only:
fixture smoke и restore check изменяют тестовые ресурсы, запускать осознанно.

Нижележащие старые записи сохранены как историческое evidence. Упоминания
«ещё не migrated LiteLLM», «семь apps» или прежнего этапа Git не отменяют текущий
статус и подробные runbooks выше.

---

# Исторические записи внедрения (читать с учётом справочника выше)

**1 ноября 2026, после второго rollout.** Пользователь подтвердил работу под
`alchemmist`, сообщил об отказе Grafana и разрешил sudo-применение/дальнейшую
миграцию. **На том этапе NetBird был исключён из scope; этот запрет впоследствии
снят отдельной задачей. Текущее состояние: [NetBird внедрён](netbird.md).**
Посторонние OTel/VPN изменения сохранять.

## Что работает

- **Authentik:** https://auth.socrat.alchemmist.xyz/, chart/app **2026.8.5**, pinned
  SHA-256; server + worker + PG17.11 на socrat-0, retained local PVCs. **Не HA**.
- Обязательное MFA. Owner `alchemmist` уже вошёл и настроил свой фактор. Других
  устройств MFA за него не регистрировать/не сбрасывать пароль при stale initial file.
- Только `homelab-owner` — superuser; единственный человек в ней alchemmist.
- Создан **tim**, группа **homelab-observer**, initial credential вне Git в
  `~/.cache/homelab-authentik/tim-login.json` на socrat-0. Передавать вне чата,
  вход с личным TOTP и сменой initial password. SMTP приглашения пока нет.
- Девять текущих плиток с локальными SVG-иконками, загруженными в собственное media-хранилище Authentik;
  все icon URLs проверены 200. Assets/hash/attribution: `assets/service-icons/`.

## Grafana: причина ошибки и исправление

`Login provider denied login request` был из-за **неразрешённого grant_type**.
У новых OAuth providers явно задавать `grant_types=[authorization_code,refresh_token]`.
Не отключать TLS/MFA и не расширять группы, пытаясь исправить этот protocol error.

**Native OIDC + PKCE активен**, owner → **GrafanaAdmin**, остальные admitted groups
→ Viewer. Insecure email-based linking выключен. Local emergency login и прежний
осознанный anonymous Viewer сохранены — это не exclusive SSO для чтения.

Проверен полный HTTP browser-equivalent flow временным observer: пароль → TOTP →
consent → code/PKCE → `/api/user` и Viewer role, не server-admin. Test identities
удалены и из Authentik, и из Grafana. Скрипт `scripts/identity-grafana-smoke.py`.
Никогда не использовать настоящий owner password/TOTP для автоматизированного smoke.
Private Grafana nginx намеренно очищает Authorization header; admin cleanup идёт
через internal service с owner node, не ослабляя gateway.

## Остальные сервисы

- **Harbor — native OIDC включён**, `systeminfo.auth_mode=oidc_auth`. Использован
  поддерживаемый CONFIG_OVERWRITE_JSON из Secret, initial admin password не сбрасывали.
  Перед этим encrypted off-node backup. Pull-only robot после переключения получил
  приватный BusyBox manifest 200, digest сохранился. Local admin — break-glass.
  Browser owner login ещё требует человеческой acceptance-проверки.
- **Rancher — native Generic OIDC + PKCE включён**, restricted exact UUID principals.
  Неизменяемые principalIds старых пользователей НЕ обходить через webhook bypass.
  Созданы внешние `u-authentik-alchemmist` и `u-authentik-tim`; им зеркалируются
  проверенные прежние Rancher GlobalRole/ClusterRoleTemplate/ProjectRoleTemplate
  grants. Старые local identities остаются emergency/transition. Это отдельные
  identities, не переписанные local IDs; native controllers генерируют K8s RBAC.
  Stale managed mirrored grants удаляются при reconciliation. Нужен реальный
  browser acceptance владельцем/Tim, одного наличия provider недостаточно.
- **Open WebUI — native OIDC включён**. Два прежних user ID и чаты сохранены,
  связь через точные Authentik UUID и application model method. Email auto-merge
  выключен. Reviewed mappings в `deploy/identity/account-mappings.json`.
  Owner admin, Tim user. Public canonical и known private callback strict allowlist.
  Local emergency login оставлен; owner должен проверить обычный browser flow.
- **n8n — MFA/group gate на UI и REST через embedded Authentik proxy**, owner only.
  **НЕ native account SSO**: соответствующая native интеграция требует лицензии;
  n8n может спросить свой пароль после Authentik. UI и `/rest/settings` дают302 через
  оба IP. Machine endpoint ingress приоритетнее и идёт напрямую к n8n: webhooks,
  forms, health, native `/api/v1` и credential OAuth callbacks не зависят от IdP.
  Проверено health200, no-key API401, missing webhook404, не login page.
- **Wiki — native OIDC включён 2026-11-01**, `/login` ведёт в Authentik. Только
  owner сохраняет local fallback `/login?local=1` (username `admin`, текущий пароль).
  Tim сохраняет прежний editor ID/роль по exact UUID; его local password/старые
  local sessions не принимаются. Остальные observers reader. Real temporary
  observer password/TOTP/consent/OIDC/PKCE прошёл, write403; MCP read работает.
  Source/image/chart и backup: `deploy/wiki-runtime/oidc/README.md`. Начальный saved
  owner password stale401, не сбрасывали; hashes исходных двух users сохранены.
  Прямые WG-IP:443 сейчас имеют чужой cert из-за отсутствующих Wiki VHs в live
  gateways; public оба IP работают. Не отключать TLS и не запускать вслепую старый
  wiki-editor-access role по уже вынесенному private-gateway.
- **Kuma НЕ считать мигрированной.** Public status сохранён; admin/shared sockets
  требуют безопасной интеграции. В установленной auth реализации нет native OIDC.
- LiteLLM, CI/robots, MCP/API, VPN и другие machine credentials не подменять SSO.
  Каталог покрывает восемь foundation-managed portal services (Argo CD отдельно), не буквально все endpoints кластера.

## Linux / kubeconfig — уже исправлено live

На socrat-0 был root:root **0644** admin kubeconfig. Теперь **root:alchemmist 0640**,
проверена исключительность owner group, K3s mode/group сохранены и в live config,
и в initial install/HA templates. Owner kubectl работает, Tim не читает credential.

Роль users применена на **всех 4 нодах**: exact authorized_keys вместо append,
состояния present/disabled, hosts, запрет root-equivalent groups/неявного sudo.
Root-проверка на всех нодах: 2 intended Tim keys, pubkey=yes, PAM=yes, effective
sudo запрещён, admin kubeconfig недоступен. Приватного ключа Tim у нас нет,
фактический сетевой SSH login от его имени не имитировать.

`sudo -l -U tim` может вернуть rc0 даже с текстом "not allowed"; verifier проверяет
текст политики в C locale, а не только rc. На Arch учитывать shell OSC markers.
`ansible/roles/users/files/verify.py` выводит только безопасные метаданные.

Пароль sudo владельца в Git/инвентарях/логах НЕ сохранять. На четырёх нодах sudo
сработал; socrat-3 inventory переведён с su на проверенный sudo.
Использованные временные helper/inventory файлы удалены, helper содержал только
чтение transient environment, не пароль. Не повторять секрет из чата.

**Важно:** chmod не отзывает ранее скопированный cluster-admin client certificate.
Историческую экспозицию/план rotation оценить отдельно. CA не ротировали, ноды не
выключали. Observer ClusterRole пока без human bindings; IdP group не равно
kube-apiserver/Rancher principal. Никаких новых cluster-admin kubeconfig людям.

## Источники и reconciliation

- `docs/identity/access-management.md` — текущая матрица, эксплуатация и ограничения.
- `deploy/identity/{services,account-mappings}.json` — reviewed services/identities.
- `ansible/roles/authentik/`, playbook `authentik.yml` — foundation и proxy gate.
- `identity-integrations.yml`, explicit `identity_oidc_services` (default empty).
- Grafana/Harbor Helm загружают отдельные identity overlays при activation Secret.
- WebUI playbooks deployment/HTTPS/upgrade/tool-guard импортируют conditional
  `identity-webui-reconcile.yml`, чтобы следующие Helm изменения не стирали OAuth.
- Изменения OTel в общих файлах не перезаписывать; весь monitoring upgrade ради
  auth не запускать. Обычные local login не выключать до проверенного emergency пути.

## Резервирование и незавершённое

Encrypted AES-256-GCM backups вне Git на Mac `~/.config/homelab/`, key
`identity-backup.key` 0600, в кластер не отправлялся. CLI:
`identity-backup.py --service authentik|harbor|open-webui`,
`identity-restore-check.py --service ...`.

Проверены isolated Authentik PG restore; Harbor PG18 restore + 3 blob SHA-256;
WebUI SQLite integrity + два исходных user ID. Это **не full app/site DR**.
WebUI restore check использует private temporary SQLite file с cleanup из-за WAL
header. Архивы encrypted; не копировать plaintext credentials в evidence/Git.

Открыто: Kuma integration, owner-only legacy fallback в остальных apps, n8n native license decision, owner/Tim browser
acceptance других apps, координированное onboarding/offboarding и revocation сессий,
API keys/SSH/VPN, scheduled independent backups/key escrow/full restore,
scoped RBAC/rotation нового machine admin API, историческая kubeconfig exposure/rotation.
IdP disable не отзывает автоматически уже выданные app/API/SSH credentials.

WG keys/routes/firewall не меняли. Не назначать одну подсеть нескольким direct WG
peers: нужен gateway+ACL/failover. Root на чужой ноде = доверие к workloads/secrets
на ней; SSO/taints/NetworkPolicy не устраняют эту границу. На том этапе NetBird
ещё не был внедрён; последующее внедрение и ограничения описаны в [актуальном справочнике](netbird.md).

### Wiki implementation / latest acceptance

- Native Authlib code/PKCE/nonce/signature/aud/exp with pinned issuer; no custom JWT validation.
- Narrow reproducible derivative in `deploy/wiki-runtime/oidc/`, vendored chart + Secret
  hook. Actual REGISTRY manifest digest is `sha256:64d27d6f320ab7440be82578d1d73193278e6b12f77127776b715c2e98b17515`.
  Podman's local RepoDigests was different after registry manifest conversion;
  first rollout was automatically rolled back, then corrected, pre-pulled and accepted.
- Wiki lives on **socrat-3**, not socrat-0. Discover PVC affinity before any backup pod.
  Frozen full-volume copy made with writer stopped; old app resumed during encrypted
  off-node transfer; snapshot DB integrity/IDs/hash preservation checked. Temporary
  backup/image/smoke resources deleted. Do not repeat a slow network transfer with
  the production writer stopped. Full application DR still not tested.
- Fresh Authentik backup after adding Wiki client exists on Mac. Local owner Wiki
  **saved initial password** returned401; CURRENT password not changed/reset. Owner
  must test his current fallback. Policy/no-IdP fallback tested with known fixture
  credentials; real owner did not enroll any fake factor.
- Native Wiki observer MFA flow passed; write403; existing configured MCP tool
  `wiki_list_pages` still works. Callback access logging disabled via UVICORN env.
- Additional **Open WebUI** observer OIDC flow passed with active native Auth row.
  **Do not set Auth.active=False to disable just passwords**: get_auth in its native
  MFA subsystem also rejects OIDC (verified on a temporary fixture, cleaned up).
  No such change applied to Tim. Native password-only restriction needs another
  mechanism; don't falsely mark other services owner-only fallback.
- Generic source and 9 regressions recorded in hugo-docs commit `c6ffb18`; no new
  tagged release. Homelab patch is self-contained/reproducible and source publication
  is organized separately from unrelated dirty work. Historical evidence records
  the pre-publication state, not current Git status. After pushing main, check Fleet
  bundle/running image rather than assuming a commit alone proves GitOps acceptance.

### Уточнение владельца о полном объёме

Нужна миграция **всех сервисов кластера с человеческой авторизацией**, включая
**LiteLLM admin UI** (теперь native OIDC + PKCE; реальная приёмка владельцем ещё нужна), а не только portal apps. Старые
серверные методы входа — только владельцу как fallback. Полный live inventory
и проверка всех прямых/приватных auth-paths ещё не завершены. Machine API keys,
robots, webhooks и MCP отдельно: нельзя заменить их интерактивными редиректами.
Не считать текущую работу завершением всей миграции.


## LiteLLM и иконки dashboard — 2026-11-01

- Исправлено реальное отсутствие LiteLLM: создан native Generic OIDC provider/application с точным `/sso/callback`, PKCE, обычным обязательным MFA и owner-only admission. Вход: `https://llm.alchemmist.xyz/sso/key/generate`.
- Reviewed Authentik UUID владельца → существующий `socrat-admin` / `proxy_admin`; ни email, ни имя не выбирают административный ID. Пароль/IDs/roles старых записей не менялись. Реальный owner MFA не подменялся тестовым.
- Browser smoke: временный observer получил отдельный UUID-based read-only ID, прошёл TOTP/consent/OIDC и серверную проверку роли. Его одиночный temporary admission binding, аккаунты и UI keys удалены. Production admission снова только owner.
- Существующий Open WebUI virtual key по-прежнему читает models; без ключа 401, без browser redirects. Master/salt/DB Secrets, config и явные OTel env совпали с encrypted pre-change snapshot. vLLM не перезапускался; LiteLLM обновлён обычным graceful rollout.
- `/fallback/login` сохранён для старого owner DB password. Сам пароль не сбрасывался/не проверялся; полноценная приёмка owner login/recovery ещё требуется. Free SSO установленной версии ограничен пятью пользователями; обходов лицензии нет.
- У Argo CD добавлен официальный pinned SVG; Wiki заменена с BookStack на исходный круглый Socrat из `deploy/litellm/branding/socrat-icon-v1.png`, версия 512px. LiteLLM использует тот же собственный favicon. Все девять разрешённых media URLs реально проверены HTTPS 200 + SHA-256; настройки Argo CD provider/policies не менялись.
- Encrypted backup `litellm-before-oidc-20261101.aesgcm`: decrypt/authentication и archive listing проверены, полный restore НЕ выполнялся. Подробности и команды — `docs/litellm.md`.
