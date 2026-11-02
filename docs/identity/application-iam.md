# Гранулярный IAM приложений

## Что меняется — и что не меняется

Это **аддитивная миграция без выдачи новых прав людям**. `homelab-*` и
`lms-students` остаются действующими; существующие разрешения владельца и Tim,
их UUID, локальные аварийные учётные записи и точные привязки subject не заменяются.
Текущий `lifecycle.json` содержит только этих двух существующих пользователей,
`state: preserve` и пустые `appGroups`. Он не выключает аккаунты и не снимает
старые группы (у владельца также остаётся `lms-students`).

Источники истины:

- `deploy/identity/services.json`: прежние `groups` плюс `appRoles`, `admission`,
  `groupsScope`. Имя новой группы: `app-<service>-<role>`.
- `deploy/identity/account-mappings.json`: **рассмотренные старые связи**, не каталог
  будущих сотрудников. UUID Tim подтверждён GET-аудитом; старые ID приложений,
  email для проверки и роли не изменены. Email **не** является ключом объединения.
- `deploy/identity/lifecycle.json`: точные username + UUID, желаемые **только app-**
  членства и состояние существующих людей. Удаление строки не означает увольнение.
- `deploy/identity/access-policy.yaml`: индекс политики и границ ответственности.

`prepare_app_iam.py` подготавливает только пустые app-группы без superuser,
родителей, детей, пользователей и RBAC-ролей, с маркером
`attributes: {homelab_app_iam: 1}`. Чужая одноимённая группа не усыновляется.
**Полный `configure.py` — НЕ команда этой миграции.** У него top-level side effects:
он может менять owner privileges, MFA stages, scopes, providers, applications и
outpost. Не запускать и не импортировать его ради создания app-групп/bindings.
Для pinned Authentik **2026.8.5** проверяются явные `is_superuser: false`,
**`parents: []`** (M2M, не устаревший singular `parent`) и `roles: []`.
Missing/null/incomplete responses запрещены; **любое** наследование, включая
owner-superuser или RBAC ancestor, блокируется **до** assignment, не после grant.
Тесты fake API учитывают текущие поля; это не замена GET-аудиту и реальному MFA/
consent browser acceptance владельца/Tim. До него новые live assignments запрещены.
Существующие app-членства не переписываются foundation-контроллером. Владельцу
не добавляется ещё одна административная группа: его прежний `homelab-owner`
остаётся единственным источником административного сопоставления.

**Допуск в Authentik application ≠ роль внутри приложения.** Привязки application
имеют режим `any`: прежние группы ИЛИ новые app-группы. Группа app не наследует
глобальную роль. Неизвестная/отключённая/инвертированная привязка, user/policy binding,
дубликат или другой режим — ошибка, а не повод молча затереть изменения в UI.
Подготовительный инструмент добавляет только отсутствующие разрешённые связи и
ничего не удаляет. Полной транзакции/CAS между объектами/API нет: частичный сбой
означает STOP, ручную GET-инвентаризацию и новый review, не автоматический retry,
rollback, усыновление посторонних объектов или восстановление старых паролей.

## Матрица: допуск отдельно от полномочий

| Приложение | Новые группы | Что они действительно дают | Ограничение |
|---|---|---|---|
| Grafana | `app-grafana-viewer`, `app-grafana-editor` | OIDC-допуск + Viewer / Editor | GrafanaAdmin по-прежнему только `homelab-owner`; Editor не server admin, но может менять dashboards — выдавать только после review |
| Open WebUI | `app-open-webui-user` | OIDC-допуск + user | Admin только `homelab-owner`; email merge выключен; старые user IDs/chats сохраняются |
| Wiki | `app-wiki-reader`, `app-wiki-editor` | OIDC-допуск + reader / editor | Точные subject overrides приоритетнее групп: Tim **остаётся editor**, владелец admin; публичное чтение и MCP отдельно |
| Harbor | `app-harbor-user` | OIDC-допуск, не системный администратор | Проекты/репозитории/роботы — native Harbor RBAC, отдельное согласование; admin group не меняется |
| n8n | `app-n8n-user` | Только Authentik MFA-gate браузерного UI | **Не native SSO и не роль n8n**; native аккаунт/роль нужны отдельно; machine-маршруты не меняются |
| Rancher | `app-rancher-user` | Подготовлена только app admission | `assignable: false`: restricted principal allowlist и native grants остаются ровно для рассмотренных UUID. Новым людям нужны отдельные scoped bindings, без копирования owner |
| LMS | `app-lms-student` | Подготовлена только app admission | `assignable: false`: развёрнутый образ принимает одну `LMS_OIDC_ALLOWED_GROUP=lms-students`; нельзя обещать, что новая группа даст вход |
| LiteLLM | Нет новых групп | Прежний owner-only native OIDC + точный UUID → `socrat-admin` | Не расширяем reviewed identity expression и не выдаём proxy_admin |
| Uptime Kuma | Нет новых групп | Только прежняя portal tile | Tile не защищает native admin UI/socket; миграция SSO не завершена |
| Argo CD / x-ui | Не управляются этим catalog/controller | Существующая отдельно управляемая политика | См. ownership ниже; нет самовольного расширения owner-only/reviewed доступа |

