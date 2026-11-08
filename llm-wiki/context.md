# Socrat: текущий контекст

Актуализировано **8 ноября 2026** для завершённого observer rollout; остальные
срезы сохраняют свои даты. Это не новая полная live-проверка кластера.
Начинать с [карты справочника](README.md). Старые датированные журналы — evidence
своего этапа, не задания повторить миграцию и не замена текущим manifests/live state.

## Сеть и вход

**NetBird — основной пользовательский доступ во внутреннюю сеть Socrat.**
Не предлагать людям ручной профиль «socrat-wg» как обычный onboarding.

| Слой | Текущий контракт |
| --- | --- |
| NetBird | Личный Authentik/MFA, отдельно согласованные JWT-группы/device policies |
| Маршруты администратора | Только четыре адреса нод `/32`, не весь LAN/pod/service CIDR и не exit node |
| Ноды 0 / 1 / 2 / 3 | `10.250.0.1` / `.3` / `.2` / `.5`; SSH `2222`, pinned host keys |
| Межнодовая сеть | Реальный интерфейс `wg-socrat` сохранён: NetBird human ingress его не заменял |
| Recovery | Независимый standalone WireGuard владельца, обычно выключен; не обычный путь входа |
| Рабочий VPN Mac | Обязательный Tunnelblick; не отключать и не менять DNS/routes ради homelab |
| Public HTTPS | HOME `109.173.40.247`, VPS `109.120.141.97`; обычный DNS/TLS без Mac overrides |

У NetBird на Mac DNS выключен, выбраны только четыре согласованных маршрута.
Setup keys для людей не используются. Автоматический user/device approval выключен,
но принадлежность устройства и реальные разрешения проверяются. Cold start без
management ранее не прошёл: не обещать HA и не удалять recovery WG.

SSH transport, публичный ключ/Linux account, sudo, Kubernetes RBAC и app role —
**независимые разрешения**. Публичные HTTPS-входы не означают публичный SSH.
Не удалять known_hosts, не добавлять public fallback/ProxyJump и не отключать TLS.
Ключи/пароли/QR/подписки/activation URLs не публиковать.

Процедуры: [сеть](network-access.md), [NetBird и onboarding](netbird.md),
[SSH без sudo](ssh-user.md), [Linux/RBAC](identity-host-access.md),
[публичный DNS](public-dns.md).

## VPN: текущая работа по #83

С 8 ноября — только конфигурация существующего socrat-2, **без покупки VPS/IP**.
Свежий аудит и приватный WAL-aware backup выполнены. Установлены только ACCEPT
backend-счётчики, не блокировки. REALITY32053 исправлен штатным API: Yahoo→Yahoo;
прошли fallback TLS1.3/H2 и synthetic64KiB до/после. Временные machine credentials
и fixture удалены, прежние токены/users/settings сохранены. Plaintext32063 и raw
backends ещё не закрыты; у всех7 plaintext-связей уже есть encrypted alternative,
но device/subscription acceptance не доказана. `x-ui -getApiToken` ротирует токен,
не извлекает его; не запускать ради чтения. Не выключать старые клиентские профили и не обещать обход IP/ASN-ban.
[Актуальный scope, исследования, инструменты и gates](vpn-hardening.md).

## Личности и авторизация

Начать с [текущего состояния identity](identity-current-state.md), затем
[операций](identity-operations.md) и [карты интеграций](identity-integrations.md).

- Owner — `alchemmist`, единственный человек в `homelab-owner`.
- Tim: **логин `antropophag`**, новая native Authentik identity после согласованного
  пересоздания; UUID закреплён в account mappings. Display name Tim и Linux `tim`
  — не логин IdP. На read-only проверке пароль ещё не задан, MFA/первого входа нет.
  Create user не запускает автоматическую установку пароля. Старый отдельный
  activation flow удалён, ссылка отозвана; SMTP invitation/recovery не настроены.
- Native OIDC: Grafana, Harbor, Rancher, Open WebUI, Wiki, LiteLLM, отдельно Argo CD.
  Admission через IdP не выдаёт native admin. Роли и exact subject links проверять
  по источникам, не по email или похожему имени.
