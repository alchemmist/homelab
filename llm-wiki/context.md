# Socrat: контекст работы с кластером и мониторингом

Срез на **20 октября 2026**. Это краткая памятка для продолжения работы, не замена live-проверке. Старые таблицы размещения в README/docs могут отставать от scheduler.

## Что мы делаем

Развиваем личный homelab Socrat: Kubernetes/K3s, VPN, приложения, локальный LLM, приватное администрирование, мониторинг и разумное распределение ресурсов. Постоянные изменения оформляем в **Ansible/Helm/Git**, а не оставляем только ручные правки в UI или kubectl.

## Устройство кластера

| Нода | Роль | Основное назначение |
| --- | --- | --- |
| socrat-0 | Дом; control-plane + etcd | GPU RTX 3090, vLLM, большая часть LLM-стека; домашний NFS |
| socrat-1 | Дом; control-plane без голоса etcd | Grafana/Prometheus/Alertmanager, Open Terminal, приложения |
| socrat-2 | Зарубежный VPS; etcd + workload agent | 3x-ui/VPN, Remark42, Kuma, внешний Traefik Edge |
| socrat-3 | Внешняя площадка; control-plane + etcd | Wiki, часть инфраструктуры; также пользовательский desktop |

- Etcd: **0/2/3**, кворум — два голоса. Нода 1 не голосует. Несколько control-plane не означают репликацию приложений и их данных.
- Ноды связаны WireGuard; пользователь называет сеть `socrat-wg`, системный интерфейс — `wg-socrat`. WG IP нод 0/1/2/3: `10.250.0.1`, `.3`, `.2`, `.5`.
- У публичных HTTP-сервисов два входа: квартира `109.173.40.247` и VPS `176.98.185.59`, две A-записи в REG.RU, домашний Traefik и Traefik Edge. Автоматического DNS failover нет; переключение зависит от клиента.
- **Два IP не резервируют backend/SQLite/PVC.** Kuma — одна реплика на VPS с `hostPath /srv/uptime-kuma`; мониторинг имеет локальные PVC на socrat-1; GPU — только на socrat-0. Полную потерю квартиры все приложения не переживут.
- Rancher, Grafana и Grafana MCP доступны через приватную WG-сеть, DNS и доверенный HTTPS, не через публичный ingress. Anonymous Viewer в Grafana оставлен намеренно; административные права — отдельно.

Подробности: `docs/k3s-ha.md`, `docs/public-ingress.md`, `docs/wireguard-admin-access-plan.md`, `docs/vpn-failover.md`.

## Grafana, метрики и алерты

- Стек в `cattle-monitoring-system`: kube-prometheus-stack, Prometheus, Grafana, Alertmanager, kube-state-metrics, node-exporter; дополнительные GPU/LLM-метрики и blackbox-пробы.
- Четыре основных dashboard: **Overview, Nodes, Services, LLM**. Nodes выбирает одну ноду по имени; LLM включает vLLM, LiteLLM, очереди, latency, ошибки, GPU/VRAM/температуру.
- В папке **Rancher** оставлены 12 встраиваемых dashboard без префикса `[Rancher]`; UIDs и переменные важны для интеграции. Неиспользуемые шаблоны и 38 Kubernetes Diagnostics удалены из provisioning; пустая старая папка могла остаться.
- Overview: крупные Cluster health, capacity gauges с used/total, Node resources, компактная Services · Availability, control plane, активность/restarts. Services: 31 плитка на 33 endpoint; Syncthing объединён в одну плитку с тремя экземплярами.
- **Все заголовки и описания панелей — English.** У каждого графика понятное описание. Легенды — имена нод, не IP; устраняем дубли от смены exporter/pod, не теряя реальные отдельные серии.
- Числовые stat-панели компактные; ключевые Cluster health крупнее. Плитка алерта — название и цвет без повторения статуса; клик ведёт в конкретное правило Grafana. Rancher — отдельная явно внешняя ссылка.
- Цвета наших плиток: зелёный Clear, жёлтый Pending, красный firing warning/critical, синий firing info, серый N/A/нет телеметрии. Это наша настройка, не универсальная семантика цветов Grafana.
- Не превращаем потерю телеметрии в здоровый ноль. CPU quota throttling без квот — N/A, а не поломка метрик. Его не путать с температурным throttling CPU.
- Для редких latency/cache/error observations используем компактные итоги выбранного диапазона, а не бессмысленные «дырявые» линии. Не скрываем реальные пропуски данных интерполяцией. Restart bars показывают `increase` за интервал, не rate; оценки Prometheus могут быть дробными.
- Canonical `root_url` — `https://grafana.socrat.alchemmist.xyz/`, не localhost. Сохраняем совместимость с проксированием/встраиванием через Rancher.
- Loki/Alloy, Telegram-доставка и звонковые алерты пока не реализованы как завершённые этапы. Alertmanager первоначально настроен без доставки уведомлений; наличие правил не означает отправку сообщений.