Все новые OIDC-проверки групп получают явный scope `groups` с объектом claims
`{"groups": [...]}`; это не изменение `sub_mode`. Native MFA,
`default-provider-authorization-explicit-consent`, строгие callback URI,
TLS и PKCE не ослабляются. Proxy n8n/x-ui сохраняет свой implicit-consent flow:
это не подмена native consent у остальных приложений.

## Кто перезапишет изменения из UI

| Контроллер / файлы | Авторитетная область | Где допустимы ручные изменения |
|---|---|---|
| `authentik/files/prepare_app_iam.py`, `services.json`, `account-mappings.json` | Только create-only пустые allowlisted app-группы; отдельный stage — пустые app bindings | Нет human assignment, repair, PATCH/DELETE или native rollout; любое расхождение требует review |
| `authentik/files/configure.py`, `services.json` | Полный Foundation app/providers, группы, bindings, scopes, MFA validation; **не команда app-IAM миграции** | Пароль, MFA devices, recovery codes, native consent принадлежат человеку. Managed provider/MFA/settings править в Git. Повторный полный запуск требует отдельного review всей write surface |
| `authentik/files/lifecycle.py`, `lifecycle.json` | Только явное ручное применение app-членств и active/disabled | UI-членство расходится с декларацией и следующий **явно одобренный** apply его снимет; фонового apply нет. Остальные группы/пароли/MFA не управляются |
| `identity_integrations/files/integrate.py` + identity overlays | Grafana OAuth env, Harbor `CONFIG_OVERWRITE_JSON`, WebUI OAuth env; Wiki Secret с role/subject maps | Изменение этих параметров в UI/Secret временное. Harbor project RBAC, native n8n роли — отдельно, не порождаются из app-группы |
| Rancher branch `integrate.py` | restricted principal list; managed mirror bindings для старых local identities | Ручная правка `identity-*` binding будет сверена с оригиналом. Прямое изменение исходных grants — отдельная привилегированная операция, не автоматическое onboarding |
| Wiki `deploy/wiki-runtime/oidc/oidc.py` + integration Secret | Групповые роли и рассмотренные subject overrides | Обычный UI role edit будет заменён при следующем OIDC login. Изменения extension требуют **rebuild/deploy runtime**, не только Secret |
| Grafana monitoring Helm / Harbor Helm | Загружают identity overlay при наличии activation Secret | Не выполнять полный monitoring upgrade ради OAuth: он затрагивает не относящиеся к IAM ресурсы |
| WebUI playbooks | Условный identity reconcile после deploy/upgrade | `ENABLE_OAUTH_PERSISTENT_CONFIG=False`: UI OAuth config не источник истины; не перетирать OTel env целым старым snapshot |
| Argo CD `argocd_oidc/files/configure.py`; `deploy/argocd/values.yaml` и `deploy/platform/argo-cd/values.yaml` | Отдельный provider/bindings и native Argo RBAC | Legacy platform-operator уже отображается в admin; **не расширяем это**. Контроллер ожидает bootstrap-token env в pod и единственный groups mapping: после retirement/появления второго mapping нужна отдельная исправленная миграция, не обход защиты |
| Authentik Helm / Argo `deploy/argocd/apps/authentik.yaml` | K8s deployment, values из `deploy/platform/authentik/values.yaml`, selfHeal | Это не декларация БД пользователей Authentik. Полный `authentik.yml` использует bootstrap values из другого пути; не смешивать upgrade с этой app-policy миграцией |
| LiteLLM / x-ui controllers | Собственные строго рассмотренные owner policy/UUID | Не расширять через foundation/lifecycle; x-ui имеет отдельную SSH-lane границу, файлы не менялись |

