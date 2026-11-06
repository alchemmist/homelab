# Ситуационная диагностика: не превращать гипотезу в автоматическую правку

Все команды выполняются по существующему приватному доступу. Сначала read-only,
потом решение и минимальная правка у правильного владельца. Не публиковать raw
журналы соединений, request bodies, usernames, credentials и IP пользователей.
Короткое окно/агрегированные counts предпочтительнее полного `kubectl logs`.

## 1. NEW не отвечает снаружи

- Сверь фактическое назначение IP на VPS, route/source, listener (`ss`) и
  источник persistent network configuration. Если адрес не назначен — это
  provider stage, не ошибка приложения. Не угадывай gateway и netmask.
- Сравни TCP из home/mobile/независимых сетей и с самого VPS. Self-hairpin
  проверяет процесс, но не внешний вход. Ping проверяет другой протокол.
- Короткий bounded capture на external interface: счётчики входящих SYN и
  исходящих SYN-ACK, без payload/вывода raw client addresses. SYN не дошёл —
  исследуй upstream/path; дошёл, нет ответа — local firewall/listener/routing.
  SYN-ACK ушёл без ACK — возможен обратный путь; это ещё не доказательство ТСПУ.
- Смотри counters точных правил nft/iptables, kube-proxy и policy owners.
  `ufw inactive` не означает отсутствие nft/iptables. Не flush, не accept-all.
- Если доступ различается по сетям, записать региональный/path-specific отказ.
  Смена порта — отдельный согласованный тест, сервер тоже должен его слушать.

## 2. TLS устанавливается, HTTPS затем зависает

- Это не TCP-блокировка IP. Сверь ingress route, Service/EndpointSlice, backend
  Ready и прямой внутренний запрос. Доступен ли backend site по mesh?
- Проверяй runtime + persistent WireGuard endpoints, handshake ages и counters
  обеих сторон. После смены IP один node может работать через ещё живой канал,
  а worker с приложением — обращаться к OLD.
- Проверь TCP transport bind на VPS и destination на client, guard counters,
  затем только relevant backend route. Не restart весь Kubernetes для mesh.
- При проблемах только с большими ответами исследуй MTU/MSS и retransmits;
  не меняй MTU всех узлов по одному timeout без подтверждения.

## 3. DNS ведёт не туда / разные резолверы дают разные ответы

- Отдельно сравни `/etc/hosts`/getent, configured resolver, оба child authorities,
  parent glue, Google/Cloudflare DoH. У getent может быть локальный override.
- Обычный `dig @8.8.8.8` из home может перехватываться. Флаг aa/необычный TTL
  и несогласованность с DoH — повод проверить другой vantage, не «пропагацию».
- Самостоятельный health-based renderer на двух сторонах при partition может
  публиковать разные A. Выясни, какой probe и почему failed; это не повод
  механически закрепить домашний IP всем именам, особенно non-HTTP transports.
- Child A NEW при parent glue OLD — незавершённая registrar stage. Parent NEW
  при recursive OLD — уже кеш; зафиксируй TTL. Не отключать второй NS наугад.

## 4. VPN-клиент «подключён», но трафика нет

- Статус приложения не доказывает tunnel delivery. Проверь выбранный профиль,
  literal destination после refresh, protocol/port, SNI/WS path и срок/лимит
  конкретного клиента, не раскрывая identifiers/credential в отчёте.
- Сравни другой сайт, Wi-Fi/mobile и Global vs rules режим. Это диагностический
  тест, не разрешение менять политику клиента постоянно без пользователя.
- Отдельно проверь VPS egress и authenticated external tunnel. Работает только
  egress — ещё не исправен tunnel. Работает один Trojan — не доказан VLESS/WG.
- Подписки OLD после host apply: все таблицы current DB, `hosts.address`, источники
  share address/host mappings и actual path mounted DB. Одна только строка
  settings/inbounds не покрывает hosts. Не делать второй restart вслепую.
- После SQL address migration проверь exact invariants, потом точный panel reload
  и полную выдачу plain/JSON. Если NEW только в файле, а клиент старый — refresh
  subscription или ручной endpoint, не перевыпуск всех credentials.

## 5. Сайт открывается, но вход/бот/объектное хранилище ломается

- HTTP 200 может быть только login page. Сверь ожидаемый auth redirect host/path,
  затем доступ приложения к Authentik/token endpoint и policy egress.
- У RustFS отдельные NetworkPolicies storage и identity gateway. Старый /32 в
  одной из них может ломать callback, даже когда публичная страница доступна.
- Telegram webhook URL и pinned IP — разные вещи. `getWebhookInfo` с VPS,
  pending count, age последнего error; запрос с home может сам блокироваться.
  Не повторять публикацию/операцию с побочным эффектом ради health check.
- NetBird advertised URI может оставаться OLD в Secret, хотя listener новый.
  Перечитай effective config и lifecycle, не меняй node identities/ACL.

## 6. Красный светофор при работающем новом входе

- Проверяй instance у свежего `probe_success`, job owner и age sample. Старый
  target в saved Collector bundle не меняется от одного ServiceMonitor.
- Если NEW=1, но firing OLD остаётся — проверь last sample/rule evaluation и
  lookback expiry. Не удалять старую серию ради цвета. Не выдавать stale data
  за успешную текущую проверку.
- Collector failures/queue growth — stop gate. Сравни delta по exporter/pipeline,
  а не только суммарную queue (сайзер может быть bytes vs requests). Ресурсный
  отказ и синтаксическая transform ошибка — разные причины; память не повышать
  без evidence. Исследовать безопасные классы ошибок, не raw bodies.

## 7. Ошибка playbook / schema drift

- Сохрани stdout counts + private receipt; **не повторять apply автоматически**.
  Определи, какие source/files/DB уже изменены и какие native units не перечитаны.
- Не исправлять unknown schema общим SQL replace всех TEXT колонок. Найти
  поддерживаемый owner/API или обновить allowlist/инварианты отдельным review.
- Не восстанавливать старую целую БД поверх новых live данных. Preimage нужна
  для сравнения/точечного recovery, а не разрешение терять новые записи.
- После ручного восстановления сохранить evidence и исходный receipt, явно
  отметить согласованное состояние и только затем снова audit.

## 8. SSH alias не работает после переезда

Обычные `socrat-N` должны подключаться к private mesh IP, без `ProxyJump` и
публичного SSH. Не выдавать переключение alias на домашний IP/VPS public за
исправление внутренней сети. Recovery alias допускается только как временный
канал управления во время диагностики.

Сверить `ssh -G`, host routes Mac, активный **импортированный** WireGuard profile,
актуальность VPS endpoint и покрытие worker `10.250.0.5/32`. Проверить обратный
peer route и узкий forwarding ACL. Исправлять VPN под source ownership, не
создавать ещё один SSH bastion. Подробности и критерии:
`docs/mac-private-ssh.md`; для Mac → worker нужны прямой внутренний SSH и
сохранение source `10.250.0.4` без SNAT.