## Как работаем через Grafana MCP

- Endpoint: `https://grafana-mcp.socrat.alchemmist.xyz/mcp`, Streamable HTTP, отдельный bearer token, доступ через WG. Сервер настроен **read-only**, Grafana identity — Viewer.
- В этой сессии доступны инструменты `mcp__socrat_grafana__…`: `query_prometheus`, `get_dashboard_by_uid`, `get_dashboard_property`, чтение alert rules. В новой сессии сначала проверять доступность инструментов.
- Prometheus datasource UID: `prometheus`. Для instant query передавать `queryType: "instant"`, `endTime: "now"`, `datasourceUid` и `expr`; для range — также startTime/stepSeconds.
- Метрики, запросы и alert instances читаем MCP. Playwright используем только для проверки внешнего вида/поведения frontend, не вместо API.
- Токены/пароли не выводить и не сохранять в Git. Подключение описано в `docs/grafana-mcp.md` и `wiki/content/observability/grafana-mcp.md`.

## Где менять и как применять

| Что | Источник |
| --- | --- |
| Основные dashboard | `charts/monitoring-k3s/dashboards/{overview,nodes,services,llm}.json` |
| Правила и service probes | `charts/monitoring-k3s/templates/`, каталог `serviceProbes.targets` в `values.yaml` |
| Базовый monitoring stack/Grafana | `deploy/monitoring/values.yaml` |
| Связи плиток с native alert details | `ansible/roles/monitoring_k3s/files/resolve_alert_links.py` |
| Rancher embedding | `ansible/roles/monitoring_rancher/` и `deploy/monitoring/` |
| Resource/placement profiles | `ansible/vars/container-resources.yml` |

Из `ansible/`:

```sh
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/monitoring.yml --tags monitoring_k3s
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/container-resources.yml
ansible-playbook -i inventory/hosts.yml -i inventory/socrat-3.yml playbooks/socrat-2-offload.yml
```

Для базового стека добавляем tag `monitoring_base`, для embedding — `monitoring_rancher`. Права sudo зависят от playbook; пароль передавать безопасно, не в репозитории. SSH через dual-address hostname может попасть не на тот вход: используем проверенные прямые inventory overrides с правильным HostKeyAlias. Для kubectl на socrat-0: `env K3S_CONFIG_FILE=/dev/null k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml …`. Временные `/tmp`-файлы прошлой сессии не считать постоянными зависимостями.

Порядок работы: измерить → изменить declarative source → unit/Promtool/Helm/Ansible проверки → точечное применение → проверить live readiness, метрики, probes и при необходимости UI. Коммит сам по себе ничего не разворачивает. Прямые аварийные patches обязательно отражать в источниках.

## Ресурсы и последний результат