GET-аудит 2026-11-02 подтвердил Helm release labels у Grafana, Harbor, WebUI,
Authentik, Argo и Wiki. `managedFields` в обычном ответе kubectl были пустыми:
это **не** доказательство отсутствия других writers. Сведения об ownership выше
получены из исходников контроллеров/Helm/Argo; все UI writers не инвентаризированы.

## Подготовка без выдачи прав: два отдельно рассмотренных этапа

В этой реализации **ничего не применялось к production и ничего не push-илось**.
Code/test readiness не означает live approval. Ниже — граница инструмента, а не
разрешение на запуск apply. Сначала независимый owner break-glass, защищённый
backup и свидетельство проверенного восстановления; затем change window и пауза
всех UI/controller writers. Не читать/печатать private cache целиком, API responses
или Secret diff. Проверить live API schema pinned Authentik **2026.8.5** до записи.

### Write boundary

`ansible/roles/authentik/files/prepare_app_iam.py` — самостоятельный CLI, не импортирует
`configure.py`. По умолчанию `plan`; `plan` и `check` вызывают **только GET**.
`check` возвращает 1, если нужны create, 0 если выбранный этап уже выполнен.
Локально они создают только private lock, не journal и не API-объекты.

- **Stage A `groups-only` (default):** максимум девять `POST core/groups/`, только
  девять имён из матрицы выше и точный список appRoles из `services.json`.
  Payload явно задаёт `is_superuser: false`, `parents: []`, `children: []`,
  `users: []`, `roles: []`, `attributes: {homelab_app_iam: 1}`. Existing group
  требует те же явные поля; missing/null, inheritance, membership, RBAC, чужой
  marker, лишняя `app-*` группа или duplicate — STOP, не «исправление».
- **Stage B `groups+empty-bindings`:** отдельный plan/review **после Stage A**.
  Все девять групп должны уже существовать: инструмент не угадывает их будущие PK.
  Максимум девять `POST policies/bindings/`, точные application/group PK пары из
  свежего inventory. `enabled: true`, `negate: false`, `failure_result: false`,
  `order: 100`; ни user, ни policy. Только семь существующих приложений с
  `policy_engine_mode: any` и существующими provider links. Неизвестные, duplicate,
  missing-field, disabled, negated, user/policy bindings на этих targets — STOP.
  Все legacy bindings должны уже присутствовать; они не меняются и не создаются.
  Другие applications/bindings остаются защищённым baseline, не входят в управление.

В обоих этапах owner/Tim должны быть активными internal identities с **pinned
UUID** из рассмотренного mapping и неизменёнными legacy членствами. Любое app-
членство блокирует этот инструмент подготовки. Никаких PATCH/DELETE, создания
users/apps/providers, membership/MFA/outpost/roles/native writes. Empty bindings
не дают людям доступ и не доказывают, что native role mapping работает.
Stage A сам по себе не завершает admission foundation: lifecycle check может
закономерно отказать до Stage B. Rancher/LMS остаются nonassignable.

### План, evidence и отдельно одобренный apply

1. С reviewed commit скопировать на socrat-0 в существующий **owned 0700** cache
   `~/.cache/homelab-authentik/` только `prepare_app_iam.py`, `services.json`,
   `account-mappings.json` (0600). Не заменять credentials, login files, clients,
   journals или signing keys. Использовать прежний проверенный SSH host key/alias.
   `credentials.json` должен быть owned regular 0600, не symlink; предпочтительный
   ключ `AUTHENTIK_API_TOKEN`, compatibility alias `AUTHENTIK_BOOTSTRAP_TOKEN`.
   Если присутствуют оба, значения должны совпадать. Token не передаётся в argv.
   Используется только фиксированный HTTPS origin, системная TLS verification;
   redirects запрещены, `--insecure` нет. Не расширять permissions ради обхода STOP.
