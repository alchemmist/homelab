# Identity / Authentik — актуальный статус

**1 ноября 2026, после второго rollout.** Пользователь подтвердил работу под
`alchemmist`, сообщил об отказе Grafana и разрешил sudo-применение/дальнейшую
миграцию. **NetBird не внедрять.** Посторонние OTel/VPN изменения сохранять.

## Что работает

- **Authentik:** https://auth.socrat.alchemmist.xyz/, chart/app **2026.8.5**, pinned
  SHA-256; server + worker + PG17.11 на socrat-0, retained local PVCs. **Не HA**.
- Обязательное MFA. Owner `alchemmist` уже вошёл и настроил свой фактор. Других
  устройств MFA за него не регистрировать/не сбрасывать пароль при stale initial file.
- Только `homelab-owner` — superuser; единственный человек в ней alchemmist.
- Создан **tim**, группа **homelab-observer**, initial credential вне Git в
  `~/.cache/homelab-authentik/tim-login.json` на socrat-0. Передавать вне чата,
  вход с личным TOTP и сменой initial password. SMTP приглашения пока нет.
- Семь плиток с SVG-иконками, загруженными в собственное media-хранилище Authentik;
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
  Каталог покрывает семь главных portal services, не буквально все endpoints кластера.

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
bootstrap admin token retirement, историческая kubeconfig exposure/rotation.
IdP disable не отзывает автоматически уже выданные app/API/SSH credentials.

WG keys/routes/firewall не меняли. Не назначать одну подсеть нескольким direct WG
peers: нужен gateway+ACL/failover. Root на чужой ноде = доверие к workloads/secrets
на ней; SSO/taints/NetworkPolicy не устраняют эту границу. NetBird обсуждать позже.

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
**LiteLLM admin UI** (ещё НЕ мигрирован), а не только семи portal apps. Старые
серверные методы входа — только владельцу как fallback. Полный live inventory
и проверка всех прямых/приватных auth-paths ещё не завершены. Machine API keys,
robots, webhooks и MCP отдельно: нельзя заменить их интерактивными редиректами.
Не считать текущую работу завершением всей миграции.
