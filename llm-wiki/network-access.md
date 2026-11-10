# Сеть и доступ: актуальный VPN-срез 9 ноября 2026

## Текущий транспорт — 10 ноября 2026 (supersedes прежний отдельный WG)

Пользовательский relay Москвы теперь **Pod `vpn-transit` на socrat-4** под Argo;
при реальном отказе — независимый fenced systemd fallback. Оба используют тот же
Xray и конфиг. Общий `wg-socrat`:Москва10.250.0.40→NL10.250.0.2; отдельный
`wg-vpn-transit` остановлен/disabled на обеих нодах, ключи/конфиги архивированы.
Management51832UDP/51840TCP остаётся отдельным systemd-relay, независимо от Pod.
DNS:.40:53→.2:5354, старый dnsmasq.2:53 не трогали. Только machine.40 исключён из
старого private-web443 DNAT; human/admin ACL не расширены. Trojan допускает
только mesh.40/32 и точный health-loopback127.0.0.1/32.

Реальный timer автоматически восстановил native relay после остановки только
московского worker-agent и его relay-контейнера; затем штатный failback вернул Pod.
Все пять HOME профилей приняты в Pod/native/fallback и **после удаления отдельного
WG**;17 клиентов/91 bindings/подписки84URI/77JSON/ключи сохранены, fixture cleanup
подтверждён. Кластер:3 healthy voters/hashKV equal revision17514049,5Ready/noMemoryPressure.
134 tests+14 subtests, новые private archives2/4 off-host SHA verified.
Это не zero-downtime rollout: исправлены TIME_WAIT guard, management source IP и
Pod bind-capability; не скрывать ошибки/короткую недоступность, не приписывать
результаты native-fallback probe первому неудачному Pod. [Подробности и операции](../docs/vpn-mesh-runtime-20261110.md).
API loss при работающем relay не вызывает переключения; native sticky до явного
failback. Mobile/AWG/полный DR/reboot/HA не доказаны. Подписка/публичный вход прежние,
Mac/Tunnelblick/default routes не менялись. Подготовительные apply не переигрывать.


## Актуально: production VPN через Москву, 9 ноября 2026

**Клиенты/HOME → Москва91.189.82.238 → NL109.120.141.60**. URL подписки
`vpn.alchemmist.xyz` неизменен; обновлять существующую подписку, не аккаунт/ключи.
Все три DNS-writer публикуют статический VPN A Москвы без NL fail-open. Нативные
Hosts7/7 обновлены:17 identities/91 bindings сохранены,32063 disabled. Подписки всех
17 клиентов:84 URI/77 JSON, обычный DNS/валидный TLS, старого NL endpoint нет.
После восстановления проверены из HOME три VLESS/REALITY, Trojan и WG:200/65536B/
контрольный hash, отдельный HTTPS exit-check=NL. UDP32…8192B через реальный
зашифрованный межсерверный канал также проверен; это не authenticated AWG/mobile.

HOME0/3 management WG и HOME1 pinned-TLS/GOST идут через Москву; известные NL
DNS/HTTPS/VPN потоки на HOME0/1/3 перенаправляются scoped persistent nft DNAT.
Не глобальный exit node, Mac/default routes/DNS-настройки не менялись. Private
DNS:Москва10.250.0.40:53→NL10.251.4.2:53. NS1 HOME и NS2/glue NL сохранены.
NL WAN raw VPN закрыт; только Trojan HTTP-путь на shared443 допускает московский
private10.251.4.1/32 и точный loopback127.0.0.1/32 для штатной health-проверки.
Public403/private101, spoofedXFF не помогает; портал200/LMS303/Argo200 сохранены.
Такой же gate установлен/проверен в native Caddy fallback.