- Вместо одинаковых CPU limits всем введены 56 индивидуальных профилей: requests CPU/RAM/ephemeral-storage, индивидуальные memory/storage ceilings. Requests — планировочный бюджет, не заранее выделенная RAM; limits не резервируют мощности.
- CPU caps оставлены только Open Terminal **6**, его cleanup **100m**, vLLM **8**, SearXNG **1**. Для остальных CPU может использовать свободную мощность. Chromium ранее создавал runaway; этот пик не взят за нормальный request.
- Нативная MutatingAdmissionPolicy задаёт эффективные Pod resources поверх шаблонов Helm/operators. Изменять бюджет нужно в каталоге. Новые версии/контейнеры требуют повторного аудита. Профили умеют закреплять nodeSelector, сохраняя посторонние labels.
- Первичный sizing основан примерно на **84 часах**, не полной неделе. Запас проверяем по каждой ноде и реальной памяти, учитывая host-процессы; сумма limits может превышать физическую RAM. N−1 и все одновременные пики не гарантированы.
- Последний перенос завершён: **metrics-server, local-path-provisioner и img-proxy на socrat-1**. На VPS освободилось 192Mi requests; осталось около 479Mi незарезервированной RAM. Все 15 PV specifications/UID сохранены, данные томов не переносились. Metrics API работает, image proxy проверен через оба публичных IP.
- На socrat-2 остаются VPN, Remark42, Kuma, Traefik Edge, Syncthing и две telemetry-службы. У Syncthing там **ноль папок**; удалить его можно отдельно, согласованно изменив DaemonSet/probes/ожидаемые три экземпляра плитки и сохранив конфигурацию. Пока не удалён.
- После переноса 74 Pod соответствовали профилям и были Ready. Финальная повторная проверка: все **33/33** service probes свежие и успешные, Metrics API возвращает четыре ноды, все ноды Ready без pressure. Временный отказ probe **Wiki** больше не воспроизводится; причина не установлена, исправление Wiki не выполнялось.

Подробные расчёты и ограничения: `docs/resource-budgets.md`; мониторинг: `docs/monitoring.md`, `docs/monitoring-llm.md`.

## Ограничения работы и состояние Git

- Не выключать ноды и не отбирать у них сеть для тестов. Не удалять данные/бэкапы на Mac. Перезапуски сервисов — последовательно, с проверкой замены, PDB и готовности; широкую пересоздачу включает только явный `container_resource_policy_reconcile=true`.
- Не ослаблять приватный доступ ради healthcheck. Проверять сервис из WG/кластера; TCP/HTTP probe не равен полноценной VPN-сессии или внешней доступности.
- Последний завершённый push: `24050eb` — четыре тематических коммита (search, resources, monitoring, socrat-3). Последующий offload, поддержка placement и эта памятка пока не закоммичены. Перед дальнейшей работой проверить `git status`; есть параллельные desktop-изменения, их не затирать.
- Не коммитить/пушить без запроса. Сообщения коммитов — одна строка, English lowercase, без co-author. Для GitHub API — MCP, не `gh`.
- Проверки offload: 47 resource/budget unit tests + 4 scope tests, server dry-runs и Ansible прошли. Ранее прошли 191 service-probe и 18 throttling Promtool cases. В полном Python suite есть два старых падения `test_wireguard_admin_client`, воспроизведённых на исходном main; не путать с регрессией этой работы.


## Сессия 24 октября 2026: Traffic-light и TV Grafana

В этой сессии Traffic-light dashboard был доведён до текущего TV-вида.

### Источник и раскладка dashboard

- Dashboard UID: `socrat-traffic-light`, файл `charts/monitoring-k3s/dashboards/traffic-light.json`.
- TV URL: `https://grafana.socrat.alchemmist.xyz/d/socrat-traffic-light?kiosk=1&hideLogo=1&autofitpanels=true`.
- Общий диапазон dashboard: `now-3h` до `now`, refresh `5s`.
- Справа находятся CPU, Memory, Disk и CPU temperature; их высота сохраняется полной (`y=0,h=7` и `y=7,h=8`).
- Слева расположены alert/service tiles и график External traffic · RPS.
- RPS считает внешний HTTP(S)-трафик через Traefik entrypoints `web`/`websecure`: линии `2xx`, `3xx`, `4xx`, `5xx`, `Total`.
- Легенда графика скрыта, сетка возвращена, подписи осей оставлены. Ось Y использует `unit: none` без лишних `req/s` и сотых; линии тонкие, Total светло-серый `#9aa7b8`.
- Нижняя граница RPS выровнена с правыми resource-панелями; свободных вертикальных зон между плитками и графиком быть не должно.
- Последнее согласованное состояние после отката неудачного эксперимента с нижними плитками: `panel-329`, `panel-330`, `panel-333` имеют `y=9,h=1`, RPS `panel-334` имеет `y=10,h=5`.

