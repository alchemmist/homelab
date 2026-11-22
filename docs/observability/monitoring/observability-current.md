# Наблюдаемость: источники и владельцы

[Отчёт: внезапная потеря `socrat-1`, 21 ноября 2026](../../records/incidents/socrat-1-loss-20261121.md): миграция на NFS, что вернулось во время потери и после неё, доставка алерта и Descheduler.

## Метрики: сбор, прореживание и перенос между нодами — 21 ноября 2026

| Поток | Вычисления → физический диск | Условие и результат |
|---|---|---|
| Сбор | OTel Collector → Prometheus на `socrat-0` | Единственный scraper, базовый интервал 5s; запись по OTLP в локальные WAL/TSDB. Retention 12h; не включать параллельный scrape тех же targets. |
| Закрытые raw-блоки | Sidecar на `0` → TLS S3 `thanos-workshop` на `socrat-1` | Обычно блок по 2h; журнал shipper отслеживает отправленные ULID. Основной Store на `1` читает S3. Это асинхронная отправка, не синхронная реплика WAL. |
| Компакция и downsampling | Основной Compactor и его рабочий каталог на `0` → тот же S3 на `1` | Компакция объединяет блоки одного разрешения; downsampling создаёт агрегаты raw → 5m → 1h по мере старения блоков (обычные пороги Thanos: 40h и 10d). Это не срок удаления и не обещание публикации точно в этот момент. |
| Часовой архив | `thanos-cascade` на `3` читает S3 на `1` → локальный 1h-архив на `3` | Каждый час в `:30`. Только готовые блоки 1h; staging, проверка хешей, атомарная публикация без перезаписи. Отдельная роль читает S3 и пишет только маркеры, без DeleteObject. У отдельного часового Compactor retention 17 520h (730 дней). |

**Политика рабочего архива:** raw ≥5 дней при читаемом покрытии 5m на `1`; 5m ≥90 дней при читаемом покрытии 1h на `3`; 1h на `3` — 730 дней. Возраст — от конца блока, не от выгрузки. Часовой источник освобождается без ожидания 90 дней после проверки файлов, метаданных, чтения через конкретный Store и защиты родительских 5m от повторного downsampling/compaction. Перенос = публикация → проверка → deletion mark; физическую очистку S3 делает Compactor после 48h. Параметры native retention в рабочем S3 остаются `0d` намеренно: срок без проверки покрытия не даёт права удалять. При пропуске интервала, несовпадении меток/источников, отсутствии ответа или дисковой тесноте срок не сокращается. Отдельный старый NFS-архив не входит в эту очистку.

Реализация: [публикация и квитанции](../../../charts/thanos/files/hour_copy.py), [условия и маркеры](../../../charts/thanos/files/tier.py), [тесты](../../../tests/test_thanos_tiers.py). Для остановки новых маркеров задать `APPLY_TIER_MARKS=false` в шаблоне CronJob; это **не отменит** уже созданные маркеры. После загрузки Store или компакции может понадобиться следующий проход. Ищите `mark deletion <ULID>` и проверяйте оставшийся блок, не считайте успешный пустой Job подтверждённым удалением.

**Проверка по участкам.** Для свежего графика сравнить прямой Prometheus, Sidecar и Thanos Query с одинаковыми параметрами (см. ниже). Для отправки на `1` проверять новый ULID в журнале и объект в S3: это подтверждено штатным блоком `01M7ZQNKDF9JW6PX0TH142HGHX`. Для переноса на `3` проверять число подтверждённых часовых блоков в логе `thanos-cascade`, а не только статус Job: `hourly blocks confirmed 0` означает успешный запуск без переноса. Часовой архив не заменяет резервную копию raw.

**Итог разовой миграции.** Старый `/var/lib/socrat-thanos` на `0` пуст; освобождено 49,58 GiB. На `3` отдельно от читаемой часовой истории лежит проверенная сжатая копия 148 исходных файлов (13,43 GiB); временная копия на `0` удалена. Это снимок до переключения, не backup последующих записей. [Проверка восстановления и путь к архиву](../../../deploy/storage/thanos-retire/README.md).

Источники: [Prometheus](../../../charts/prometheus/values.yaml), [размещение и retention Thanos](../../../charts/thanos/values.yaml), [расписание и права каскада](../../../charts/thanos/templates/warm-cascade.yaml), [проверка часовых блоков](../../../charts/thanos/files/hour_copy.py).