**Инцидент не скрывать:** первоначальный ACL пропустил local health и вызвал
watchdog fallback/остановку NL K3s. Исправлено loopback-исключением, проверки и
watchdog не отключены. Штатный failback исходного member без reset/replacement;
160MB Raft catch-up занял3m45s, bounded start timeout180→600s. После восстановления:
3 healthy voters/common leader/hashKV equal (revision17449598),5Ready/noMemoryPressure,
все пять транспортов и17 подписок повторно приняты, watchdog healthy/fallback off.
Московский socrat-4 — agent-only10.250.0.40, bootstrap NoSchedule сохранён,
не control-plane/etcd/обычный heavy worker. Четыре human admin routes не расширялись.

Бэкапы пяти нод плюс post-recovery supplement — private/off-host/SHA verified;
история/старые recovery receipts сохранены.126 tests+14 subtests passed — срез приёмки,
не непрерывный healthcheck. Mobile/Happ interactive, authenticated AWG, полный DR/
chaos/reboot и сохранение end-user IP enforcement не доказаны. Не обещать HA/TSPU immunity.
Подробности и custody: [production runbook](../docs/vpn-production-cutover-20261109.md).
Исторический staging: [Moscow bootstrap](../docs/moscow-vpn-transit-20261109.md).
Не переисполнять migration/prepare/apply: fresh preimage/CAS, uncertain→разбор.

## Историческая приёмка human ingress, 7 ноября

# Сеть и доступ Socrat: текущий контракт на 7 ноября 2026

## Текущая граница — 7 ноября, снятие внешних auth gates

Удалены11 obsolete Authentik Applications (включая старую Kuma bookmark-карточку)
и10 Proxy Providers; outpost assignments сняты.10 native OIDC Applications,
их UUID/client credentials/callbacks/policy bindings сохранены. n8n,3x-ui, Kuma
и Syncthing используют собственный login; SearXNG и опубликованные SPI artifacts
публичны без Authentik и NetBird. Reader допускает только GET/HEAD, проверяет
manifest/hash и выдаёт безопасные типы inline. [Контракт и границы](../docs/identity/native-browser-auth.md).