- n8n/3x-ui, Kuma admin/Syncthing — только штатный логин сервиса; внешние Authentik proxy gates удалены.
  не универсальный account SSO. Umami для Tim **приостановлен** до native OIDC (#85).
- **Observer принят 8 ноября:** Rancher, Grafana, Wiki, Argo CD. Danila добавлен в
  `homelab-observer`, ошибочная `authentik Read-only` снята, согласованный NetBird
  сохранён; пароль/MFA и персональные native app/RBAC записи не создавались.
  Обычному следующему человеку достаточно IdP-группы и native SSO/JIT. Имеющиеся
  owner/editor/direct grants аддитивны, observer их не понижает.
- Отзыв проверен на synthetic identity: старые cookie/действующий Rancher bearer,
  Wiki MCP и новый вход без группы; автоматический native cache remove/re-add.
  Worker не создаёт users/roles; его доступность контролируют Prometheus alerts.
  Не обещать мгновенный logout всех OAuth/JWT. **Harbor для observer закрыт**:
  нативный CLI-кеш не прошёл отзыв, follow-up #134. Не возвращать Guest grants
  по старому readiness receipt. [Границы и evidence](native-observer.md).
- Machine APIs, robots, MCP, agents, webhooks сохраняют отдельные credentials;
  их нельзя переводить на browser MFA redirects.
- Grafana anonymous org access выключен. Исключение — только явно shared
  `socrat-traffic-light`. Wiki read public, запись — native OIDC/роль, MCP — bearer.

## Деплой и источники

Постоянные изменения оформляются в Ansible/Helm/Git. Workloads — Argo CD,
`root → deploy/argocd/apps`, проект `default`. Fleet GitRepo/bundles retired;
наличие Rancher Fleet controllers не означает возврат к Fleet deployment.

Для подключённых приложений: build/test → immutable Harbor image →
`alchemmist/deploy-to-socrat@v1` → tag/digest в homelab main → Argo reconciliation
→ readiness и функциональная проверка. Push образа или коммит не равен deployment.
Уточнять состояние `automated.enabled`, hooks и конкретной Application; не делать
blanket sync/prune, `helm upgrade` или ручной image patch для обхода GitOps.

Публичный ingress/policy принадлежат **своему приложению**. Aggregate
`public-web-entry` удалён; его не восстанавливать. Grafana сейчас имеет Application
`grafana`, chart `charts/grafana` и `deploy/platform/grafana/public-entry`.
Не искать его текущего владельца в старом `kube-prometheus-stack` app.

Мониторинг разделён на `grafana`, `prometheus`, `alertmanager`, `prometheus-operator`,
`node-exporter`, `kube-state-metrics`, `loki`, `tempo`, `pyroscope`;
дашборды/rules/probes — отдельный `monitoring-k3s`. Handoff закрыт: старые
`kube-prometheus-stack`, `prometheus-stack`, `otel-backends`, `profiling` удалены без
каскадного удаления. Auto-sync включён у действующих владельцев. На закрытии
первого этапа сохранены 103 UID ресурсов; на окончательном разделении
Prometheus-компонентов повторно проверены все 77 ресурсов этого подмножества,
8 runtime Pods без перезапуска, 4 PVC и UID/содержимое 3 целевых Secrets.
Неиспользуемый общий ConfigMap удалён отдельно по UID. Не повторять retirement и не возвращать старые owners.
Итоговый checkpoint — `0bb4e31`; 104 профильных теста и 24 subtest, public regression
134/134. Это результаты закрытия миграции, не замена новой live-проверке.
Остаётся отдельная проблема WAL Prometheus; сбой digest блога исправлен
параллельным релизом `f485c74` (blog снова Synced/Healthy). Это **не** обещание
целостности WAL или здоровья всего кластера. Карта/приёмка и границы:
[деплой](cluster-deploy.md), [наблюдаемость](observability-current.md),
[первый closeout](../docs/monitoring-service-split.md),
[окончательное разделение Prometheus-компонентов](../docs/prometheus-service-split.md).

## Топология и данные

- K3s/etcd: голосуют ноды **0/2/3**, кворум два. Нода1 control-plane без голоса etcd.
- socrat-0: дом/RTX3090, vLLM/LLM, Authentik/PG, Wiki PVC, Kuma MariaDB и NFS.
  На проверке Prometheus pod также на socrat-0, не выводить placement из имени app.
- socrat-1: Grafana, Loki/Tempo/Pyroscope и часть приложений на проверке.
- socrat-2: VPS/3x-ui/edge; img-proxy закреплён именно здесь (`b3ad6e2`).
- socrat-3: внешняя control-plane/etcd нода и пользовательский desktop.
- Два публичных IP не реплицируют backend, GPU, SQLite/PVC или PostgreSQL.
  Singletons и retained PVC не являются HA/проверенным off-node DR.

Scheduler/placement сверять перед работой; старые offload-таблицы не текущая правда.
Resource budgets: `ansible/vars/container-resources.yml`, native admission policy;
requests не резервируют физическую память, сумма limits не доказывает N−1.

## Мониторинг, бот и телевизор

Collector — sole scraper; Prometheus принимает OTLP, Loki/Tempo работают в K8s.
Dashboard/rules/probes в `charts/monitoring-k3s`, datasource/provisioning Grafana —
в его текущем chart. English titles/descriptions; не скрывать telemetry gaps,
не превращать отсутствие данных в здоровый ноль. Чтение метрик — через read-only
Grafana MCP/API, браузер — для визуальной проверки.

SPI triage использует durable queue, read-only evidence и scoped GitHub App;
не получает права автоматически чинить инфраструктуру или закрывать инциденты.
[Бот](socrat-bot.md), [SPI](spi-incident-triage.md), [n8n](n8n-workflows.md).
Ручная эскалация20→10 не равна смене severity и не обещает SLA.

TV использует public traffic-light URL канонического Grafana, без внутреннего VPN.
Профиль `xiaomi-tv`/peer отозван; `alchemmist-tv` для YouTube сохранён отдельно.
Не стирать app data WireGuard. Fully55%/font75%, injectJsCode пуст; актуальный
TV layout в Git, старые panel coordinates не повторять. Физический пульт/cold boot
не считать повторно проверенными по одному screenshot: [TV](android-tv.md).

## Безопасный порядок работы

1. Fresh status/fetch и сверка владельца ресурса, версии, UID и реального placement.
2. Read-only аудит; явный scope, private backup, fresh preconditions/lock/CAS.
3. Декларативное изменение и профильные tests/render/syntax checks.
4. Только согласованное точечное применение; uncertain write → остановка/разбор,
   не слепой retry. Никаких глобальных firewall/DNS/VPN/K3s/DB рестартов попутно.
5. Отдельно доказать readiness, native права, negative cases и реальные user steps.

Не трогать посторонние worktree/Playwright profile. Не stash/reset/force-push.
Для Ansible единый `inventory/hosts.yml`, четыре ноды `Socrat`; для подмножества
явный `--limit`. App/browser MFA не даёт право взять owner kubeconfig.
Локальные `/tmp`-артефакты не постоянный deployment dependency.

Эта актуализация — документация с read-only аудитом, не повторная миграция,
не browser acceptance, не завершённый первый вход человека и не общий зелёный suite.


## MCP в репозитории

Agent entrypoint — `AGENTS.md`, settings — `.pi/mcp.json` (без секретов в Git).
Официальные подключения и полный audit/ограничения: [official-mcp.md](official-mcp.md).
n8n MCP после локального обновления токена проверен (`initialize`/`tools/list`)
и включён на Mac: поиск/чтение workflows, без execution. Токен только в private
файле0600, не в Git. В committed config n8n пока disabled; другие машины не
настроены автоматически. Umami остаётся опциональным и ждёт authorized analytics
key; не обходить это через reset/DB. Новых обязательных MCP на кластере не требуется.


VPN83 latest owner clarification: users will refresh subscriptions themselves.
Native32063 excludeFromSub=true applied, enabled=true retained for cached clients.
All16 URI+JSON subscriptions verified public/backend before/after: exactly7 plaintext
links removed (78 URI entries remain), unrelated profiles/keys/URLs preserved.
Server publication migration done, not device refresh/legacy retirement. No device
remote-control prerequisite for this phase; wait for owner refresh confirmation
before closing32063. Temporary tokens removed; see llm-wiki/vpn-hardening.md.


VPN83 latest: raw public eth0 TCP12096/32087 rejected by a dedicated persistent
exact-owned guard; external resets+TLS443 and all16 URI/JSON subscriptions verified.
Own Trojan64KiB before/after; no rule replay after nft1.0.6 readback correction.
Real socrat-0 HOME FIXED WAN now passes own REALITY32053+TrojanTLS44364KiB each;
expected home source, not overlay; routes/resolver unchanged, all probe credentials
cleaned, four nodes Ready.71 tests+6 subtests. Mobile/reboot not tested. Legacy32063
still excluded+enabled pending actual refresh confirmation; WATCHDOG CONFIG STILL
REQUIRES IT, so no blind API disable (would false-fail/fence). Coordinated watchdog
source/live config+monitoring update is required before retirement. See VPN wiki.


VPN83 latest supersedes previous retirement gate: OWNER APPROVED old-client
DISCONNECT.32063 now disabled+excluded, no listener/external TCP refused. Source/live
watchdog dependencies+collector updated under existing lock, timer resumed, recovery
healthy/not inhibited. All16 URI/JSON subscriptions preserved; users refresh SAME
URL/select encrypted profile, keys unchanged. Actual HOME WAN REALITY+Trojan64KiB
repeated after cutover, passed; no global network change, all temp keys/clients clean.
133 tests+8 subtests scoped. Server move complete, do not re-enable32063. Mobile,
reboot/DR and future-IP-ban immunity not claimed. See authoritative VPN wiki latest.


VPN active incident19:07–19:45UTC supersedes availability assumptions: owner says all
phone profiles now fail on mobile too. New literal-VPS TCP timed out home+workstation,
internal health/4nodes/auth fields intact. Independent GermanyTCP443 succeeded10ms:
regional/source filtering or routing suspected, not proven TSPU. vpn hostname DNS
currently HOME IP (TLSworks), not VPS; earlier Trojan hostname probe exact path was
not recorded, do not claim literalVPS443 from it. Paired header diagnosis unavailable
home tcpdump missing; no matched packet attribution. No repair/IP change performed.
Don't use HOME as VPN fallback without explicit risk consent or remove old IP before
safe parallel replacement. See VPN wiki/runbook incident section; future ban immunity
never established.
