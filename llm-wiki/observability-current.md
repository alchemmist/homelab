# Наблюдаемость: источники и владельцы

Срез **7 ноября 2026**, Git `832e341` и отдельное read-only чтение Argo/pods.
Не объявляет завершённым cleanup старых owners, синхронизацию root, новый browser
acceptance или независимый DR. Последующие commits/status проверять перед apply.

## Argo ownership после split

| Application | Источник | Ответственность |
| --- | --- | --- |
| `grafana` | `charts/grafana`, `deploy/platform/grafana/public-entry` | Native Grafana, datasource provisioning, public policy и TV assets |
| `prometheus-stack` | upstream kube-prometheus-stack92.10.0 + `deploy/platform/prometheus-stack/values.yaml` | Prometheus/operator/Alertmanager/exporters; upstream Helm release name прежний |
| `loki` | `charts/loki` | Logs backend и scoped retention resources |
| `tempo` | `charts/tempo` | Traces backend |
| `pyroscope` | `charts/pyroscope` | Profiling backend и его Grafana integration |
| `monitoring-k3s` | `charts/monitoring-k3s` | Dashboard JSON, rules, probes и связанные monitoring resources |

На срезе все шесть apps — Synced/Healthy. Но `loki` и `tempo` имеют
`automated.enabled=false`: selfHeal flag сам по себе не включает auto-sync.
Старые `kube-prometheus-stack`, `otel-backends`, `profiling` ещё есть, Healthy,
OutOfSync, с отключённым automated/selfHeal; root тоже OutOfSync/Healthy.
**Не включать старым owners auto-sync и не удалять их с finalizers ради зелёного
статуса.** Новый source owner, tracking, UIDs, render-equivalence, PVC/Secret и
hooks проверяются отдельно. Этот справочник ничего из этого не применяет.

App name не равен Helm release или Service name: имя
`kube-prometheus-stack-grafana` у pod/service не возвращает владение старой app.
Текущие manifests: `deploy/argocd/apps/{grafana,prometheus-stack,loki,tempo,pyroscope}.yaml`.

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
