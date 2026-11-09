# Наблюдаемость: источники и владельцы

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
[monitoring-service-split.md](../docs/monitoring-service-split.md).

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
[prometheus-service-split.md](../docs/prometheus-service-split.md).

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

Источники: [monitoring](../docs/monitoring.md),
[logging operations](../docs/unified-logging-operations.ru.md),
[retention](../docs/otel-loki-retention.md), `deploy/monitoring/otel/`,
`deploy/monitoring/migration-evidence/`, текущие chart values и resource budgets.
Старые ссылки на отсутствующие в этом checkout otel-history runbooks не являются
достаточным основанием запускать migration/delete scripts.

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
[TV design](../docs/traffic-light-tv-design.md), а не инъекция JS в Fully.
Последующая documented приёмка (`29f41d9`): dashboard `832e341`, kiosk parity
`757dc18`, четыре real-browser случая (public/authenticated kiosk ×1920×1080/1440×900),
40 targeted tests и24 public access checks. Это evidence другой выполненной
приёмки, не повторный браузерный тест этой doc-задачей. Физический remote/cold boot
и независимый внешний ISP этим не проверялись.

Grafana MCP — public verified-TLS endpoint с отдельным bearer и Viewer/read-only
native identity. Secret нельзя коммитить/печатать; browser MFA не подходит machine
API. Для чтения использовать MCP/API, браузер — для визуального acceptance.

[Деплой](cluster-deploy.md) · [сеть](network-access.md) · [TV](android-tv.md) ·
[SPI](spi-incident-triage.md) · [n8n](n8n-workflows.md).


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

[Forensic report](../docs/vpn-incident-2026-11-07.md): four failed TLS/WebSocket
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
See [current protocol/defaults](../docs/vpn-failover.md#hardened-detection-and-service-identity).

Hardening applied live without restarting k3s, x-ui or Traefik; their current Pod
names were retained, all4 nodes Ready, native primary/Caddy inactive, timer active.
Post-update scheduled probes healthy/failures0.63 focused tests +2 subtests and
Ansible syntax-check pass. Error/confirmation/warm-up/rollback branches are unit
and fault-injection tested; no additional production outage was deliberately
triggered to exercise the new fencing policy. Private installation receipts are
under `/var/lib/homelab-vpn-failover/hardening/2026-11-07/` on socrat-2.

### 2026-11-09 recovery continuation

Full receipts: `docs/cluster-recovery-20261109.md`. Old WAL00001786 checksum fault
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
