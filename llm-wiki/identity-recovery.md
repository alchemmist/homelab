# Авторизация: backup, recovery, диагностика и evidence

Начало: [identity.md](identity.md). Любой recovery меняет доверенную систему:
проверить личность/полномочия оператора, pre-change snapshot и влияние на consumers.
Не запускать production restore по этому документу без отдельного incident plan.

## 1. Где находится чувствительное состояние

| Место | Что там / граница |
|---|---|
| `socrat-0:~/.cache/homelab-authentik/` | Private runtime deployment root, directory 0700/files 0600 |
| `credentials.json` в этом root | DB/installation secret material и legacy API-key alias нового machine admin; broad privilege |
| `automation-api.json`, `credentials-before-automation-*.json` | Secret-bearing exact-identity migration journal и pre-change rollback; не публиковать |
| `owner-login.json`, `tim-login.json` | Initial credentials + bootstrap markers; могут быть stale |
| `oidc-clients.json` | Stable confidential OAuth clients; не пересоздавать при потере файла |
| private integration journals/snapshots | Old config, exact identity bindings, потенциальные secrets |
| `theme-backups/`, brand journal, original flow-title file | Presentation rollback, не полный DB backup |
| Kubernetes runtime Secrets | Authentik/app client credentials/signing keys; refs публичны, bodies нет |
| `~/.config/homelab/` на owner Mac | Off-node encrypted backups и отдельный encryption key |

Не печатать credential files, Secret JSON/YAML, pod env, shell history с tokens,
callback URLs, MFA QR/seed, browser storage/cookies. Не сохранять Playwright
trace/HAR/video по умолчанию: они могут содержать всё перечисленное.

Encryption key по умолчанию `~/.config/homelab/identity-backup.key`, 0600,
**не отправляется в кластер**. Потеря key делает AES-GCM backup непригодным.
Независимый escrow/recovery доступ к нему ещё надо организовать отдельно.
Имена файлов и digest можно документировать; содержимое keys/archives — нет.

## 2. Что умеют существующие backup tools

`scripts/identity-backup.py`: `--service authentik|harbor|open-webui|litellm`.
По SSH запускает reviewed read-only collector, получает snapshot в память owner
Mac, шифрует AES-256-GCM с random nonce и authenticated header, пишет новый файл
0600 и SHA-256 sidecar. Не перезаписывает existing output. У remote collectors
stdout **содержит secrets/plaintext archive**: запускать через encrypting wrapper,
а не вручную в terminal/CI log.

```sh
# Из корня repo, в Python environment с cryptography. Директория заранее private.
python3 scripts/identity-backup.py --service authentik \
  --output "$HOME/.config/homelab/authentik-YYYYMMDDTHHMMSS.aesgcm"
python3 scripts/identity-backup.py --service litellm \
  --output "$HOME/.config/homelab/litellm-YYYYMMDDTHHMMSS.aesgcm"
```

Timestamp в примерах заменить реальным; не использовать predictable overwrite.
SHA sidecar подтверждает целостность transport/storage, а AES-GCM — аутентичность
с данным key. Ни то ни другое не проверяет логическую пригодность полного recovery.

- **Authentik:** PostgreSQL dump, protected config/credentials и `/data` snapshot;
  exact набор файлов смотреть в `ansible/roles/authentik/files/backup.py`.
- **Harbor:** DB + registry data/config/Secret snapshot; blob hashes проверяются
  отдельно. Snapshot не делает распределённый storage consistent сам по себе.
- **WebUI:** consistent SQLite backup через штатный SQLite механизм, config/Secrets.
- **LiteLLM:** custom PG dump, Deployment/ConfigMap, original env/DB Secrets,
  optional dedicated OIDC Secret. Dump содержит чувствительные account/key данные.
- **Wiki:** отдельный encrypted frozen-volume pre-migration snapshot был создан
  и проверен. Generic wrapper пока **не поддерживает `--service wiki`**; не выдумывать
  такой CLI. SQLite/WAL и volumes требуют reviewed quiesce/snapshot procedure.

Backup без schedule, off-site copy, retention alerts и escrow — manual capability,
не завершённая DR-система. Copy на том же physical node не независимый backup.

## 3. Restore check: что действительно проверялось

```sh
python3 scripts/identity-restore-check.py --service authentik \
  --backup "$HOME/.config/homelab/REVIEWED_AUTHENTIK_BACKUP.aesgcm"
python3 scripts/identity-restore-check.py --service harbor \
  --backup "$HOME/.config/homelab/REVIEWED_HARBOR_BACKUP.aesgcm"
python3 scripts/identity-restore-check.py --service open-webui \
  --backup "$HOME/.config/homelab/REVIEWED_WEBUI_BACKUP.aesgcm"
```

Это реальные операции создания disposable restore resources в cluster для PG,
а не read-only lint. PG работает socket-only без Service, временный `emptyDir`,
без runtime SA token; данные не записываются в production DB. Cleanup в finally.
Запускать только с достаточным запасом ресурсов и разрешением на такой test.

