# Authentik: пользователи, доступы и ежедневные операции

Начало: [identity.md](identity.md). Протокол/границы: [identity-architecture.md](identity-architecture.md).
Все операции с реальными правами требуют согласования scope владельцем.

## 1. Как пользователю войти

1. Открыть **https://auth.socrat.alchemmist.xyz/** с доверенным HTTPS.
2. Использовать личный username, не общий `akadmin`.
3. При первом входе указать выданный initial password, зарегистрировать **свой**
   TOTP в authenticator app и подтвердить кодом. Не передавать QR/seed помощнику.
4. Сменить initial password, проверить следующий вход собственным фактором.
5. Выбрать доступную плитку либо кнопку Authentik/SSO в самом приложении.

Обычная форма теперь объединяет native identification/password. Глаз пароля —
штатная функция password stage; MFA после неё остаётся обязательной.
Если в Authentik уже есть живая MFA-сессия, приложение может открыться сразу.
Это не обход MFA. Для чистого теста использовать private window, не удалять devices.

Прямая SSO-ссылка LiteLLM: **https://llm.alchemmist.xyz/sso/key/generate**.
Локальный owner recovery LiteLLM: `/fallback/login`; не путать с нормальным входом.
Wiki: `/login` — OIDC, `/login?local=1` — исключение только для существующего owner ID.

Если приложение отсутствует в library: проверить активность пользователя,
application group bindings и actual provider. Добавление картинки/плитки не чинит OIDC.
Не выдавать owner/superuser ради появления карточки.

### Если приложение всё ещё просит свой пароль

В 3x-ui и текущем n8n настроен **внешний MFA gateway, не native account SSO**.
После Authentik может оставаться штатная форма приложения без кнопки Authentik;
в неё вводят прежний пароль приложения, не пароль IdP. Активная родительская
MFA-сессия может сделать первый этап незаметным. Не обещать один вход вместо двух.

В 3x-ui исправлен cross-origin fetch при пропавшей/истёкшей gateway-cookie:
XHR получает401, native UI выполняет top-level reauthorization. После простоя
поля могут потребовать повторного ввода — это не silent refresh. Для n8n владелец
сообщил о сбое, но симптом ещё не воспроизведён; не объявлять его исправленным.
Диагностика и зафиксированные границы: [identity-gateway-troubleshooting.md](identity-gateway-troubleshooting.md).

## 2. Кто сейчас есть и что означают роли

| Group | Назначение и предел |
|---|---|
| `homelab-owner` | Единственный личный владелец `alchemmist`; Authentik superuser, явно mapped app admin |
| `homelab-observer` | Наблюдение только в допущенных приложениях; это не root/Secrets/exec |
| `homelab-project-maintainer` | Потенциальный reviewed project scope; не произвольный admin кластера |
| `homelab-platform-operator` | Инфраструктурный scope только после review; в Argo CD конфигурация даёт admin |
| `homelab-machine-owner` | Владение конкретной машиной, не автоматическое владение всем кластером |

Последние три группы созданы без спекулятивной раздачи людям.
Tim — личный `tim`, observer, со своими существующими IDs в Rancher/WebUI/Wiki.
В Wiki сохранено его прежнее исключение editor по точному subject; это не editor
для всей observer group. В WebUI он user, а не admin. LiteLLM production app owner-only.

Перед назначением группы читать **все app mappings**, а не только её название.
Например platform-operator в Argo CD — admin; в Grafana admitted non-owner — Viewer, кроме отдельно назначенного `app-grafana-editor` → Editor.
Имена групп — контракт интеграций. Переименование может отозвать/изменить доступы.

## 3. Как добавить нового человека

