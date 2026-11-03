# NetBird: STUN и machine peers в существующем Kubernetes

## Результат live-этапа 2026-11-02

Это продолжение `d6cf22b`, **не заявление об успешном пользовательском VPN**.
Management/Dashboard остаются на socrat-0, один SQLite writer, без HA.
TLS/OIDC-only на `netbird.socrat.alchemmist.xyz` сохранены, `localAuthDisabled=true`.
После изменения повторно прошёл независимый relay nonce в обе стороны через
два TLS entrance. Generic `/health` combined v0.82.0 не исправлялся и не
подменялся «healthy»: management readiness и relay payload — отдельные проверки.

**STUN действительно работает:** `stun:176.98.185.59:3478` (UDP).
Не использовать management FQDN как STUN hostname: у него два entrance, а
`109.173.40.247:3478` не отвечает. Home NAT/router не менялись.

До записи проверены точные Kubernetes ресурсы, Services/externalIPs и UDP
listeners на обоих узлах: конфликта 3478 не было, существующий WG51830 сохранён.
Свежий quiesced encrypted backup SQLite + Kubernetes/runtime configuration
создан и расшифровкой проверен в **закрытом** remote journal. PAT/ключи/Secrets
не копировались в git и не выводились.

### Почему не обычный externalIPs Service

1. Новый `netbird-pilot/stun-public`, UDP3478, externalIP176.98.185.59 с endpoint
   combined server на socrat-0 дал корректную STUN transaction, но
   **XOR-MAPPED-ADDRESS=10.42.0.0**. Межузловой kube-proxy SNAT делает такой
   ответ бесполезным для обнаружения NAT. Это был отказ теста, не STUN acceptance.
2. STUN-only coturn pod на socrat-2 + `externalTrafficPolicy: Local` исправил
   внешнего клиента, но запрос с самого socrat-0 всё ещё получал **10.42.2.0**:
   kube-proxy отдельно направляет locally-originated externalIPs через cluster
   chain. Только Local не устраняет host hairpin.
3. По согласованному уточнению размещения на **существующем socrat-2** оставлен
   один `Deployment/netbird-pilot/stun` с `hostNetwork:true`, listener строго
   **176.98.185.59:3478/UDP**. Свои Service и additive NetworkPolicy удалены
   с DELETE preconditions по точным UID/resourceVersion. Никаких изменений
   глобального kube-proxy, host firewall, WG, NAT/router или новых машин.

Рендерер: `scripts/netbird-stun.py`, официальный `coturn/coturn:4.7.0` с
immutable index digest в `deploy/netbird/images.lock.json`. Manifest SHA256
сравнен с `Docker-Content-Digest`; это integrity pin, не publisher signature.
Контейнер nonroot65534, без hostPID/rootfs mounts/SA token, read-only rootfs,
32Mi memory cap, 100m CPU cap, requests8Mi/5m, tmpfs<=1Mi, одна relay thread.
`--stun-only --no-tcp --no-tls --no-dtls --no-cli`, нет TURN/admin/web/debug
публикации. `--stun-only` игнорирует TURN requests; `--no-auth` относится
здесь к публичным Binding, **не к разрешению TURN**. RFC5780 не включён.
Официальный `/usr/bin/turnserver` содержит file capability NET_BIND_SERVICE:
при dropALL без этого bounding bit exec дал EPERM, поэтому оставлен только
NET_BIND_SERVICE, хотя сам порт3478 непривилегированный. blanket privileged
не использован. Начальный неработавший pod заменён; финальный pod — 0 restarts.

В private runtime `netbird-runtime` добавлено **только**:

```yaml
server:
  stuns:
    - uri: stun:176.98.185.59:3478
      proto: udp
```

Это **дельта, не полный Secret/config для apply**. `combined/cmd/config.go`
v0.82.0: `ApplySimplifiedDefaults`, `applyRelayDefaults`,
`autoConfigureClientSettings` — nonempty `server.stuns` отключает local STUN
и публикует ровно этот список. Поэтому Service на combined server более не нужен.
Чтение Secret после guarded replace подтвердило отсутствие других изменений.

### Реальные проверки, не только UDP socket

`scripts/netbird-stun-check.py` проверяет source endpoint, response type/length,
magic cookie, точный случайный transaction ID, XOR-MAPPED IPv4 и запрет TURN
Allocate. На один запуск — три UDP запроса с timeout3s, без нагрузочного теста.

| Откуда | Endpoint | Проверенный XOR-MAPPED | TURN Allocate |
|---|---|---|---|
| внешний worker | 176.98.185.59:3478 | публичный 93.158.185.136 | timeout/ignored |
| host socrat-0 | 176.98.185.59:3478 | **109.173.40.247**, exact expected | timeout/ignored |
| host socrat-2 | 176.98.185.59:3478 | **176.98.185.59**, exact expected | timeout/ignored |
| все три | 109.173.40.247:3478 | timeout, **не рекламируется** | — |