### Внешний трафик и scraping

- Home Traefik уже отдаёт `traefik_entrypoint_requests_total` на metrics-порту `9100`, но изначально Prometheus его не скрейпил.
- В `charts/monitoring-k3s/templates/traefik-metrics.yaml` добавлены ClusterIP Service и ServiceMonitor; обе реплики Traefik имеют target `up`.
- Grafana/Prometheus live-проверка подтвердила рабочие серии и запросы RPS.
- VPN через Traefik Edge в RPS не включён: это TCP/Trojan, а не HTTP requests. Для него нужны отдельные connection/bytes или Xray-метрики.

### TV и Fully Kiosk

- Телевизор: Xiaomi MiTV-MOOQ1, Android 11, физическое разрешение `1920x1080`, ADB `192.168.0.19:5555` через `socrat-0`.
- Fully перезапускается через:

```sh
adb -s 192.168.0.19:5555 shell am force-stop de.ozerov.fully
adb -s 192.168.0.19:5555 shell monkey -p de.ozerov.fully 1
```

- `ansible/playbooks/tv-admin.yml` теперь хранит Fully `initialScale: "55"`, `fontSize: "75"` и URL с `autofitpanels=true`.
- Реальный screenshot через ADB использовался для проверки раскладки и границ панелей.
- Grafana Time series рисует оси через uPlot canvas с фиксированным стандартным размером оси; отдельной настройки font-size осей в dashboard JSON нет. Поэтому масштаб Fully уменьшает обычный WebView UI, но не меняет пропорционально canvas typography.
- Рекомендуемый штатный путь для TV — kiosk/fullscreen, `autofitpanels=true`, отдельная TV-раскладка и компактные grid-панели. CSS/JS-патчи для уменьшения осевых шрифтов не добавлялись.

### Provisioning и ручное редактирование Grafana

- Основные dashboard provisioned через ConfigMap/sidecar из Helm chart. Поэтому Grafana показывает `Managed by: File provisioning`.
- Для разрешения UI-сохранений в `deploy/monitoring/values.yaml` включён `grafana.sidecar.dashboards.provider.allowUiUpdates: true`.
- `traffic-light.json` содержит `editable: true`.
- Важно: UI-правка сначала живёт в Grafana DB. Чтобы не потерять её при provisioning/PVC-инциденте, нужно экспортировать dashboard через `/api/dashboards/uid/socrat-traffic-light`, перенести осмысленные изменения в JSON и закоммитить их в Home Lab.
- В текущей ручной правке были увеличены по высоте панели `325–328` (VPN, 3xUI, LiteLLM DB, Umami DB), но затем по запросу пользователя раскладка была возвращена к прежнему состоянию и сохранена в Git.

### Коммиты этой части работы

- `2421baf show external traffic response rates`
- `5e8d86f compact traffic light dashboard layout`
- `2443398 show three hour traffic window`
- `358633b preserve resource panel height`
- `a16e1f9 fit traffic chart on tv screen`
- `59d5a0e simplify traffic chart chrome`
- `2793cb1 restore traffic chart axes`
- `b49edd0 restore traffic chart grid`
- `50515b6 manage tv page scale`
- `03a8470 enable grafana tv autofit`
- `1c36fb6 refine traffic chart lines`
- `92061dc balance tv dashboard vertical space`
- `69cc1ae compact traffic axis labels`
- `4830572 tighten tv resource gauges`
- `a8eab4f restore resource gauge text size`
- `90bb6b3 uniform service tile sizing`
- `e77baf8 balance compact traffic chart`
- `6805b20 fill tv dashboard vertical space`
- `d4c95b1 square lower service tiles`
- `509f1b9 allow grafana dashboard editing`
- `e30c567 save manual traffic tile layout`
- `0437f6c restore previous traffic layout`

Live deployment revisions reached monitoring-k3s Helm revision 136 during the session. The final dashboard source must remain the source of truth; UI changes should be exported and merged deliberately.