**Если это новый администратор кластера:** полный порядок
[Authentik/MFA → NetBird identity/device + JWT policy → отдельные SSH и
Kubernetes/app-права](netbird.md#как-добавить-нового-админа). Ни одна из этих
ступеней не выдаёт остальные автоматически. Linux-аккаунт создаётся ручным
[Ansible username + public key](ssh-user.md), без sudo и n8n.

### Перед созданием

Составить заявку: личный username, подтверждённая личность, какие приложения,
точные роли/проекты, нужен ли Linux/VPN, срок и кто одобрил. Отдельно установить,
есть ли старые app accounts с данными. Не создавать дубль поверх старого аккаунта.

Сделать private pre-change backup IdP и важных app DB. Подготовить owner recovery
и отдельную открытую owner-сессию; не экспериментировать на единственном доступе.
Пользовательские пароли/QR/tokens не включать в task, PR, logs или скриншоты.

### Вариант A: новый обычный пользователь через UI

В admin interface Authentik открыть управление Directory / Users (названия меню
могут меняться по версии), создать active личную запись без superuser. Установить
сильный временный пароль через штатное действие Set password. Выбрать только
одобренные группы. UI-настройки не считать автоматически перенесёнными в Git.

Передать initial credential через password manager / независимый защищённый
канал, а не публичный чат, Git или аргумент shell. SMTP invitation/reset delivery
ещё не считается настроенным. Проверить фактическую доставку лично получателю.
Первый вход и TOTP enrollment выполняет сам человек; recovery codes сохраняет
безопасно. Нельзя зарегистрировать device «за него для теста».

После создания записать reviewed immutable UUID и необходимые app ID mappings.
Если впоследствии переносить пользователя под bootstrap automation, нельзя просто
добавить его username в mapping: initializer остановится при existing user без
bootstrap journal. Это intentional guard от захвата существующего имени.

### Вариант B: контролируемый bootstrap из source

`deploy/identity/account-mappings.json` — реестр заранее reviewed людей и старых
application IDs. Формат следует существующим записям, но добавлять поля старых
app IDs следует **только когда сами ID реально проверены**. Не выдумывать UUID.

`configure.py` создаёт private `<username>-login.json` с initial password и
`initialized` marker. При первом bootstrap пароль задаётся один раз; после
`initialized=true` повторное применение не должно возвращать initial password.
Существующий username без journal — ошибка для manual identity review, не повод
удалить пользователя или синтезировать journal. Не менять marker на false.

Не копировать owner mapping новому человеку и не добавлять ему `homelab-owner`:
initializer намеренно запрещает второго owner и неожиданное owner membership.

**Важно:** текущий initializer — не полный user lifecycle controller. После
инициализации он не является авторитетным reconciler всех `is_active`/groups и
не реализует безопасное усыновление UI-created пользователей. Членство и revoke
нужно менять явно и проверять live; документация intent не равна enforcement.

## 4. Как выдать доступ к приложению

Проверить три вещи независимо:

1. **Admission в Authentik:** application binding допускает нужную группу/человека.
2. **Account linking:** exact subject соответствует ожидаемому application ID.
3. **Application authorization:** нужный проект/роль, без лишних global privileges.

Для foundation apps список намерений — `services.json` / `groups`; для Argo CD
отдельный `argocd_oidc` controller; для app-specific ролей — собственный mapping.
Поле `groups` в account mapping описывает bootstrap intent, не все текущие grants.

Пример: чтобы дать read-only доступ к Grafana, нужен approved observer admission
и фактический Viewer на Grafana API. Для доступа к Harbor нужны ещё reviewed
project membership/permissions. Для namespace Kubernetes нужен ограниченный
Rancher/RoleBinding, а не перенос owner kubeconfig. Для LiteLLM сейчас admission
только owner: не добавлять observer group без отдельного review free-SSO limits,
ролей, финансовых/ключевых API и existing-user linking.

После изменения проверить чистый вход и server-side права. Негативная проверка
обязательна: non-owner не может стать admin, читать чужие данные или получить
полномочия только через редактирование email/name.

### Ловушка: удаление из каталога не является отзывом

`configure.py` **добавляет отсутствующие application bindings**, но автоматически
не удаляет старые лишние bindings. Удаление имени группы из `services.json` само
не отзывает уже созданный binding. Нужно явно удалить/disable лишнее live binding
после review и проверить отсутствие альтернативного разрешающего пути.

Повторный apply может вернуть удалённый binding, если он остался в source. Поэтому
менять и source intent, и live enforcement. Argo CD controller отдельно останавливается
при неожиданных application group bindings; это другой режим, не универсальный revoke.

## 5. MFA и потерянное устройство

Native validation stage `default-authentication-mfa-validation` настроен на
`not_configured_action: configure`, а не skip. Разрешены TOTP/WebAuthn/static
classes; штатный configuration stage — TOTP setup. Это не означает, что у каждого
человека уже зарегистрированы все типы факторов или recovery codes.

Если код не принимается: проверить часы устройства и сервера, правильную запись,
текущий период кода и реальный stage. Не уменьшать MFA policy/не включать skip
как универсальное исправление. Для тестов — отдельная fixture identity.

Потеря owner device — recovery incident: подтвердить личность вне потерянного
канала, использовать независимый break-glass/backup codes, отозвать потерянный
фактор и связанные sessions в согласованном порядке. Факт возможности admin API
не является разрешением молча сбросить owner MFA. Рабочий пароль не заменять
значением из старого `owner-login.json`: initial file может быть давно неактуален.

## 6. Отключение человека / offboarding

План действий, не обещание мгновенного global logout:

1. Удалить его из desired grants/mappings там, где source иначе вернёт доступ.
2. Disable user в Authentik, отозвать действующие IdP sessions, grants/refresh tokens
   средствами установленной версии; проверить, что новый authorize не проходит.
3. Отозвать **отдельно** sessions каждого приложения, personal/API tokens,
   virtual keys, project membership и legacy local access. Проверить старую cookie.
4. Не полагаться только на исчезнувшую плитку или закрытый браузер. JWT могут
   оставаться годны до expiry; приложения не обязательно ходят в IdP на каждый запрос.
5. При наличии Linux/VPN: удалить ключи/peer grants декларативно по нужным хостам,
   проверить effective sudo/groups и уже существующие подключения. Удаление ключа
   само не завершает процесс/SSH-session; отключение owner/root — отдельный incident plan.
6. Не отозвать вместе с человеком общие production machine keys без оценки
   зависимостей. Перевести ownership/rotations под контролем и проверить consumers.
7. Сохранить необходимый аудит без credentials; проверить negative cases в новых
   и старых сессиях. Не удалять пользовательские данные без отдельного решения.

Для Wiki старые non-owner local sessions и local passwords уже отсекаются сервером.
Для остальных приложений нельзя автоматически заявить такой же уровень закрытия
fallback/old sessions: это часть оставшегося cluster-wide lifecycle inventory.

## 7. SSH и доступ администратора к операциям

Для нового личного Linux-аккаунта без sudo достаточно
[ручного `ssh-user.yml`: username + публичный `.pub`](ssh-user.md).
Authentik/n8n для этого не нужны; NetBird, роли приложений и Kubernetes выдаются
отдельно. Старый `users.yml` ниже остаётся exact-key inventory management.

Отдельный [host-access runbook](identity-host-access.md) описывает точные assignments,
key replacement, disabled state, sudo verification и отзыв на прежних хостах.

С owner Mac, с существующим проверенным SSH identity:

```sh
ssh -o Hostname=109.173.40.247 \
  -o 'HostKeyAlias=[socrat.alchemmist.xyz]:2222' socrat-0
```

Kubernetes команды на ноде выполнять с явным kubeconfig:

```sh
K3S_CONFIG_FILE=/dev/null kubectl \
  --kubeconfig /etc/rancher/k3s/k3s.yaml -n identity get pods,pvc
```

Не отключать host key checking. Не копировать admin kubeconfig в чужой home.
Права sudo для Ansible запрашивать безопасно, не сохранять пароли в inventory.
Привилегированная проверка Tim keys/PAM/sudo прошла на четырёх нодах, но реальный
вход с его private key должен проверить он сам — private keys не запрашивать.

Read-only inventory: `scripts/identity-audit.py --output <PRIVATE_NEW_FILE>`.
Он не читает shadow, private keys, tokens или Secret bodies, но содержит usernames,
key fingerprints и RBAC topology: результат всё равно private, не автопубликация.

## 8. Применение конфигурации

Из `ansible/`, с текущим inventory и проверенным owner SSH:

```sh
# Foundation — реальные изменения IdP/ingress, НЕ dry-run и НЕ только CSS.
ansible-playbook playbooks/authentik.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"'

# Только явно выбранная интеграция; пустой список по умолчанию ничего не мигрирует.
ansible-playbook playbooks/identity-integrations.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e '{"identity_oidc_services":["litellm"]}'
```

Поддерживаемые dedicated integrations смотреть в `integrate.py` и роли, не
выдумывать service name. n8n gateway относится к foundation manifests, Argo CD —
к отдельному `argocd.yml`. Wiki Secret сам по себе не добавит OIDC в старый image:
нужен соответствующий immutable runtime/chart.

`authentik.yml` импортирует `vpn-edge.yml` для namespace watch/RBAC; это не
безобидная операция UI-темы. Перед запуском пересмотреть весь imported play graph.
Для изменения только внешнего вида использовать отдельный branding playbook.

## 9. Что проверять после любой выдачи прав

- Доверенный HTTPS, правильный hostname/issuer/callback, без `verify=False`.
- Личная password+MFA цепочка; positive и negative admission.
- Server-side profile/ID/role, не только надпись/скрин dashboard.
- Старые данные на прежнем app ID, без пустого дубля профиля.
- Owner recovery остаётся доступным и проверяется самим владельцем отдельно.
- Machine API с действующим scoped key работает; без key — 401/403, не login HTML.
- Webhook/API/public status не попали за интерактивный redirect.
- Никаких fixture users, MFA devices, app keys и временных bindings после smoke.
- Source, runtime Secret references и post-upgrade reconcile согласованы.

## Сетевые изменения 6 ноября

[Сводный итог](network-access.md) и [NetBird](netbird.md) заменяют старую обязательную device-approval процедуру: сейчас approval flags выключены, admission остаётся personal MFA/JWT group-restricted. Новый человек не получает Linux/sudo/app роли автоматически. Не возвращать Mac resolver files, internal TV profile или отдельный TV домен при onboarding. Native Grafana anonymous org access выключен; public traffic-light share — отдельное явно согласованное исключение.