HTTPS proxy egress worker отличается от UDP egress; не сравнивать STUN с
`curl` через HTTP proxy. Для внешнего worker подтверждён публичный адрес,
независимая аттестация его egress не заявлена; два host-теста сравнивают
с заранее известными точными публичными адресами. `ss` на VPS подтвердил
UDP listener только176.98.185.59:3478, отсутствие TCP3478/5349 и UDP5349.
Существующие unrelated listeners, включая8080, не трогались.

```sh
python3 scripts/netbird-stun-check.py
# на host socrat-0:
python3 /tmp/netbird-stun-check.py --expected-source 109.173.40.247
# на host socrat-2:
python3 /tmp/netbird-stun-check.py --expected-source 176.98.185.59
```

Это не TURN relay, но публичный STUN всё равно может использоваться для
UDP reflection. CPU/memory ограничены, **packet-rate limit не установлен**:
host firewall запрещено менять в этом этапе. `max-bps`/`bps-capacity` coturn
ограничивают TURN sessions, не доказывают rate limiting Binding. Кандидат
отдельного review: source-keyed UDP3478 limit порядка30 Binding/s, burst60,
плюс общий потолок; оценить shared NAT и мониторинг, не применять вслепую.

## Более простая архитектура: два machine peer, без маршрутов

`scripts/netbird-host-peer.py` — **новый** Kubernetes renderer, не Docker/systemd
`netbird-host-router.py`. Legacy router/Network-планы остаются историческими и
не используются для этого этапа.

- socrat-0 и socrat-2 — обычные machine peers со **своими** overlay адресами.
- Не нужен маршрут `10.250.0.2/32` через socrat-0, нет маршрутизации собственного
  хоста, SNAT/FORWARD, exit node, fake route HA или импортов маршрутов.
- Оба агента: `NB_DISABLE_CLIENT_ROUTES=true`, `NB_DISABLE_SERVER_ROUTES=true`,
  `NB_DISABLE_DNS=true`, отдельный `nb-host`/UDP51871 (проверить конфликт перед
  активацией), NetBird SSH выключен. Native OpenSSH socrat-2 уже слушает2222.
- Собственный overlay socrat-2:2222 — **INPUT**, который фильтрует NetBird agent.
  Source v0.82.0 `client/firewall/iptables/chains_linux.go` и
  `client/firewall/nftables/chains_linux.go` привязывает INPUT ACL к peer iface.
  Не добавлять глобальные SSH accept/drop, не менять public/recovery SSH.
- Только group-based directed TCP policies:
  JWT `netbird-pilot-grafana` → API destination `netbird-machine-grafana`,8443;
  JWT `netbird-pilot-ssh-socrat-2` → API destination
  `netbird-machine-ssh-socrat-2` (только peer socrat-2),2222.
  `All`, protocol all, bidirectional grants и route/Network resources не нужны.
  Grafana destination может содержать socrat-0 и позднее socrat-2 с отдельными
  frontend listener — это не HA маршрута.

### Что подготовлено, а что НЕ установлено

Renderer выдаёт отдельный namespace `netbird-host-peers`, по PVC64Mi на host,
Recreate Deployments, pinned NetBird0.82.0, hostNetwork, **только**
NET_ADMIN/NET_RAW/BPF + CharDevice `/dev/net/tun`. Нет Docker daemon, hostPID,
privileged, host `/`, `/etc/wireguard`, SSH files или cluster API token.
State/private key хранится в PVC; Secret передаётся только через secretKeyRef.
Client image smoke-pod на socrat-0 реально выдал `0.82.0`, затем удалён; он
не подключался к management, без hostNetwork/NET_ADMIN/TUN/credentials.

**Все peer и frontend Deployments намеренно replicas=0.** Рендерер ничего
не применяет, не создаёт ключи, не вызывает API и не разрешает активацию.
Namespace/PVC/peer/frontend workloads пока не установлены. Kubernetes server
validation прошла для ресурсов с namespace, временно заменённым в dry-run на
существующий `netbird-pilot`: Kubernetes dry-run не создаёт namespace для
последующих документов. Реального apply machine resources не было.

```sh
python3 scripts/netbird-host-peer.py > /tmp/netbird-machine-stage.yaml
# frontend рендерить только с ФАКТИЧЕСКИМ адресом enrolled machine peer:
python3 scripts/netbird-host-peer.py --frontend-host socrat-0 \
  --overlay-ip 100.96.1.2 > /tmp/netbird-machine-with-frontend.yaml
# этот адрес лишь пример, НЕ фактический peer/IP
python3 scripts/netbird-host-peer.py --frontend-guard
python3 -m unittest discover -s tests -p test_netbird_host_peer.py -v
```

