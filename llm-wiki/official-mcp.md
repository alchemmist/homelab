# MCP для агентов Homelab — 2026-11-07

Точка входа агента — `AGENTS.md`, настоящий project config — `.pi/mcp.json`.
Протокол первоначального подключения: [runbook](../docs/official-mcp.md),
[реестр всех сервисов на момент аудита](../deploy/mcp/service-audit.json).
Последующее локальное включение n8n описано ниже; прежний blocker в реестре
не означает текущий отказ endpoint.
Аудит охватил 49 Argo Applications, все Deployment/StatefulSet/DaemonSet и running
systemd units четырёх нод, не только приложения из каталога Helm.

## Подключения

- `socrat-grafana`: уже развёрнутый официальный Grafana MCP2.0.2; Viewer,
  disable-write, добавлены Loki/Tempo/Pyroscope. Через него доступны dashboards,
  Prometheus/Thanos, Alertmanager, logs/traces/profiles. Пароли/сертификаты не ротируются.
- `argocd`: официальный **Argo CD Labs** MCP0.9.0, pinned npm lock, stdio/read-only.
  Для desired state по-прежнему GitOps, не live mutation из MCP.
- `socrat-metrics`: официальный Prometheus MCP stable0.18.0, stdio, общие
  read-only PromQL/docs/metadata APIs через Grafana Viewer и **Thanos datasource**.
  Это не прямой TSDB/admin/WAL API. Не ставить `--prometheus.backend`: в этой версии
  он переопределяет allowlist и возвращает лишние, в том числе destructive, tools.
- `n8n`: native MCP **работает**. После локального обновления access token прошли
  реальные `initialize` и `tools/list`; сервер возвращает `search_workflows`,
  `execute_workflow`, `get_workflow_details`. В локальном project config Mac клиент
  включён, агентам открыты только search/details; execution остаётся hidden.
  Token хранится только в `~/.config/n8n/mcp-token` (0600), не в Git.
  Exact route `/mcp-server/http` принадлежит n8n; UI gate/TLS сохранены.
  Первоначальный backend403 больше не является текущим blocker.
- `umami`: официальный stdio0.2.0 установлен, но **нет разрешённого API key**.
  Client отключён; нужен scoped user/team analytics key0600, не пароль БД.
- Глобальный wiki MCP сохранён; GitHub в проекте остаётся отключённым.

`python3 scripts/setup-official-mcp.py` ставит проверенные upstream binaries и
реиспользует существующие Grafana credentials без ротации; приватные копии вне Git.
Новый агент/переподключение MCP загрузит project config после доверия репозиторию.
Не запускать credential helper вручную ради вывода токена. Другие машины/клиенты
требуют собственного setup; не обещать, что этот commit настроил их автоматически.

Нет MCP ради количества: NetBird/Rancher/RustFS — first-party исходники с оговорками
по стабильному пакету/авторизации; LiteLLM admin требует proxy_admin даже для reads;
Kuma MCP отсутствует в установленной stable2.5.7. Internal DB/cache, backup buckets,
контроллеры и наши сервисы не получают самописных/сторонних обёрток и широких прав.
Open Terminal имеет native MCP, но он открывает полный shell/file API под общим
ключом; это намеренно не включено как обычная диагностика.
Решение по **каждой** Application и upstream evidence — в реестре.

Read-only tools не разрешают агенту публиковать логи/приватные данные, исполнять
workflow, гасить alert или считать Healthy доказательством целостности WAL.
HTTP200 с HTML/IdP login — не успешный MCP initialize.

## Проверенный итог

Feature commit `e77eed4`; полный audit содержит также 271 Pod records (включая
completed jobs и operator-owned DB Pods) и 114 workload controllers — это **не**
число отдельных сервисов/MCP. В tracked config 3 включённых official connectors;
локальный ранее работавший wiki access сохранён отдельно.

Проверены actual Pi loader, Argo11/tools+реальный read, metrics10/tools+`query=1`,
Grafana37/read-only+auth rejection/dashboard/query. Loki/Tempo/Pyroscope metadata
действительно прочитаны через MCP, без вывода содержимого. Два n8n Ingress сохранили
UID и приняты n8n; Grafana/n8n Pods не перезапускались; MCP Secret UID/содержимое
не менялись. Намеренно rollout только Grafana MCP с новыми tool families.

131 test +24 subtests; public regression134/134. Старый WAL incident не исправлялся,
alert не скрывался. Это результаты первоначальной приёмки, не новый полный прогон.
n8n403 был первоначальным blocker и закрыт последующей проверкой протокола;
**Umami missing-key остаётся**.

В исходном грязном checkout сохранены dashboard/Traefik изменения; branch/source
не reset/merge. Его ignored project MCP config переведён на установленные cached
launchers после приватного backup старого symlink; shared target и Wiki override
сохранены. Не коммитить private local config с унаследованными credentials: новая
tracked версия в main содержит только безопасные ссылки. Новая доверенная сессия
увидит подключения; уже запущенную сессию MCP нужно переподключить.


## Итог после локального подключения n8n

Обязательных дополнительных MCP-развёртываний на кластере нет. Argo и metrics
серверы штатно запускаются у агента по stdio; переносить их в постоянные Pods
ради количества не нужно. Umami — опциональное продолжение, если агентам нужна
аналитика посещаемости: сначала отдельный разрешённый analytics API key.

Важно различать локальный и общий config: n8n включён в приватном
`/Users/antonmoss/code/homelab/.pi/mcp.json`; committed `.pi/mcp.json` пока содержит
консервативное `enabled: false`. Этот wiki-only update не меняет общий config,
runbook, audit или настройки других машин. При новом checkout проверить состояние
записи, наличие собственного разрешённого токена и protocol handshake, затем
включить клиент без расширения toolExposure. Не копировать весь локальный private
config в Git — там могут быть унаследованные credentials других MCP.

Новая сессия на настроенном Mac подхватит n8n; в существующей требуется reconnect.
Обновление токена не разрешает выполнение production workflows и не означает,
что они исполнялись при проверке: проверены только handshake и discovery.
Переданный через чат токен следует перевыпустить при ближайшей возможности;
это рекомендация безопасности, не текущий технический blocker. Значение токена
не повторять в документации, коммитах или логах.