2. Первый GET-only plan можно посмотреть без evidence:

   ```sh
   CACHE="$HOME/.cache/homelab-authentik"
   umask 077
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups-only
   ```

   Inventory **всех страниц** включает groups, users/memberships, providers/all
   плюс detailed OAuth2/proxy, applications, global bindings, MFA validation/TOTP
   и stages/all, flows/instances/bindings, propertymappings/all и outpost instances.
   В stdout — только allowlisted requests, tool SHA и hashes; raw responses и
   provider credentials не печатаются и не пишутся в journal. MFA devices, факторы,
   recovery codes и native databases этот инструмент не читает/не валидирует.
3. В отдельном private 0600 JSON `preparation-evidence.json` оператор фиксирует
   **реальные** evidence, не placeholders:

   ```json
   {
     "version": 1,
     "reviewed_commit": "<40 lowercase hex: reviewed source commit>",
     "reviewed_tool_sha256": "<64 lowercase hex: tool_sha256 from plan>",
     "backup_sha256": "<64 lowercase hex: protected current backup evidence>",
     "restore_test_sha256": "<64 lowercase hex: reviewed recovery test evidence>",
     "recovery_owner": "<responsible operator and protected evidence location>",
     "change_window": "<approved window/change reference>",
     "writers_paused": true
   }
   ```

   Это **операторская аттестация**: helper проверяет структуру, hashes и совпадение
   своего исходника, но не открывает backup и не выполняет restore, не подтверждает
   достижимость break-glass и не проверяет review commit в Git на remote host.
   Проверка актуальности backup, восстановления и review commit/input diff —
   обязательный внешний gate, а не свойство наличия JSON. Не писать в evidence
   секреты/response bodies. С evidence получить **новый** plan:

   ```sh
   EVIDENCE="$CACHE/preparation-evidence.json"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups-only \
     --evidence "$EVIDENCE" > "$CACHE/preparation-plan.json"
   ```

   Digest включает tool hash, полный catalog/mapping, stage, evidence, hashes
   **свежего полного baseline**, точные method/path/payload операции. Review должен
   охватить все эти inputs и точный список запросов; сохранить approval digest
   независимо. Не получать approval автоматически из текущего plan в apply shell.
4. Только после отдельного approval на этот digest:

   ```sh
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" apply --stage groups-only \
     --evidence "$EVIDENCE" --approve-sha256 "$REVIEWED_PLAN_SHA256"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" check --stage groups-only
   ```

   Apply без evidence или с другим baseline/approval откажет до POST. Перед первым
   POST выполняется ещё один полный fresh snapshot; после **каждого** POST — полный
   GET и проверка, что изменилось только возвращённое созданное object. Затем
   final GET/check. Любое постороннее изменение останавливает дальнейшие POST.
   Уже существующие объекты сравниваются без «нормализации»/repair. Изменение даже
   protected config или активности человека требует нового plan/review.
5. Если нужны admission bindings, отдельно рассмотренный Stage B:

   ```sh
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" plan --stage groups+empty-bindings \
     --evidence "$EVIDENCE" > "$CACHE/preparation-bindings-plan.json"
   # STOP for independent review of the new baseline, PK pairs and digest.
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" apply --stage groups+empty-bindings \
     --evidence "$EVIDENCE" --approve-sha256 "$REVIEWED_BINDINGS_PLAN_SHA256"
   python3 "$CACHE/prepare_app_iam.py" "$CACHE" check --stage groups+empty-bindings
   ```

   После Stage B текущий preserve/empty manifest должен давать ноль lifecycle
   операций: `lifecycle.py plan`, затем `check`. **Lifecycle apply не нужен.**

### Lock, journal и частичный сбой

Все CLI действия берут exclusive nonblocking local lock `.app-iam-prepare.lock`;
он не удаляется при освобождении. Это защита только cooperating invocations на
**этом cache**, не UI, других hosts/cache или full controllers. Distributed lock
и conditional API transaction/CAS отсутствуют; competing writers должны быть
остановлены на всё окно. GET snapshot также не является серверной транзакцией.