96Mi agent /32Mi frontend — **кандидат caps, не доказанная рабочая память**.
До STUN VPS имел557Mi available, после568Mi; actual STUN около4Mi,0 restarts.
Консервативный budget preflight: available>=417Mi
(256reserve+96agent+32frontend+32STUN+1tmp). Не считать эти цифры гарантией fit:
перед активацией повторить memory/CPU/port/interface baseline; наблюдать
cgroup memory/OOM/events/latency. Если запас<256Mi или OOM — остановить
новые workloads, не повышать limits/не менять существующие сервисы вслепую.

### Grafana frontend

TLS listener **только фактический overlay IP:8443**, не wildcard/public/WG.
Traefik использует strict SNI + сертификат для Grafana, HTTP router только
`Host(grafana.socrat.alchemmist.xyz)`, фиксирует upstream Host тем же hostname,
а upstream — **10.250.0.3:443**, serverName=Grafana, TLS verification включена.
Перед frontend пользователь предоставляет отдельный runtime TLS Secret;
рендерер не копирует TLS private key из других namespace.
Отдельный nft guard принадлежит только `table inet netbird_peer_frontend`:
DROP TCP8443 при iifname!=nb-host; нет SSH/UDP/WG/NAT/FORWARD изменений.
Перед установкой: убедиться, что таблицы ещё нет, проверить `nft -c`, затем
установить через отдельно разрешённый NET_ADMIN путь; renderer сам guard
не применяет. **Frontend не включать без реальной проверки этого guard**,
SNI/Host negative tests, allow/deny peer ACL и direct-public negative test.

Upstream был проверен настоящим trusted TLS c SNI/Host Grafana через
10.250.0.3:443: HTTP200, `<title>Grafana</title>`. Public Kubernetes Ingress
Grafana не найден; его не создавали и не меняли. Отдельная private path
работает независимо от публикации NetBird frontend.

## Блокирующий человеческий шаг и безопасный порядок продолжения

Readonly native owner-handover проверен один раз: точного owner subject ещё
нет, **OIDC users0**. API показывает только `All(issued=api)`, JWT source groups
отсутствуют, **policies0 / peers0 / setup-keys0**. Поэтому enrollment и grants
**НЕ выполнялись**. Владелец должен лично пройти реальный OIDC login, не
имперсонация, password/MFA reset, создание человека или email merge.
Только утверждённый exact UUID+connector может проходить отдельный native
handover; эта стадия никого не повышала и owner роль не передавала.

После настоящего login:

1. Read-only сверить owner subject и обе source groups `issued=jwt`. Не создавать
   одноимённые API groups и не переписывать JWT source membership вручную.
2. Fresh encrypted backup; перечитать **policies=[]**, peers/groups/setupkeys,
   безопасный membership и свежие CPU/memory/ports/TUN/interface/netfilter
   baselines. `preflight()` fail-closed при неожиданном peer/group/state;
   это helper для live read, а не «бумажное» разрешение apply.
3. По одному создать native API `type=one-off, usage_limit=1, expires_in=600,
   auto_groups=[], ephemeral=false` ключу на host. Ключ хранить только в private
   journal0700/files0600 и Kubernetes Secret, не argv/вывод/репозиторий.
4. Activate только один агент, без policies; сверить identity, реальный overlay,
   agent default-deny и отсутствие client/server route imports. Проверить OOM.
   Удалить/отозвать enrollment Secret/key по отдельному плану restart: entrypoint
   запускает `netbird up` при restart, PVC identity необходимо сохранить.
5. Создать только dedicated destination groups с точными peer IDs; перечитать
   memberships, затем точные два TCP policy bodies из `policies()`; нет All.
6. Frontend только после actual IP/TLS secret/guard; проверить positive/negative
   JWT group access, wrong Host/SNI, direct public denial, отдельный SSH login
   пользовательским private key (существующие SSH keys/config неизменны).
   Только после этих тестов можно принять пользовательский VPN.

### Rollback текущего STUN этапа

Перед rollback перепроверить resource UID/owner и свежий snapshot. Вернуть
**только** предыдущее содержимое `netbird-runtime` из private
`journal/stage5-runtime-secret-before.json` guarded replace с актуальной
resourceVersion, перезапустить одиночный server, проверить OIDC/readiness/relay.
Так вернётся исходная FQDN-STUN конфигурация, **не рабочий внешний STUN**.
Удалить только собственный `Deployment/netbird-pilot/stun` по UID precondition.
Удалённых `stun-public`/`allow-stun-binding` уже нет; не создавать их обратно.
Не удалять существующие management PVC/Secrets, не менять WG/SSH/firewall.
Будущие peer/frontend откатывать отдельно; их PVC с identity не удалять
автоматически, nft guard удалять только собственную таблицу после остановки
frontend, API policies/peer revocation — по точным созданным ID.