Проверены isolated Authentik PG/role groups, Harbor PG/admin/blob hashes и WebUI
SQLite integrity/сохранность исходных user IDs. Это **не full application recovery**:
не проверены все users/MFA/devices, сетевые endpoints, DNS, signing/token continuity,
восстановление ноды, consumers и реальные owner recovery logins.

LiteLLM pre-change archive `litellm-before-oidc-20261101.aesgcm`: authenticated
расшифровка и `pg_restore --list` прошли, а полный restore drill **не выполнялся**.
`identity-restore-check.py` пока **не принимает `--service litellm`**.
PG16 `pg_restore` отвергал archive format 1.16; более подходящий installed PG17
смог прочитать TOC. Для настоящего восстановления выбирать совместимый major/tool,
не считать успешный listing доказательством восстановления всей PG18 database.

Реестр санитизированного evidence — `deploy/identity/migration-evidence/`.
Хеши конкретных snapshots могут быть в evidence/старых заметках; не хранить
расшифрованный dump, recovery codes или key рядом в Git.

## 4. Recovery при недоступном Authentik

1. Отличить TLS/DNS/edge failure от server/worker/DB/PVC failure. Проверять readiness,
   certificate state, endpoints, volume attachments и ресурсы без dump env/Secrets.
2. Проверить оба trusted public edges с правильным Host/SNI. Не отключать TLS и не
   менять WG routing только потому, что private gateway даёт неправильный cert.
3. Не удалять PVC/PG, не uninstall release и не генерировать новый secret key.
4. Использовать заранее reviewed local owner recovery конкретного приложения,
   если он доступен. Он может зависеть от private network и реального owner password.
5. Если требуется восстановление IdP: сначала изолированный restore, затем отдельный
   утверждённый production cutover plan. Нужны БД, installation/signing keys,
   `/data`, client secrets, protected identity journals, TLS/DNS и корректная версия.
6. После восстановления проверить immutable user UUID и application subjects.
   Новая пустая IdP installation с теми же usernames — **не те же identities**.
7. Проверить все consumers, clock, token validation, positive/negative admission,
   owner личный MFA, машинные keys; обоснованно отозвать потенциально скомпрометированные
   sessions/tokens. Наличие backup не отменяет последствий компрометации.

Старый bootstrap API token retired вместе с akadmin после переноса consumers
на отдельный machine admin. Новый token пока тоже broad: scoped RBAC и rotation
остаются долгом, не скрытой гарантией least privilege. Legacy имя credential key
не означает, что старый bootstrap token ещё используется.

## 5. Rollback интеграции без уничтожения данных

Private snapshots предназначены для точечного восстановления config, не слепого
`kubectl replace` всего Deployment. Иначе можно стереть параллельные env/OTel,
placement, resource budgets или обновлённый image. Сначала сравнить current vs snapshot.

Для LiteLLM отключить только dedicated SSO env/Secret wiring по reviewed snapshot,
сохранить DB/master/salt/passwords/API keys. Owner `/fallback/login` не сбрасывать.
Provider/app отключать после решения, какой entrypoint должен остаться. Нельзя
исправлять user-count license failure обходом premium check.

Для Wiki сохранить original accounts SQLite и signing key; неверный key может
инвалидировать cookie, но не повод выдавать fallback всем. Immutable runtime image
и chart выбирать явно, без удаления PVC. Old non-owner password sessions не оживлять.

Theme rollback отдельный, см. [identity-frontend.md](identity-frontend.md): Brand UUID
и flow identity guards, original baseline, retained static assets. Он не является
откатом всей identity DB или auth migrations. Live rollback/reapply ради проверки
не делался, чтобы не прерывать реальные входы.

## 6. Таблица диагностики

| Симптом | Проверить прежде изменения политики |
|---|---|
| Плитка отсутствует | Реальное app existence, active user, admission bindings; не icon alone |
| `invalid_request` / provider denied | Client ID, exact callback, grant_types, issuer; Grafana incident был про grants |
| Новый пустой профиль | Subject mode, exact existing ID links, не произошёл ли email merge/new-user creation |
| Login есть, роль неправильная | Signed group claim + app role mapping + собственные app grants |
| MFA пропускается у нового человека | `not_configured_action`, native flow binding; не fixture-only success |
| Ранее выданный пароль не работает | Initial journal может быть stale; не reset реального password без owner |
| Wiki Tim не входит локально | Это intended owner-only fallback; использовать OIDC |
| WebUI OAuth исчез после disable user auth | `Auth.active=False` выключает также get_auth для OAuth |
| LiteLLM callback 500 | Runtime validators, custom scope claim names, account limits и state/PKCE; не печатать code/token |
| API внезапно отдаёт login HTML | Browser proxy захватил machine path; проверить route boundary, не отключать API auth |
| Follow redirect вместо авто-перехода | Открыт native inspector: intentional debug pause |
| `%(app)s` в heading | Raw flow title template; управляемые authorization titles уже `Redirecting` |
| История inspector повторяется | Native session snapshots общего flow, не unique checks одного app |
| Лупа недоступна observer | Нормально: debug API требует отдельного inspect permission |
| Theme assets перестали загружаться | Нельзя persistent signed media JWT URL; проверить immutable static endpoint/digest |
| CSS не меняет drawer | LitElement root не получает AKElement Brand injection; использовать exported parts |
| UI на русском после en default | `?locale=`/sessionStorage выше defaults; hidden picker не forced locale |
| kubectl apply слишком большой annotation | Server-side apply immutable asset CM, не client-side last-applied |
| OpenAPI List validation 503 | Separate documents/strict v3, не `--validate=false` |
| WG URL даёт чужой certificate | Отдельный private VH/TLS дефект; не ослаблять certificate verification |