Apply создаёт private 0700 `app-iam-prepare-journal/<run-id>/`: atomic 0600
`run.json` и отдельный JSON каждого запроса, fsync durable intent **до POST**, затем
PK/status и hashes GET-проверки. Ни response bodies, ни credentials не сохраняются.
Crash, timeout, schema mismatch, drift или ошибка на N-м POST: **fail-stop**, без
rollback/retry и без следующих create. Pending может означать, что POST уже дошёл.
Незавершённый journal блокирует все следующие apply, даже если новый plan пуст.

Сохранить journal, вручную сделать read-only inventory и сопоставить созданные
PK/payload/результаты с одобренным plan; не усыновлять одноимённые посторонние
ресурсы. Только после отдельного incident review можно вручную архивировать
разобранный run **вне активного journal directory**, документировать partial
результат, получить новый plan/approval и продолжить. Автоматического resume или
journal-clear нет. Не удалять lock/journal «для починки», не replay `configure.py`,
не восстанавливать целиком IdP ради пустых групп. Deletion/cleanup — отдельное
рассмотренное административное изменение, не функция этого helper.

## Native integrations: отдельный gated rollout

Подготовка выше **не запускает integrations playbook** и не является разрешением
на него. Native OAuth env/Secret/role maps, Wiki runtime rebuild и browser login
меняют другую write surface и требуют собственного reviewed plan, backup/recovery,
change window и per-service acceptance. Не запускать полный integrations playbook,
monitoring/Helm upgrade или prune «ради пустых групп»; не включать Rancher/LiteLLM/
Argo повторно в этот change.

Перед выдачей новых app-членств отдельно подтвердить owner/Tim login с их
собственным MFA/consent (без извлечения факторов), прежние UUID/native user IDs,
Tim editor Wiki / viewer Grafana / user WebUI, owner admin; machine keys/webhooks
и независимый owner fallback. Wiki extension требует отдельного rebuild/deploy
по `deploy/wiki-runtime/oidc/README.md`. Существующие smoke helpers могут создавать
аккаунты/сессии — это production writes, не read-only acceptance. Только после
успешной native приёмки разрешать отдельные reviewed lifecycle изменения;
существующим людям миграция app-групп не требуется.

## Onboarding настоящего человека

1. Владелец утверждает конкретные приложения/роли и native scopes. Не давать
   `homelab-owner`, platform-operator или kubeconfig для «удобства входа».
2. Создать **отдельного** человека штатным Authentik admin/enrollment flow.
   Саморегистрация/SMTP здесь не включаются. Изначально без superuser и без app/legacy
   grants; доставить enrollment/временный пароль защищённым независимым каналом,
   потребовать смену пароля и его собственное MFA. Не копировать чужой TOTP.
3. GET-проверкой получить точный UUID; добавить только реальную учётную запись в
   `lifecycle.json` (`state: preserve` либо осознанное `active`, конкретные appGroups).
   Для native account linking нужен отдельный review существующего ID, не совпадение
   email. Не добавлять человека в `account-mappings.json` только ради provisioning:
   это legacy migration contract. При missing pinned owner/Tim foundation теперь
   останавливается, а не создаёт другую личность со старым именем.
4. На owner node выполнить `plan`, проверить все операции и digest. Применение:

   ```sh
   python3 "$CACHE/lifecycle.py" "$CACHE" apply --approve-sha256 "$REVIEWED_PLAN_SHA256"
   python3 "$CACHE/lifecycle.py" "$CACHE" check
   ```

   Digest связан с input, UUID, текущими группами/active и операциями. При изменении
   состояния нужен новый plan/review. Lock защищает только этот инструмент; UI и
   другие контроллеры не блокируются. Нет распределённой транзакции/CAS: остановить
   конкурирующих writers. Частичный apply — повторно plan, не rollback всего IdP.
5. Проверить положительный вход и **отказ** для чужих приложений/операций. Harbor
   project RBAC, n8n native account и machine credentials оформить отдельно.
   Rancher/LMS с `assignable: false` инструмент откажется назначать.

## Offboarding и срок действия отзыва

