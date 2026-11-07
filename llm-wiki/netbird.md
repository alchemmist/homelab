# NetBird: доступ людей к кластеру

Актуализация: **7 ноября 2026**. Общий сетевой итог и ограничения: [network-access.md](network-access.md). Это текущая схема, а не первоначальный pilot.
Старые записи «NetBird отложен / не внедрять» описывают уже завершённый этап.

## Что он делает и чего не делает

NetBird — управляемый сетевой вход для людей: личный Authentik/MFA и адресные политики доступа. Автоматическое требование user/device approval сейчас выключено; принадлежность устройства всё равно проверяется оператором. Панель: https://netbird.socrat.alchemmist.xyz/.
Он заменяет ручную раздачу **человеческих VPN-профилей**, но не межнодовый
`wg-socrat`, Linux SSH-аутентификацию, sudo, Kubernetes RBAC или роли приложений.
Сетевой доступ к узлу не означает право войти на него или стать root.

**Standalone WireGuard оставлен только независимым recovery, не human default:** холодный запуск клиента
без management действительно провалился. Успешные тесты существующего соединения
не означают полноценную HA или возможность удалить независимый recovery path.

## Как добавить нового админа

Это несколько независимых разрешений, не одна всесильная группа.

1. **Личность.** Создать личного активного человека в Authentik, настроить MFA и
   согласованные application/group bindings. Сохранить неизменяемый UUID; не
   клонировать owner, не использовать service account и не переиспользовать чужую
   учётную запись. **Созданная запись без пароля не может начать обычный вход.**
   Сначала выбрать штатную установку пароля; не обещать автоматическое приглашение
   или первый self-set экран. Текущий `antropophag` пока без пароля/MFA.
   [Первый вход и статус](identity-current-state.md),
   [создание человека](identity-operations.md).
2. **Устройство.** Человек устанавливает NetBird и входит своим Authentik/MFA в
   нашу management-систему. Администратор проверяет принадлежность устройства и
   согласованные identity/device policies; ручной approval не является текущим обязательным шагом. Setup keys для регистрации людей не используем.
3. **Сетевые права.** После отдельного согласования включить человека в настоящий
   Authentik/JWT-источник группы `netbird-internal-admins`. Сейчас он **owner-only**;
   Tim не получает admin автоматически. В NetBird это должна оставаться genuine
   `issued: jwt` группа, не вручную созданный API-аналог с тем же названием.
   Для обновления OIDC-сессии/групп используется `netbird login --extend`, не
   несуществующий `netbird up --force-reauth`. Проверить результат синхронизации,
   membership и реальные политики; имя группы само по себе ничего не доказывает.
4. **Linux/SSH.** Передать Linux-имя и публичный `.pub` в
   [ручной Ansible playbook](ssh-user.md). Он создаёт обычного пользователя **без
   sudo**, проверяет каждую выбранную ноду и добавляет недостающий ключ, сохраняя
   другие. Никаких Authentik attributes или n8n workflow для этого не нужно.
5. **Kubernetes и приложения.** Отдельно назначить нужные Rancher/Kubernetes/app
   роли. Не раздавать общий owner kubeconfig, private SSH key или root-пароль.
   Административная роль Kubernetes не требует членства Linux-пользователя в sudo.
   NetBird account admin/owner — тоже отдельное право управления самой панелью,
   оно не требуется просто для разрешённого сетевого доступа.
6. **Приёмка человеком.** С его устройства проверить MFA, identity/device policies, соединение,
   доступ только к согласованным адресам, SSH под его Linux-именем и нужные app/
   Kubernetes операции. Отдельно проверить запрещённые направления и отсутствие
   sudo. Успех owner Mac не является приёмкой другого человека или устройства.

## Текущая топология

На последней выполненной проверке: **пять подключённых peers** — Mac владельца
и четыре persistent machine agents на существующих нодах. Это срез приёмки,
не обещание их непрерывной доступности.

| Нода | Межнодовый WG / административный ресурс | NetBird agent IP |
| --- | --- | --- |
| socrat-0 | 10.250.0.1/32 | 100.100.155.241 |
| socrat-1 | 10.250.0.3/32 | 100.100.160.32 |
| socrat-2 | 10.250.0.2/32 | 100.100.166.186 |
| socrat-3 | 10.250.0.5/32 | 100.100.7.160 |

- Management/Signal: `netbird-pilot/server` на socrat-0, версия 0.82.0.
- Четыре агента: `netbird-host-peers/machine-socrat-N`, persistent PVC, без setup
  key в постоянном окружении. Client routes/DNS/NetBird SSH отключены; обычный
  SSH сервера и проверка host key сохраняются.