## Пропуски свежих метрик в Thanos — 19 ноября 2026

**Правило чтения:** последние 6 часов обслуживает живой sidecar Prometheus. Только у raw Store Gateway (`thanos-store`) задан `--max-time=-6h`; локальный Prometheus хранит 12 часов, поэтому на границе остаётся около 6 часов перекрытия. Это фильтр чтения, а не удаление блоков. Если sidecar недоступен, на raw-архив как на резерв для последних 6 часов рассчитывать нельзя. При изменении retention перепроверить перекрытие. Источники: [Thanos](../../../charts/thanos/values.yaml), [Prometheus](../../../charts/prometheus/values.yaml); исправление `69a0a2bf`.

**Что произошло.** На Traffic Light графики n8n (920) и VPN (907) показали разрывы утром. В 08:00 МСК в архив уже попал блок `from-out-of-order` за 07:00–09:00: его границы охватывали два часа, но внутри были только опоздавшие точки. На момент расследования обычного блока за этот период в архиве ещё не было. Один и тот же запрос панели с шагом 60 с дал разные результаты:

| Источник | Результат до исправления |
| --- | --- |
| Напрямую в Prometheus или через Thanos только к sidecar | Нет разрывов |
| Только raw Store Gateway | Неполный ряд |
| Sidecar и raw Store Gateway вместе | Разрывы воспроизводятся, в том числе без дедупликации и downsampling |

**Как проверить повторение.** Взять точное выражение панели из [Traffic Light](../../../charts/monitoring-k3s/dashboards/traffic-light.json), не убирая проверку свежести. С одинаковыми `start`, `end` и `step` сравнить `/api/v1/query_range` напрямую в Prometheus и через datasource Grafana `prometheus` (он читает Thanos). Если ответы различаются, в Thanos ограничить `storeMatch[]` сначала адресом sidecar, затем адресом raw gateway из `/api/v1/stores`, затем запросить оба. Сравнивать значения и временные метки каждой серии, а не только статус HTTP или наличие серии. Если ряд отсутствует уже в локальном Prometheus, это другой случай: проверять сбор и доставку, не подставлять нули.

**Приёмка после выкладки:** за 07:15–08:00 МСК все 46 минутных точек каждой серии обеих панелей через Grafana совпали с Prometheus; в двухчасовом окне вокруг границы чтения совпали все 121. На глубине 19–20 часов архив вернул все 61 точку каждой серии. Панели и их запросы не менялись.

**Отдельная проблема:** в те же часы отправители OTLP регистрировали `DeadlineExceeded`; экспортёр n8n сообщил об отбрасывании 673 точек метрик (не запусков workflow). Это реальная ошибка доставки, но не объяснение разрывов, для которых локальный ряд был полон. Причина таймаутов и отдельного пропуска VPN в 09:16 не установлена.

## Current placement delta —16 November 2026

