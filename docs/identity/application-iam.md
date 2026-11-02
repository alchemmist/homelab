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

`configure.py` создаёт пустые app-группы без superuser/родителя/RBAC-ролей и с
маркером `attributes: {homelab_app_iam: 1}`. Чужая одноимённая группа не усыновляется.
Существующие app-членства не переписываются foundation-контроллером. Владельцу
не добавляется ещё одна административная группа: его прежний `homelab-owner`
остаётся единственным источником административного сопоставления.

**Допуск в Authentik application ≠ роль внутри приложения.** Привязки application
имеют режим `any`: прежние группы ИЛИ новые app-группы. Группа app не наследует
глобальную роль. Неизвестная/отключённая/инвертированная привязка, user/policy binding,
дубликат или другой режим — ошибка, а не повод молча затереть изменения в UI.
Контроллер добавляет отсутствующие разрешённые связи, но ничего не удаляет.
Полной транзакции между объектами/API нет: при ошибке возможна частичная безопасная
сверка, затем нужен повторный plan, не восстановление старых паролей.

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
| `authentik/files/configure.py`, `services.json` | Foundation app/providers, группы, bindings, scopes, MFA validation | Пароль, MFA devices, recovery codes, native consent принадлежат человеку. Managed provider/MFA/settings править в Git. Неизвестные bindings теперь блокируют запуск; известные отсутствующие будут восстановлены |
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

## Внедрение без выдачи прав

В этой реализации **ничего не применялось к production и ничего не push-илось**.
Предварительно проверить независимый owner break-glass, защищённый backup/restore,
свежие UUID и отсутствие конкурирующего reconcile. Не читать/печатать private cache
целиком и не делать diff Secret с данными в терминал.

1. Скопировать с reviewed commit на socrat-0 в существующий 0700 cache
   `~/.cache/homelab-authentik/` только публичные исходники (mode 0600):
   `configure.py`, `app_iam.py`, `lifecycle.py`, `services.json`,
   `account-mappings.json`, `lifecycle.json`. Не заменять `credentials.json`,
   `*-login.json`, `oidc-clients.json`, automation journal или signing keys.
   Использовать прежний проверенный SSH host key/alias; не отключать проверку.
2. **На socrat-0** после просмотра diff:

   ```sh
   CACHE="$HOME/.cache/homelab-authentik"
   python3 "$CACHE/configure.py" "$CACHE"
   python3 "$CACHE/lifecycle.py" "$CACHE" plan
   python3 "$CACHE/lifecycle.py" "$CACHE" check
   ```

   Foundation добавит пустые группы/bindings; lifecycle plan/check не вызывает
   изменяющих API запросов (создаётся лишь локальный private lock). До foundation
   check закономерно остановится на отсутствующих app-группах. Для текущего manifest
   после foundation ожидается **ноль операций**; lifecycle apply не нужен.
3. Применить только выбранные native integrations с новым `integrate.py` и public
   env. Например, из `ansible/`, с обычным проверенным inventory:

   ```sh
   ansible-playbook -i inventory/hosts.yml playbooks/identity-integrations.yml \
     -e '{"identity_oidc_services":["grafana","open-webui","harbor","wiki"]}'
   ```

   Wiki дополнительно требует rebuild/deploy `oidc.py` по
   `deploy/wiki-runtime/oidc/README.md`. Не включать Rancher/LiteLLM/Argo повторно
   ради этой миграции. Не запускать full monitoring/Helm upgrade и не включать prune.
4. Проверить owner/Tim native login с их собственным MFA/consent без извлечения
   факторов. Подтвердить прежние UUID/native user IDs, Tim editor в Wiki, viewer
   Grafana, user WebUI, owner admin; machine keys/webhooks и owner fallback отдельно.
   Существующие smoke helpers могут создавать временные аккаунты/сессии: это уже
   **production writes**, их не запускали в read-only аудите.
5. Только после успешной проверки native mapping разрешать отдельные reviewed
   lifecycle изменения; существующим людям миграция app-групп не требуется.

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