- Network `wireguard-internal`, один native `peer_groups` router на точную API-
  группу `netbird-node-agents`, metric 80, masquerade. Четыре отдельных WG `/32`,
  не общий префикс и не пересекающиеся дубликаты маршрутов.
- Семь политик: четыре admin resource FORWARD, admin own-node INPUT и две
  ограниченные pilot SSH-политики. INPUT нужен для самого routing peer,
  FORWARD — для адреса за другим peer. Нет All-device grants или fake JWT groups.
- Два отдельных аутентифицированных relay: home на socrat-0 и VPS на socrat-2;
  STUN-only coturn на socrat-2 UDP3478. TURN не включён, новых VM не покупали.
- Dashboard 2.96.0, management/client/relay и остальные образы закреплены digest.
  Authentik и management/Signal остаются singleton-зависимостями.

## Деплой: только Argo CD

**`root → netbird`**, встроенный проект `default`, ветка `main`:

- Application: `deploy/argocd/apps/netbird.yaml`;
- chart: `charts/netbird`, values: `deploy/netbird/values.yaml`;
- auto-sync, `selfHeal: true`, `prune: false`, Helm `parameters: []`;
- 33 ресурса при миграции, включая 10 Deployment: management/dashboard, edge,
  relay, STUN и machine agents. PVC и собственные namespaces имеют
  `Prune=false,Delete=false`; общий namespace `identity` не захватываем;
- Secret values, private keys и содержимое PVC **не в Git**. Существующие runtime/
  relay Secrets остаются private bootstrap dependencies, TLS выдаёт cert-manager.

Root сам создал Application из каталога apps. Проверено **Synced/Healthy** и
tracking всех ресурсов. UID объектов/PVC/namespaces, секреты и граф доступа
сохранились; из-за нормализации ссылки на тот же digest пересоздался только UI
pod, не management/agents/relays. Исторические direct-apply скрипты не являются
путём деплоя. Не создавать Application руками и не лечить drift ручным Helm.
Подробнее: [контракт](cluster-deploy.md), [adoption](../docs/netbird-argocd.md).

## Как добавляется новая нода

1. Явно добавить доверенный host и уникальный серверный WG-адрес в inventory.
   Не брать адрес человеческого устройства; существующий WG mesh нужен отдельно.
2. В корне repo выполнить `python3 scripts/netbird-gitops-nodes.py` и закоммитить/
   опубликовать inventory вместе с обновлённым `deploy/netbird/values.yaml`.
   Генератор только готовит Git, не деплоит в кластер. Проверка: `--check`.
3. Root/Argo CD создаёт Deployment/PVC. Присоединить узел к Kubernetes обычным
   baseline/worker/HA playbook. Не-Ready узел откладывается, не считается enrolled.
4. Обычный Ansible onboarding устанавливает host-side controller и работает с
   NetBird API: свежий Argo-owned агент получает одноразовый 600s ключ без групп
   через exec stdin, ключ отзывается, проверяется сохранение peer identity после
   key-free operational restart. Deployment/PVC создаёт **только Argo CD**.
5. После проверок WG/UID/key/peer добавляется точный machine peer, `/32` ресурс
   и admin policy. Уже разрешённому Mac не нужен новый VPN-профиль.

Missing workloads: `awaiting-argocd-workloads`; missing/non-Ready node:
`deferred-node-not-ready`. Не обходить отказ переизданием peer/PVC. Контроллер
не восстанавливает намеренно удалённые grants. Состояние root-only в
`/var/lib/homelab-netbird-nodes/`, machine PAT обслуживает отдельный daily timer.
Эта API-учётная запись имеет **широкие admin-права, не least privilege**.
Реальная пятая нода и expiry-boundary rotation PAT ещё не проверены физически.
Полный порядок: [node onboarding](../docs/netbird-node-onboarding.md).

## Исправленные проблемы, которые нельзя вернуть

- Native Signal требует h2c и отдельного Service `netbird-edge-forwarder-grpc`;
  HTTP/1 fallback не подходит. Проверены настоящие bidi stream headers через оба
  публичных входа, не только обычный HTTP health.
- В 0.82 external relay addresses отключают combined relay. Верхнеуровневый
  `relay:` игнорируется; два standalone relay — реальный текущий деплой.
- Relay health проверяет публичный TLS endpoint. Для выделенного Service нужны
  **оба** `publishNotReadyAddresses` и Traefik `service.nativelb: 'true'`, иначе
  получается readiness-цикл. TLS/HMAC/health не отключали.