Повторная приёмка после восстановления socrat-2: **82/82** публичных проверок
на HOME и VPS, обычная проверка TLS без отключения верификации. Все4 ноды Ready;
socrat-2 Ready с17:55:34UTC7 ноября. Все8 затронутых Argo apps Synced/Healthy.
Старые xui gateway Application/Deployment/Service/ConfigMap и Pod отсутствуют;
force-delete не потребовался.10 native OIDC регистраций/providers/bindings и
сохранённые поля иконок не изменились; Proxy Providers0. Опубликованный artifact
проверен через оба входа: anonymous GET/HEAD/206, manifest/SHA-256, inline,
PUT/POST/PATCH/DELETE405. [Приёмка](../docs/identity/native-browser-auth.md#recovered-vps-final-acceptance).
Это протокольная приёмка, не новая проверка входа от имени каждого человека.


Это актуальный итог сетевых изменений, а не инструкция повторить миграцию. Он заменяет старые утверждения «Grafana только через WG», «anonymous Viewer сохранён», «на Mac нужны resolver overrides», «ТВ подключает внутренний WG» и «Kuma ещё ждёт разделения входов». Transport/negative-case приёмки относятся к5–6 ноября;7 ноября обновлены
документация и карта владельцев, не повторён полный VPN/внешний browser тест.
Старые приёмки остаются историей; перед новым применением нужен свежий аудит.

**Внутренняя сеть для пользователя — NetBird**, не ручной socrat-wg профиль.
Имена `wg-socrat-*` routes и `wireguard-internal` resource — реальные оставшиеся
идентификаторы; не переименовывать их автоматически. Межнодовый WG и независимый
аварийный WG ниже сохранены намеренно. Текущие логины/первый вход:
[identity-current-state.md](identity-current-state.md).

## 1. Адреса, транспорт и неприкосновенные границы

| Назначение | Текущее состояние |
|---|---|
| Домашний публичный вход | `109.173.40.247` |
| VPS socrat-2 / второй публичный вход | **`109.120.141.60`** |
| Старый VPS IPv4 | `176.98.185.59` — только история, не рабочий endpoint |
| Внутренние адреса нод 0 / 1 / 2 / 3 | `10.250.0.1` / `.3` / `.2` / `.5`, обычный SSH `2222` |
| Основной административный транспорт Mac | **NetBird**, только четыре согласованных `/32` |
| Независимое восстановление Mac | Standalone WireGuard, обычно выключен; owner client `.4` |
| Обязательный рабочий VPN Mac | Tunnelblick, не выключать и не перенастраивать |

Межнодовый `wg-socrat` остаётся отдельной сетью Kubernetes/узлов: переход человеческого доступа на NetBird его не заменяет. Обычные SSH aliases закреплены за внутренними адресами и pinned host keys, без public fallback/ProxyJump. Не чинить SSH удалением known_hosts, ослаблением TLS/host-key checks или изменением корпоративных маршрутов.

Tunnelblick в приёмках сохранял тот же процесс (тогда PID 40769). Это историческое доказательство, не вечный PID для будущих команд: перед новыми действиями сверить актуальный процесс. Глобальный DNS, corporate resolvers/routes и VPN-профили Mac не менять; cache flush/HUP не использовать.

## 2. Миграция socrat-2

Новый IPv4 отражён в source/runtime, публичной зоне и REG.RU glue, WG recovery/TCP transport, ingress/probes, NetBird relay/STUN и webhook. Шлюз провайдера **`176.98.185.1` сохранён намеренно**: это не старый адрес VPS, массовая замена всего `176.98.185.*` недопустима.

В 3x-ui исправлены семь основных и семь legacy `hosts.address` строк с резервными копиями и whole-table invariants. Приёмка: 15 plain subscriptions / 79 links (74 новый VPS, 5 других, 0 старый VPS), 15 JSON subscriptions и authenticated Trojan TLS/WS. Содержимое подписок, SQLite, ключи и receipts не публиковать. Старые backups сохранены; неполный rootfs archive не объявлять полноценным backup.

STUN настроен на новый адрес, открытый TURN не включён. Webhook проверен на новом endpoint с пустой pending queue. Региональная недоступность старого VPS воспроизводилась отдельно; версия о TSPU не доказана.

Источники: [миграция VPS](../docs/vps-ip-migration-20261105.md), `scripts/vps-ip-migration.py`. Сверить актуальный CLI/runbook, не запускать по памяти. Применение миграционных действий: audit first, fresh exact hash, lock, private backup/receipts, остановка при uncertain write. Не перезапускать ноды/K3s/БД и не делать blanket firewall flush.

## 3. NetBird: основной доступ и отдельные права

На Mac DNS NetBird выключен: `disableDns=true`, `disableClientRoutes=false`, `disableServerRoutes=true`. Выбраны только четыре `wg-socrat-*` маршрута к адресам нод `/32`; нет exit route, захвата LAN, pod/service CIDR или корпоративной сети. Проверялись свежие SSH ко всем четырём нодам и фактический транспорт, а не только зелёный статус клиента.

Builtin All не раздаёт DNS, в том числе будущим peers. **Автоматическое требование user/device approval выключено**; личные Authentik/MFA и group-restricted admission сохранены. Это не All-device policy и не автоматическая выдача app/Linux/Kubernetes/admin-прав. OIDC/JWT mapping группы использует `profile`; существующий pilot сохранён.

Жизненный цикл: `scripts/netbird-access.py`, `ansible/playbooks/netbird-access.yml`, [onboarding](../docs/netbird-administrator-onboarding.md). Есть scoped grant/revoke/offboard, защита owner/service identities, свежий hash и private snapshots. Временные grant/revoke/no-op/deletion проверены; bootstrap admin ограничен, старый PAT не даёт прежнего admin-доступа. Не создавать вручную fake JWT-группу с тем же именем.

Допуск в приложение, NetBird policy, Linux SSH key, sudo и Rancher/Kubernetes/app role — независимые решения. Удаление группы не гарантирует мгновенное закрытие старых sessions/SSH forwards. Первый настоящий новый человек с собственным MFA/device enrollment остаётся отдельной приёмкой: временные fixtures её не заменяют.

Recovery WG проверен через новый VPS и все четыре ноды, включая worker `.5/32` и return path owner `.4`. После теста WG выключен, NetBird восстановлен. Устаревший assistant peer `.6` отозван; возможная косметическая запись в GUI не является действующим grant. Phone `.7` и ранее раскрытый phone key требуют отдельного решения о владельце/ротации, не отзываются попутно.

Подробнее: [NetBird](netbird.md), [совместимость с Tunnelblick](../docs/netbird-tunnelblick-coexistence.md), [границы отказоустойчивости](../docs/netbird-independent-access.md). Cold start без management раньше провалился; management/Authentik HA и full DR не доказаны. Не удалять независимый recovery.

## 4. Kubernetes: transport mark не даёт pod разрешение

Обнаружен cross-node NetworkPolicy bypass: NetBird mark `0x1bd22` пересекался с kube-router/CNI bits `0x10000`/`0x2000` и приводил к allow `0x20000`.

На всех нодах установлен строго owned nft guard `inet homelab_k3s_overlay_marks`, owner `homelab:k3s-overlay-marks:v1`: prerouting priority `-175` очищает ненулевой mark только на flannel/VXLAN ingress, когда **оба** адреса принадлежат pod CIDR `10.42.0.0/16`. Правила NetBird и прочий трафик не переписываются. Boot oneshot выполняется до K3s; остановка oneshot намеренно не удаляет guard.

Источник/процедура: `scripts/k3s-overlay-marks.py`, `ansible/playbooks/k3s-overlay-marks.yml`, [runbook](../docs/k3s-networkpolicy-overlay-marks.md). Whole-fleet preflight → serial atomic apply, private receipts, совместимость nft 1.0.6. NetBird/workloads не перезапускались.

16 обычных и 16 forged wrong-namespace gateway-label probes были заблокированы через разные ноды, PodIP/ClusterIP и порты 9000/9001; настоящий gateway читал согласованный fixture, console оставалась закрыта. Fixtures удалены. Это проверенная конкретная граница, не обещание универсальной защиты от любого root/cluster-admin. Повторять аудит после сетевых/node upgrades.

## 5. Обычный публичный HTTPS: доступ не равен роли

Публичный DNS не означает публичные backend ports. Публикуются выбранные human HTTPS entrances; БД, storage/telemetry APIs и внутренние protocol ports автоматически не открываются.

| Сервис | Итоговый контур |
|---|---|
| Grafana | Native OIDC auto-login, anonymous org access **выключен**; owner → GrafanaAdmin, `app-grafana-editor` → Editor, остальные admitted → Viewer |
| Светофор `socrat-traffic-light` | Только этот dashboard доступен native public sharing без входа на `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>` |
| Search | Публичный SearXNG, без Authentik/NetBird |
| `llm.socrat` / `litellm.socrat` | Прямые aliases к приложениям с native OIDC; machine entrances/credentials сохранены |
| Rancher | Native OIDC/roles; public local-password mutations блокируются, bearer/agents/WebSockets/private recovery сохранены |
| Grafana MCP | Отдельный bearer, read-only native identity; missing/invalid token 401, не интерактивный MFA gate |
| Wiki | Public read, native OIDC/роли для записи; `/mcp` защищён, поддельные WG/identity headers не дают обхода |
| Syncthing node0 `/sync/` | Штатный GUI login, заранее включённый до снятия пустой BasicAuth обвязки; prefix снимается; API key/devices сохранены |
| Syncthing node1 `/sync/` | Явный **410 gateway-only**, не другая Syncthing device и не фиктивный GUI |
| Kuma status | Anonymous `/status/socrat`, status/heartbeat APIs, assets/badges и native-token push сохранены |
| Kuma admin | `kuma.socrat.alchemmist.xyz`: только native Kuma login; публичный status-only фильтр сохранён |

Обычные app role groups `app-grafana-viewer`, `app-grafana-editor`, `syncthing-web-admins`, `uptime-kuma-web-admins` создавались пустыми; временные тестовые memberships удалены. Не предполагать выдачу этих прав новым людям и не добавлять их в owner group ради входа. Machine consumers должны сохранять свои исходные API entrances/tokens, а не переезжать на MFA alias без отдельной совместимости.

Grafana Viewer/Editor проверены личными временными password+TOTP fixtures: чтение, Editor folder create/delete, admin API denial обоим. Fixtures удалены; старый Grafana proxy gate снят после native acceptance. Public policy блокирует BasicAuth/`POST /login`, metrics/debug, сохраняя bearer API/WebSockets/private recovery. Grafana Deployment и shared Prometheus/Collector не перезапускались этим closeout.

Kuma public Socket.IO и неизвестные admin APIs закрыты; старые admin/login/settings/dashboard/manage-status-page URL перенаправляют на admin host. На admin host проверены WebSocket 101, Socket.IO namespace и denial native `getSettings` без native login. Нельзя просто закрыть весь общий socket и считать status/machine paths сохранёнными.

Syncthing BasicAuth bytes, process/device identity, keys, config и synchronization не менялись/не перезапускались. Реальный owner Basic login — отдельная опциональная приёмка; пароль не заимствовался и не сбрасывался.

Основные источники: `deploy/public-web/services.json`, `publicEntry` в локальных чартах и `deploy/platform/<app>/public-entry` в существующих Argo Applications, `scripts/public-web-access.py`, `ansible/playbooks/public-web-access.yml`, [публичные входы](../docs/public-web-migration.md). Audit/create-only, drift refusal, outpost preservation, private receipts. Authentik policy denial может быть HTML с HTTP 200: оценивать фактический denial, не требовать фиктивный transport 403.

### Владение public ingress после миграции 2026-11-07

Сборная Application **`public-web-entry` и её chart удалены**. Публичные входы,
policy proxies и их ConfigMap теперь принадлежат существующим Applications:
Grafana → **`grafana`** (после monitoring split), Rancher → `rancher`, Search → `searxng`,
LLM alias → `open-webui`, LiteLLM alias → `litellm`, MCP → `grafana-mcp`,
Syncthing → `syncthing`, Kuma admin → `uptime-kuma`.

Для локальных чартов менять `publicEntry` в values; для сторонних —
`deploy/platform/<app>/public-entry`, подключённый дополнительным source той же
Application. Authentik policies/группы остаются централизованными, native роли и
machine authentication не менялись. Не создавать общий ingress Application снова.

Все 22 ресурса переданы без пересоздания; TLS/проверки доступа сохранены.
После удаления старого owner public regression — **134/134**. Это не новый
browser-MFA/onboarding тест. Детальная карта, безопасная передача ownership и
граница LiteLLM hooks: [cluster-deploy.md](cluster-deploy.md#публичные-входы-принадлежат-приложениям--2026-11-07).
Ingress handoff был завершён в `e7fe891`; затем monitoring split `8862770`
передал Grafana собственному app. Не возвращать старого владельца. Текущие sources
и незавершённый aggregate cleanup: [observability-current.md](observability-current.md).

## 6. Kuma: восстановление после инцидента, не zero downtime

Application-only restart для закрытия старых sockets выявил несовпадение Secret и действующего SQL password; приложение было недоступно. Максимальный наблюдённый heartbeat gap активного HTTP monitor — **2072s, около 35 минут**. Историю не подделывали, backfill не делали.

Старый app password восстановить не удалось. Существующие SQL passwords не сбрасывали: создан отдельный `homelab_kuma_app` с точным schema-only grant `` `uptime\_kuma`.* `` (escaped underscore, не wildcard schema). Старый `uptime_kuma` account/grants сохранён. App Deployment использует новый username; DB Deployment username остаётся `uptime_kuma`. MariaDB Pod UID/restart count и fingerprint native Kuma account/auth сохранены.

Secret UID сохранён, **данные Secret при recovery изменились**; не повторять промежуточное утверждение об неизменных credential bytes. Random bootstrap Secret отключён, старое Argo tracking ownership точно снято/keep сохранён, bootstrap guard не позволяет спутать app/DB username. Не менять DB deployment username или регенерировать живой Secret для обхода guard.

Аудит: maintenance task `kuma-db-account-recovery` (без apply), `scripts/kuma-db-account-recovery.py`, [MariaDB runbook](../docs/uptime-kuma-mariadb.md). Private candidate/before/grants/uncertain/after receipts сохранены. При uncertain write остановиться; не менять defaults и не повторять recovery вслепую. Отдельная БД не перезапускалась.

## 7. Mac: старый owned DNS lifecycle снят полностью

Удалены 12 точно owned `/etc/resolver` файлов, wiki restorer script/plist/marker; выгружен только `system/xyz.alchemmist.wiki-resolver`. Перед удалением проверялись content/owner/mode/symlinks, private backup и fresh hash. Финальный audit: operations=0, resolver_files=0, daemon=false.

Глобальный DNS hash и прежний процесс Tunnelblick сохранены; никаких cache flush/HUP, global DNS/route/VPN mutations. Native system DNS для 12 affected/control hosts возвращал публичные HOME/VPS; ordinary DNS+TLS и чистый браузер доходили до MFA без overrides. Внутренний pinned SSH ко всем нодам/NetBird продолжил работать, recovery WG не использовался.

Источник: `scripts/macos-public-dns-cleanup.py`; backups/receipts в private `/var/db/homelab-public-dns-cleanup/`. Normal Wiki onboarding больше не ставит resolver: legacy task требует `wiki_editor_client_private_dns_legacy=true`. Default admin WG DNS mode — `none`. Server-side private DNS может оставаться для других согласованных consumers, это не повод восстанавливать Mac overrides.

## 8. Телевизор: только публичный Grafana, YouTube VPN отдельно

По окончательному решению пользователя `xiaomi-tv` удалён через WireGuard UI вместе с конфигурацией/ключом на ТВ. Его exact public peer `.8/32` отозван на трёх нодах, где существовал; worker уже не имел его. Все четыре final audits — operations=0. Inventory и оба helper APK больше не создают/не подключают внутренний профиль.

Остался **только `alchemmist-tv` для YouTube**, без чтения/замены его key/config. YouTube helper поднимает его по требованию и ждёт VALIDATED. Grafana helper отключает этот глобальный VPN и открывает Fully **без подключения туннеля**. Always-on VPN очищен; helper source и `tv-admin.yml` не возвращают его. Package/component/signing identity совместимы с существующими назначениями пульта.

URL Fully — canonical `grafana.socrat.alchemmist.xyz/public-dashboards/<accessToken>?kiosk=1&hideLogo=1&autofitpanels=true&socratTv=1`; точный адрес — root-private `/var/lib/homelab-grafana-tv-public/fully-url.json`. Временный **`tv.alchemmist.xyz` удалён** из authoritative A records и chart; его exact Ingress/Certificate/Secret удалены по UID, не blanket prune. DNS/alias final audits — operations=0; это исторический результат. Отдельный public-web-entry затем удалён; Grafana public ingress/proxy теперь принадлежат **grafana**; Helm release/service
имена с kube-prometheus-stack сохранены, это не старый Argo owner.

Серверный JS/CSS восстанавливает 5px inset, скрывает public header/footer и autofit compacted layout: native public scene игнорирует старые kiosk/autofit flags. Важно брать compacted geometry, не пересекающиеся raw gridPos. Сохранены Fully scale 55%, font 75%, empty injectJsCode (без Plus watermark), remote assignments/HDMI и Android Private DNS. Native share не меняет dashboard JSON, refresh 5s и live range now-12h.

Проверены реальный TV screenshot с живыми данными, YouTube foreground с **одной настоящей VALIDATED VPN network** и последующий Fully без VPN. `NOT_VPN` в Wi-Fi capabilities не считать активным VPN. Физический пульт/холодное включение повторно не проверялись.

Процедуры: [TV](android-tv.md), [операционный runbook](../docs/android-tv.md), `tv-public-dashboard.yml` (только URL), `retire-tv-internal-wireguard.yml`, maintenance `retire-tv-alias`, `grafana-tv-dns.yml` (теперь только retirement). Не удалять данные WireGuard app целиком: там сохранён YouTube-профиль. Private historical backups не уничтожать.

## 9. Что доказано и что ещё отдельно

- Final TV/canonical checks: **24/24** verified-TLS forced-routing checks двух IP; общая public-web regression **134/134**, ingress **30/30**, **66 focused tests**, четыре Ansible syntax checks. Это не полный repository suite.
- Public-web closeout до TV: **117 passed / 17 subtests**, реальные scoped MFA/native role tests; считать исторической отдельной выборкой, не суммировать тесты в одну выдуманную приёмку.
- Forced public routing, второй LAN device и чистый browser не заменяют независимый внешний Internet/provider/device test. Exhaustive every-app/every-role/machine API/WebSocket acceptance не выполнен.
- First real new-human NetBird enrollment, owner Syncthing Basic acceptance, independent DR/HA, длительная совместимость corporate VPN и phone-key decision — отдельно.
- CI `HOMELAB_DEPLOY_KEY` publickey failure, unrelated LMS/RustFS Argo drift и исторические adminclient test expectations — не повод для blanket sync/prune или ослабления защиты.

Закрывающие network/TV коммиты: `435c70b`, `448f93f` (с промежуточной реализацией TV alias и её последующим полным retirement). Последнее живое состояние важнее промежуточной идеи. Wiki-актуализация сама по себе ничего не разворачивает.


## VPS migration recovery — 2026-11-09, fresh acceptance

This supersedes the prior unreachable/ReadyUnknown observation, not its history.
Owner rebooted socrat-2; persistent NEW=109.120.141.60/24, gateway109.120.141.1.
All four nodes Ready; watchdog Kubernetes healthy=true; native fallback inactive.
Management uses owner-authorized direct NEW:2222 with pinned key and /usr/bin/ssh;
old controller wrapper is not private-only evidence and must not be reused blindly.
Do not further alter Mac WireGuard; corporate Tunnelblick/routes/DNS preserved.

Seven stale panel host addresses migrated via native API only, with uncertain-call
readback/reconciliation and no replay.16 identities/85 bindings, credentials,
quotas and disabled legacy32063 preserved; temporary admin tokens removed.
All16 URI subscriptions(78 entries) and JSON(72) match backend/public TLS pinned
NEW, zero OLD. Own temporary HOME-WAN identity authenticated REALITY and
TrojanTLS to literal NEW with HTTP200/65536 bytes each; no overlay/global proxy,
fixture removed. This is NOT mobile/operator acceptance or filtering attribution.

Source d8a5e54 merged normally with upstream SPI extraction and pushed as0642a36;
bot/netbird/traefik-edge/spi-triage naturally Synced/Healthy at that revision.
No blanket sync/prune. Bot runtime webhook env and Telegram destination NEW;
queue2 ->0, existing machine secret/URL/allowed updates retained, no duplicate
mailing command sent. Recipient-level mailing completion remains unproven.
REG.RU accepted ns2-only glue change; **both x.nic.xyz/y.nic.xyz now publish NEW**,
ns1=109.173.40.247 and both NS names unchanged; cached old glue can outlive this.
Public NEW UDP53 authoritative answer and STUN Binding verified.

Still separate: owner phone refresh/connectivity; mailing recipient confirmation;
RustFS manual-sync auth-egress /32 runtime (source changed, app still old revision);
Collector delivery, off-host DR and workstation NetBird LoginFailed. Public
backend eth0 TCP12096/32087 denials preserved (external refused;443 open), priority-6.
NetBird added one nb-host-only accept to that accept-policy chain: read-only proof
shows no public-rule change/no-op semantics; installed exact-table validator stops
on the extra rule, so do not blindly run ensure/rewrite the table. No firewall edits.
Runbook/evidence index: docs/vps-ip-migration-20261108.md. Focused166tests+21subtests.
