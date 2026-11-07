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
(в том числе 10 shared CRD в Prometheus scope без принудительных tracking annotations).
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