Grafana и Grafana MCP приняты на `socrat-5`, новый Grafana claim
`grafana-socrat5`, старый claim на `socrat-1` stale/Retain. Native SSO, существующие
идентичности и настоящий read-only MCP→Grafana→Thanos запрос проверены.
[Полная приёмка и downtime](https://github.com/alchemmist/homelab/blob/2fd1179442b3c7b05c9049dfa4bbaa47bfbc3790/docs/vm105-grafana-20261116.md).
Prometheus/Thanos и другие backend не переносились этим изменением. Таблица
владельцев ниже остаётся полезной, но runtime-утверждения среза7ноября не являются
новой приёмкой всех компонентов. Источник Grafana также включает
`deploy/storage/grafana-socrat5`; актуальные ссылки — в Application.

## Historical split checkpoint —7 November 2026

Актуализировано **7 ноября 2026**, после завершённых handoff Grafana/backends (`f4020d1`),
пяти Prometheus-компонентов и runtime-проверок. Это заменяет ранний read-only срез промежуточного split.
Не объявляет новый browser-MFA acceptance, каждый producer исправным или независимый DR.

## Argo ownership после split

| Application | Источник | Ответственность |
| --- | --- | --- |
| `grafana` | `charts/grafana`, `deploy/platform/grafana/public-entry` | Native Grafana, datasource provisioning, public policy и TV assets |
| `prometheus` | `charts/prometheus` | Только Prometheus, его storage/конфигурация, общие rules и cluster monitors |
| `alertmanager` | `charts/alertmanager` | Только Alertmanager, routing/config, свои Service/SA/rules |
| `prometheus-operator` | `charts/prometheus-operator` | Контроллер, CRD, admission webhooks и правила оператора/reloaders |
| `node-exporter` | `charts/node-exporter` | Нодовый DaemonSet, Service/monitor и собственные правила |
| `kube-state-metrics` | `charts/kube-state-metrics` | Экспорт состояния Kubernetes, RBAC/Service/monitor/rules |
| `loki` | `charts/loki` | Logs backend и scoped retention resources |
| `tempo` | `charts/tempo` | Traces backend |
| `pyroscope` | `charts/pyroscope` | Profiling backend и его Grafana integration |
| `monitoring-k3s` | `charts/monitoring-k3s` | Dashboard JSON, rules, probes и связанные monitoring resources |

Все указанные apps — Synced/Healthy. Auto-sync Loki/Tempo восстановлен:
временный `automated.enabled=false` снят, `prune=false/selfHeal=true` сохранены.
Старые `kube-prometheus-stack`, `prometheus-stack`, `otel-backends`, `profiling` удалены из Git/кластера
после снятия finalizers и передачи владения. 103 UID существующих объектов сохранены
(в том числе 10 shared CRD: после окончательного разделения их scope —
`prometheus-operator`, без принудительных tracking annotations).
PVC/Secret/Certificate UID не менялись. Только неиспользуемый ConfigMap
`otel-backends` удалён с UID/resourceVersion preconditions после проверки ссылок.
Не повторять retirement и не включать старых owners. Карта и полный протокол:
[monitoring-service-split.md](monitoring-service-split.md).

В Grafana сверены private согласованные SQLite snapshots: users/org/memberships,
datasource identities, dashboard UIDs, OAuth links и public shares сохранены.
Native OIDC redirect работает; public regression134/134 и TV24/24 на двух IP прошли.
Loki/Tempo verified-mTLS `/ready`200, отказ без client cert, свежие logs и stored
traces проверены без вывода содержимого. Это не physical-TV/browser-MFA повторная
приёмка. Новый TV layout/JS из параллельных `832e341`/`757dc18` сохранён.

App name не равен Helm release или Service name: имя
`kube-prometheus-stack-grafana` у pod/service не возвращает владение старой app.
Текущие manifests: `deploy/argocd/apps/{grafana,prometheus,alertmanager,prometheus-operator,node-exporter,kube-state-metrics,loki,tempo,pyroscope}.yaml`.

Последний aggregate `prometheus-stack` также разобран: все 77 ресурсов переданы
пяти независимым Applications, render payload совпадает полностью. Все 8 runtime
Pods сохранили UID/ноду/readiness/restarts; все 4 PVC сохранили bound volumes;
3 целевых Secret (включая webhook TLS) сохранили UID **и содержимое**. Prometheus
по-прежнему находит прежний Alertmanager endpoint. Ни WAL repair, ни переустановка
оператора, ни миграция данных не требовались. Детали и source-provenance:
[prometheus-service-split.md](prometheus-service-split.md).

## Зафиксированный closeout, не новая команда миграции

Окончательное разделение: disarm `652e286` → передача пяти владельцам `78a9336`
→ удаление aggregate `bcc93ca` → checkpoint **`0bb4e31`**. На финальном срезе все
**49 Applications**, включая `root`, были Synced/Healthy. При этом
`PrometheusTSDBCompactionsFailing` оставался firing: Argo Healthy не означает
целостность WAL. Watchdog — отдельный ожидаемый heartbeat.

Приёмка последнего этапа: **104 профильных теста + 24 pytest subtest**, Helm lint
пяти component charts, Ansible syntax check; public-access regression **134/134**.
Более ранние TV24/24 относятся к предыдущей приёмке Grafana, не к новому физическому
тесту телевизора. Результаты этапов не складывать в вымышленный общий test suite.

Private UID/Pod/PVC/Secret-hash/render receipts последнего handoff сохранены 0600
в `~/.config/homelab/monitoring/migrations/2026-11-07-prometheus-components/`.
Это rollback evidence без вывода содержимого Secrets, не off-node backup/DR.
Для обратной передачи владельца снова нужны disarm и снятие deletion finalizers;
**не делать blanket git revert**, удаляющий новые Applications с активными
finalizers: это может каскадно удалить workload. Обычный rollback версии — новый
коммит в source текущего владельца, с сохранением данных.

## Данные и pipeline

- OTel Collector — sole scraper; Prometheus принимает OTLP с согласованным
  out-of-order окном30m и NoTranslation. Не добавлять второй scrape path для тех же
  target и не «чинить» дубли удалением исторических данных.
- Loki3.7.9 / Tempo2.10.10 — Kubernetes workloads, persistent nonroot storage,
  защищённые backend entrances; старые host units не основной pipeline.
- Loki retention intent: debug3d / info7d / other14d; scoped marker/temp cleanup,
  не blanket удаление bucket/PVC. Версии/настройки сверять с актуальными charts.
- Историческая миграция метрик завершена; факт принятой небольшой потери не
  разрешает придумывать backfill. Thanos raw/5m/1h storage и compaction — отдельные
  runbooks; полная hourly shipping/DR acceptance не объявлялась завершённой.
- Grafana refresh и dashboard range — presentation, не гарантия полноты ingestion.
  Не превращать отсутствие телеметрии в zero/green и не скрывать gaps интерполяцией.

Источники: [monitoring](monitoring.md),
[logging operations](../logging/unified-logging-operations.ru.md),
[retention](../logging/otel-loki-retention.md), `deploy/monitoring/otel/`,
`deploy/monitoring/migration-evidence/`, текущие chart values и resource budgets.
Старые ссылки на отсутствующие в этом checkout otel-history runbooks не являются
достаточным основанием запускать migration/delete scripts.

## Software update alerts

Third-party images are compared with the newest stable GitHub release by `monitoring-update-watch` in `charts/monitoring-k3s` (`updateWatch.targets`). The Prometheus rule is `SocratSoftwareUpdateAvailable` (`for: 15m`, severity warning). It uses the same Grafana alert graphs, Alertmanager, n8n workflow and socrat-bot `POST /v1/messages` path as other warning alerts. This is one cluster-wide alert, not one instance per app: its value counts apps with an update. The primary graph shows one step line per catalog app (0 = checked and current, 1 = newer stable release, missing = unknown). Version changes do not create new lines. A new release appears after the next successful lookup, not at publication time. While the alert is already firing, another app switching to 1 changes the graph and count, not the alert identity. Nothing in this path upgrades a workload.

Installed version comes from the running container tag when the tag contains `x.y.z`. Digest-only images use `updateWatch.targets[].current`, which must be changed in the same commit as the chart pin. Open WebUI and 3x-ui are in the catalog. Xray is not a separate Deployment; it ships inside the 3x-ui image. Apps released from this homelab's own repositories are not in the catalog.

`SocratSoftwareUpdateCheckFailed` fires when a lookup stays unsuccessful for 6 hours. A failed lookup does not emit an update alert. SearXNG releases do not currently expose a stable `x.y.z` tag, so that target stays on the failed check rather than an update alert.

## Placement — наблюдение, не вечный контракт

На read-only срезе: Grafana/Loki/Tempo/Pyroscope и Grafana MCP на socrat-1,
Prometheus на socrat-0. Wiki и Authentik тоже на socrat-0. Не использовать старые
таблицы «весь monitoring на1 / Wiki на3» для работы с дисками или рестарта.
Scheduler/nodeSelector/PV affinity проверять для конкретного приложения.

## Dashboard, TV и APIs

Dashboard JSON: `charts/monitoring-k3s/dashboards/`; datasource configuration —
`charts/grafana/values.yaml` и templates. Alerts/probes — monitoring-k3s. Не путать
native per-app authorization с инфраструктурным namespace и read-only MCP identity.

Public traffic-light — единственный явный share, не anonymous org Viewer.
Headerless TV geometry обновлена в `832e341`; прежние hard-coded panel positions
из октябрьских заметок не текущая layout specification. Источники — dashboard JSON,
`deploy/platform/grafana/public-entry/files/traffic-light-inset.js` и
[TV design](../../applications/android-tv/traffic-light-tv-design.md), а не инъекция JS в Fully.
Последующая documented приёмка (`29f41d9`): dashboard `832e341`, kiosk parity
`757dc18`, четыре real-browser случая (public/authenticated kiosk ×1920×1080/1440×900),
40 targeted tests и24 public access checks. Это evidence другой выполненной
приёмки, не повторный браузерный тест этой doc-задачей. Физический remote/cold boot
и независимый внешний ISP этим не проверялись.

Grafana MCP — public verified-TLS endpoint с отдельным bearer и Viewer/read-only
native identity. Secret нельзя коммитить/печатать; browser MFA не подходит machine
API. Для чтения использовать MCP/API, браузер — для визуального acceptance.

[Деплой](../../platform/cluster-deploy.md) · [сеть](../../network/network-access.md) · [TV](../../applications/android-tv/README.md) ·
[SPI](../../applications/spi/spi-incident-triage.md) · [n8n](../../n8n/n8n-workflows.md).


## Отдельные инциденты, замеченные при закрытии split

- **PrometheusTSDBCompactionsFailing**: в логах 2026-11-07 09:00 UTC checksum
  corruption WAL segment `00001786` при checkpoint/truncation. Это раньше disarm
  split в 10:20 UTC; Prometheus Pod миграцией не перезапускался. Ready/Argo Healthy
  не доказывает целостность WAL. Алерт не выключали, WAL/blocks не удаляли и не
  откатывали; нужен отдельный безопасный разбор с backup перед repair.
- **Blog**: параллельный robot release `8b3e079` записал Harbor digest
  `sha256:c476e069de95fd3daafaac09f1f1fcf58f65230deaecb6740b5b9cf84aae8c99`,
  который registry возвращает NotFound. Новый pod — ImagePullBackOff, два прежних
  продолжают обслуживать. Это отдельный release incident, не результат переноса
  Grafana/Loki/Tempo. Вскоре независимый robot release **`f485c74`** записал
  доступный digest; повторная проверка после `4124691`: blog **Synced/Healthy**.
  Этот инцидент закрыт параллельным релизом, не repair мониторинга. Чужой release
  в ходе split не откатывался и образ вручную не подменялся.
- Root показывал отдельный metadata drift Rancher: Argo-managed PostDelete
  finalizers отсутствовали в Git. В manifest задекларированы **уже существующие**
  finalizers, не удалены hooks и не добавлен ignoreDifferences. Rancher runtime,
  MCM/Fleet и значения chart этим не менялись.

Watchdog severity=none — ожидаемый heartbeat, не доказательство отсутствия других
алертов. Не объявлять весь кластер здоровым по зелёным новым Applications.

### Public status redirect repair

`status.alchemmist.xyz/` ошибочно редиректил на
`http://status.alchemmist.xyz:8080/status/socrat`: stock nginx policy proxy
формировал absolute redirect из внутреннего listener8080 после TLS termination.
В `charts/uptime-kuma/files/kuma-policy.conf` добавлен `absolute_redirect off`:
Location теперь относительный `/status/socrat`, HTTPS/public origin сохраняются.
Изменены только policy config и обусловленный checksum rollout proxy, не Kuma
DB/PVC, native auth или UI gateway. Reviewed ownership fixture обновляет только
ConfigMap policy и Deployment proxy; исходная handoff-версия остаётся в Git history.

### socrat-2 watchdog incident and recovery — 2026-11-07

[Forensic report](../../records/incidents/vpn-incident-2026-11-07.md): four failed TLS/WebSocket
checks from20:02:22 MSK caused the VPN watchdog to stop k3s at20:03:56 and fence
VPS Pods. This was an explicit stop, not a proven k3s crash/OOM. Exact first
handshake error was discarded by the old helper; timeout/certificate/false-positive
explanations remain unproven. Native fallback became healthy but intentionally did
not auto-failback.

Corrected stale live `agent_unit` (agent→server); isolated Kubernetes-start timeout
from40s to180s after first controlled failback timed out. Added safe probe error
classification, without private paths/tokens. Threshold4, TLS verification and
fencing safety retained. Controlled second failback succeeded: all4 nodes Ready,
x-ui/Traefik1/1, native units stopped, timer resumed. Authenticated public Trojan
TLS/WebSocket → HTTPS200 verified. Pods were replaced after fencing; DBs were not
reset/restored. Private backup/journal paths and limitations are in the report.


### Watchdog hardening after the incident

Role/Python defaults now select `k3s.service`, consistent with socrat-2's etcd-only
server role. Legacy `k3s-agent.service` remains only a compatibility fencing/guard
reference or historical context; do not delete it from the safety lists.

After4 scheduled failures, watchdog requires2 further bad samples1s apart before
fencing; recovery cancels activation and resets failures. Native startup has30s
monotonic/boot-scoped warm-up (still unhealthy if checks fail), and native restarts
also require confirmation. Failback checks target identity before stopping VPN;
failed server startup attempts immediate native rollback. No automatic failback,
TLS weakening or alert muting. Safe last-failure receipt retained outside Git.
See [current protocol/defaults](../../network/vpn-failover.md#hardened-detection-and-service-identity).

Hardening applied live without restarting k3s, x-ui or Traefik; their current Pod
names were retained, all4 nodes Ready, native primary/Caddy inactive, timer active.
Post-update scheduled probes healthy/failures0.63 focused tests +2 subtests and
Ansible syntax-check pass. Error/confirmation/warm-up/rollback branches are unit
and fault-injection tested; no additional production outage was deliberately
triggered to exercise the new fencing policy. Private installation receipts are
under `/var/lib/homelab-vpn-failover/hardening/2026-11-07/` on socrat-2.

### 2026-11-09 recovery continuation

Full receipts: `docs/records/incidents/cluster-recovery-20261109.md`. Old WAL00001786 checksum fault
predates night outage (already Nov7).13:34UTC exact one-bit repair applied atomically
without restart/truncate/replay: pinned native decoder6409 records valid and all
11716 affected samples independently match raw Thanos history exactly; off-host
original/candidate SHA verified. **Next native checkpoint and3h alert expiry still
pending**; no restart shortcut. Physical bit-flip cause unproven.

vLLM actual kubelet allocation/request10Gi,24Gi limit, same process; natural observer
13:48 success and critical alert cleared. Four power/fresh-quorum safety rules live
(source has native promtool tests; verify actual evaluation). Node3 native durable
storage compaction preserved all queues/cursors with consistent backup/off-host
copy; queue25→9MB, delivery continues/refused0, HDD I/O pressure remains under watch.
`fsync=true` retained. fwupd metadata service naturally success/no firmware install.
Three historic failed Job objects retained; current natural replacements succeed;
no alert masking or deletion solely for green.

14:40 continuation: node3 queues fully drained; explicit1s filelog polling and
infinite receiver retries validated/applied only there with5.22s agent-only lifecycle
and new consistent archive. fsync kept. HDD mean60s17% vs39% after-drain baseline;
actual5m PSI I/O6.9%, contention alert naturally cleared; native Loki522 fresh
records/5m. Three healthy etcd voters/common-revision hash agreement rechecked;
new159MB consistent snapshot/current17-client native panel backup both off-host SHA
verified. Original16 identities/85 bindings unchanged;1 external addition not
attributed or deleted. Backend validator now accepts only exact redundant nb-host
allowance; public eth0 deny untouched and externally re-proven. Next native WAL
checkpoint remains the remaining functional gate;3 old failed Jobs retained.

**15:10UTC final WAL gate accepted:** normal Prometheus checkpoint1786→2388 completed
in9m54s; checkpoint2388 exists, same Pod/all container IDs, no new compaction error
in native watch. No forced restart/truncate/replay. Historical3h counter alert still
visible;3 old failed Jobs have no TTL and remain intentionally unchanged.15:15:
all4 nodes Ready/no active nonready Pods; strict-TLS LMS303, Umami heartbeat200;
observer/SPI/Wiki/Thanos natural successes fresh. Node3 I/O5m5.4%, alert cleared.
Native checkpoint/functional receipts supersede earlier pending-gate notes above.


## Wishlist — 2026-11-16

Private8001 metrics via the existing native Collector; own renewable mTLS leaf
and browser/backend OTel are live. Actual anonymous15-span browser→Traefik→app→DB
trace, Loki correlation and Thanos up/inventory success1 accepted. Dashboard
`wishlist-performance`; no second sampler/scraper, public OTLP or CA key copying.
Exact Collector egress to Wishlist8001 is required. Existing extraneous
ConfigMap/wishlist is NOT pruned; desired resources reconciled, not blanket Argo
health. Real user slow upload/production login remain outside canary acceptance.
[Runbook](wishlist-observability.md) and its JSON evidence are authoritative.