- Записать явное `state: disabled`, `appGroups: []` и применить проверенный plan.
  Сначала disable IdP, затем снять управляемые app-членства. Владелец защищён от
  disable/изменения app-членства этим инструментом. Legacy группы сохраняются:
  **это не полное удаление прав** и не повод автоматически снова включить аккаунт.
- Удаление пользователя из manifest **не** деактивация. Повторный foundation не
  включает initialized disabled аккаунты и не меняет его пароль/MFA.
- Отдельно отозвать IdP sessions, OAuth grants/access/refresh tokens штатными
  средствами Authentik; зафиксировать проверку отказа входа. Инструмент не угадывает
  API endpoint массового session revoke и не обещает успешного logout браузеров.
- Отозвать native sessions и локальные способы входа **в каждом** приложении:
  Grafana, WebUI, Harbor, Wiki, Rancher, n8n, LMS и прочих. Группы/роль обычно
  пересчитываются при новом login/refresh, не при каждом запросе. У Wiki subject
  override Tim editor остаётся рассмотренным исключением; отзыв app-группы не
  удаляет native session, а legacy observer всё ещё допускает новый вход, пока
  аккаунт активен. Native session/token следует отзывать отдельно, а не менять
  этот override тайно.
- Native OIDC provider TTL сейчас 5 минут access / 8 часов refresh — **не верхняя
  граница native session**. Grafana/Argo имеют 8-часовую policy, другие cookies,
  proxy sessions и уже выданные JWT могут жить по своим правилам. Прокси n8n в
  read-only аудите имел 1 час access / 30 дней refresh; не сокращалось без review.
- Отозвать личные API keys/PAT, Harbor robot при личной принадлежности, WebUI keys,
  LiteLLM keys, wiki API tokens/MCP, Rancher tokens/kubeconfigs и sharing links;
  не ломать организационные machine accounts без передачи владения.
- Host/SSH/VPN и активные shell/tunnel sessions — отдельный согласованный runbook.
  Этот commit не меняет NetBird/SSH/WireGuard lane. Снять группу в IdP недостаточно,
  чтобы закрыть эти каналы или уже скопированный сертификат.
- Записать per-service результат, время и остаточные окна; не заявлять «все сессии
  отозваны» по одному успешному lifecycle check. Восстановление старого backup может
  воскресить аккаунт/гранты: повторить актуальное offboarding перед открытием входа.

## Откат

До выдачи app-членств откат — вернуть только новые public OAuth settings/role maps
к рассмотренной предыдущей версии и отдельно убрать только новые app bindings,
если это действительно требуется. Legacy bindings, точные subject links, пароли,
MFA и базы пользователей не удалять. Не восстанавливать целиком старый Deployment
поверх OTel/других параллельных изменений и не применять старый IdP backup ради
OAuth env. После реальной выдачи/отзыва прав rollback требует нового review:
автоматический обратный lifecycle apply может воскресить уже отозванный доступ.

## Проверки и оставшиеся блокеры

`tests/test_prepare_app_iam.py` проверяет current-schema fake API, оба ограниченных
этапа, GET-only default/plan/check, pagination, pinned UUID, все явные пустые
relations/marker, unexpected objects/bindings, protected snapshot drift, повторную
pre-write проверку, отсутствие любых иных permission side effects, TLS/token alias,
exclusive lock и private atomic per-request journal. Проверяются partial failure,
принятый сервером POST с потерянным ответом, journal failure до POST, post-create
посторонний drift и запрет автоматического retry/adoption. Это isolated tests,
**не live schema verification, backup/restore или native acceptance**.

`tests/test_app_iam.py` проверяет отсутствие исходных grants, идемпотентное
добавление/снятие, disable-before-remove, stale hash, несовпадение UUID,
защиту owner, отказ service accounts/чужих групп/наследования, pagination и
UI binding drift. `tests/test_identity.py` сохраняет проверки MFA/consent,
client credentials, legacy membership и non-superuser Tim. Native browser
приёмка новых app-ролей **не выполнялась**: это post-deploy задача.

Не завершены: native session revocation automation, LMS multi-group admission,
новые scoped Rancher principals, отдельная безопасная модернизация Argo controller,
Kuma SSO/admin/socket boundary, полная live-инвентаризация всех человеческих входов.
Наличие portal tile или пустой app-группы не закрывает эти блокеры.