## 7. Набор проверок и границы live-тестов

Offline (без credentials/cluster mutations):

```sh
python3 -m unittest discover -s tests -p test_identity.py -v
python3 -m unittest discover -s tests -p test_litellm_identity.py -v
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
python3 -m unittest discover -s tests -p test_authentik_flow_titles.py -v
cd ansible
ansible-playbook playbooks/authentik-branding.yml --syntax-check
ansible-playbook playbooks/identity-integrations.yml --syntax-check
ansible-playbook playbooks/identity-litellm-reconcile.yml --syntax-check
```

Read-only live controls check: `identity-branding-controls-check.py --run`,
в том числе второй edge. Это local-only browser layout challenge с denied inspector
API, не реальный owner login и не изменение server auth data.

Actual temporary-identity tests: `identity-branding-smoke.py --run`,
`identity-litellm-smoke.py --run`; создают identities, реальные временные TOTP,
app sessions/keys, а LiteLLM ещё scoped temporary admission binding. **Это writes**,
не read-only healthcheck. Не запускать массово/параллельно с user migration.
Fixture не owner, existing human factor не читается/не сбрасывается. Проверить
cleanup, включая temporary bindings/DB users/keys, даже при callback exception.

Старые `identity-grafana-smoke.py`, `identity-webui-smoke.py`, `identity-wiki-smoke.py`
тоже выполняют live mutations и не обязаны иметь guard `--run`; прежде запуска
прочитать именно текущую версию. Cleanup helper `identity-litellm-cleanup.py` не
является массовой командой удаления users: применять только к точной тестовой identity.

Owner сам подтвердил LiteLLM SSO; это не подтверждение всех app roles/recovery
passwords, личного Tim MFA или полной offboarding готовности. Owner inspector
исследован по его saved HTML и UI/CSS checks, без захвата его browser session.

## 8. Как оформить безопасную публикацию

1. Fetch origin и проверить dirty tree/outgoing commits. Параллельную работу не
   откатывать, не staging `.` и не force-push. Изменения могли уже попасть в main
   другим оператором — сначала пересмотреть log/diff, не копировать историю вслепую.
2. Stage только reviewed auth paths и guides. Исходные private Downloads HTML,
   backup archives, credentials, browser profiles, `/tmp` dumps/screenshots исключить.
3. Проверить staged diff: tokens/passwords/seeds/callback queries отсутствуют;
   публичные digests/UUID не путать с credentials, но реальную утечку не allowlist.
4. Выполнить focused unit/syntax/link checks и secret scan. Не утверждать, что
   прошёл весь repository suite, если запускались только профильные tests.
5. Commit/push в согласованную ветку без переписывания origin. Проверить remote
   commit, рабочее дерево и реально настроенные CI checks; отсутствие workflow
   не называть зелёным pipeline.
6. Push не равен deployment: branding/app controllers применяются отдельно,
   running images/Fleet/Argo readiness проверяются после соответствующего rollout.

## 9. Оставшийся backlog

Cluster-wide human-auth inventory; Kuma safe boundary; n8n license/native SSO;
личные Tim delivery/TOTP/private-key acceptance; owner recovery для каждого app;
legacy local sessions/old-password bypass audit кроме уже проверенного Wiki;
strict English enforcement для старых overrides; Native inspector JSON highlight/
Copy, grouping/filtering history; owner photo collection; independent backup
schedule/escrow/full DR; scoped machine admin API/rotation; historic kubeconfig exposure/
credential rotation; distributed Authentik/Harbor HA. Не закрывать эти пункты
по факту красивой login page или наличия encrypted archive.


## 10. Default Admin заменён машинной автоматизацией

`akadmin` и его bootstrap token удалены после guarded checks; daily human users —
`alchemmist` и `tim`. Outpost account оставлен. Новый `homelab-identity-automation`
имеет service_account type, непригодный для входа пароль и **широкие** admin API
права отдельной группы — не выдавать это за completed least-privilege RBAC.
Исторический ключ AUTHENTIK_BOOTSTRAP_TOKEN в private credentials теперь alias
этого token. Он не попадает в runtime Secret/pods через bootstrap.py.

Независимый node-admin recovery проверен официальной recovery-ссылкой на
временном admin, не на владельце; exact fixture cleanup завершён. Личный owner
recovery и full DR остаются отдельной приёмкой. Старые backup credentials после
retirement не восстановят API к текущей DB; сначала проверить journal/backup
consistency. Процедура, guards и доказанные ограничения:
[admin-automation.md](../docs/identity/admin-automation.md).