- SSH host-key mismatch нельзя лечить удалением корректного known_hosts.
  Публичный DNS указывает на разные серверы: использовать проверенный SSH alias
  и точный endpoint/HostKeyAlias; connection-only `netbird-controller` закреплён
  за доверенным home IP, не входит в группу нод `Socrat`.
- **Исторические Mac resolver exceptions сняты 6 ноября**, включая restorer lifecycle. Сейчас используется обычный public DNS, DNS NetBird выключен. Не запускать старый `netbird-macos-bootstrap-dns.py` для нормального onboarding; guarded retirement — `scripts/macos-public-dns-cleanup.py`.
- 403 на странице Users был вызван общим edge-deny `/api/users/invites`.
  Разрешено **только точное GET чтение** с native auth/role checks; локальные
  создание/принятие приглашений, setup и local login/signup по-прежнему закрыты.
  Проверено admin 200 / anonymous 401 на обоих входах.
  [Диагностика](../docs/identity/netbird-users-invites-403.md).

## Что действительно испытано и где границы

| Отказ NetBird-сервисов | Результат |
| --- | --- |
| Агент socrat-0 + management/Signal остановлены | Новые SSH к 1/2/3 прошли, выбрался другой routing peer |
| Остался только агент socrat-2, management остановлен | Новые SSH к VPS прошли с существующего авторизованного Mac |
| Агент/VPS relay/STUN на socrat-2 остановлены, Mac down/up | Home relay доступен; сначала SSH не работал, к третьему раунду восстановился. Немедленная доступность **не доказана**, численного RTO нет |
| Management/Signal остановлен, затем Mac down/up | **Неуспех:** timeout, LoginFailed, SSH не работает; после восстановления management доступ вернулся |

Все остановленные сервисы восстановлены. Проверены SSH по WG и NetBird адресам
четырёх нод, оба relay и Signal. Это **bounded service-outage tests**, не физическое
отключение нод, питания площадки или WAN. Cached Signal-connected флаг сам по себе
не доказательство доступности сервера. Полные доказательства/тайминги:
[independent access](../docs/netbird-independent-access.md).

Не закрыты: physical/site outage, full DR, отдельный nonadmin/Tim-device тест,
сроки отзыва сессий/устройств, management/Authentik HA и cold-start resilience.
Проверенные зашифрованные backups не равны успешному полному восстановлению.
Ранее раскрытый legacy WG private key скомпрометирован; не повторять/использовать.
Перед ротацией подтвердить владельца профиля `.7` (inventory: Tim phone, owner
Mac `.4`); автоматического отзыва не делали, независимый recovery не удаляем.

## Отзыв доступа — отдельная операция

Отозвать согласованные IdP/JWT группы и app/Kubernetes роли, удалить/заблокировать
нужные NetBird devices/доступы и отдельно отозвать SSH-ключи на всех нужных нодах.
Выключение Authentik user не стирает `authorized_keys`, а добавляющий
`ssh-user.yml` ничего не отзывает. Применять reviewed exact-key/disabled путь
[host access](identity-host-access.md#4-отзыв-ssh); уже открытые SSH sessions и
forwards требуют отдельного решения. Пока нет отдельной приёмки, не обещать
мгновенный отзыв по одному изменению группы или истечению пятиминутного bearer.

## Операционный итог 6 ноября

- NetBird — основной транспорт Mac; recovery WG проверен через новый VPS `109.120.141.97` и оставлен выключенным. Tunnelblick не выключался/не перенастраивался. Все ordinary SSH — internal `/32`/2222, pinned host keys, без public fallback.
- Mac: `disableDns=true`, `disableClientRoutes=false`, `disableServerRoutes=true`, выбраны только четыре `wg-socrat-*` routes. Builtin All не раздаёт DNS будущим peers. No exit/LAN/pod/service/corporate route capture.
- `scripts/netbird-access.py` / `ansible/playbooks/netbird-access.yml`: audit-first scoped grant/revoke/offboard, owner/service protections, private snapshots и fresh exact hash. Временный lifecycle проверен; bootstrap admin ограничен, fixtures удалены. Membership не даёт автоматически app/Linux/Kubernetes/admin роли и не отзывает все старые sessions.
- Approval mode выключен, но genuine JWT group admission и личная MFA сохранены. Первый реальный новый человек/device остаётся отдельной приёмкой.
- Межнодовый WG не удалён. Отозваны только obsolete assistant `.6` и явно согласованный TV `.8`; owner recovery `.4` сохранён. Phone `.7`/скомпрометированный key — отдельное решение.
- После исправления overlapping transport marks на flannel ingress NetworkPolicy проверена cross-node ordinary/forged probes. Не возвращать старый bypass и не менять NetBird marking глобально: [overlay guard](../docs/k3s-networkpolicy-overlay-marks.md).
