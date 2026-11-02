# NetBird: пилот пользовательского доступа (не транспорт кластера)

**Статус на 2026-11-02: исходники подготовлены; развёртывание BLOCKED.**
Ни один NetBird-компонент не установлен, политики/IdP/DNS/маршруты не изменены.
Это не отчёт об успешной production acceptance. Основа: чистый `f976677`.
Нет Application в Argo CD, автоматической синхронизации, Ansible deployment playbook,
API apply или автоматического создания пользователей. Скрипты компилируют локальные
артефакты; `verify-images` читает только публичный registry.

## Границы и архитектура

- `wg-socrat`, адреса `10.250.0.1/3/2/5`, ключи, AllowedIPs, Flannel/K3s,
  WG TCP transport, существующие recovery SSH и пользовательский VPN не трогаем.
- Пользовательский NetBird overlay имеет **отдельный, проверенный на пересечения CIDR**.
  Нет exit node, маршрутов `/0`, LAN `/24`, pod/service CIDR или all-to-all.
- Community combined server (Management + Signal + Relay + STUN) — **один экземпляр**,
  SQLite/PVC, `Recreate`, закрепление на выбранной ноде. Dashboard тоже один.
  Это SPOF; PVC local-path не превращается в HA при пересоздании pod.
- **Ровно два routing peer на новых выделенных Linux VM/хостах**, не на socrat-0…3.
  Host networking/NET_ADMIN/SYS_ADMIN/SYS_RESOURCE разрешены только внутри этих VM.
  Интерфейс `nb-pilot0`, UDP 51840. Не устанавливать этот Compose на K3s-ноды!
  Каждый peer должен самостоятельно достигать **каждого** выбранного backend.
  Две VM на разных физических хостах одной LAN защищают от отказа VM/хоста,
  но не от отказа домашнего роутера, питания, коммутатора или WAN.
- Используем **Networks**, не legacy Network Routes: deny по умолчанию, ресурсы
  только IPv4 `/32`, TCP 443 (web) и TCP 2222 (существующий OpenSSH).
  Отдельная destination group на каждый ресурс, source groups только из JWT.
  К routing peer самому нет input/peer-to-peer allow policy. Не размещать backend
  на самом routing peer — иначе нужны другие input-chain правила, которых здесь нет.
- Один Network с двумя индивидуальными routers, разными metrics (например,
  primary/standby; значения вводит оператор), masquerade=true. Обратные маршруты
  на существующих узлах не меняются. Все target ACL должны принимать SNAT-адрес
  **обоих** routers. Сетевая идентичность не заменяет приложение/SSH IAM.
- **NetBird SSH отключён**. Не меняем SSH accounts, authorized_keys, сертификаты
  SSH, настройки приложений, их роли, SSO/outpost или MFA. Существующий OpenSSH
  проверяет старые host keys и ключи пользователя. Доступ к login-странице не означает
  доступ к приложению без его авторизации.

### Важная граница L3/L4 для web

Разрешение `IP:443` разрешает все virtual hosts на этом listener. Ни FQDN в документации,
ни доменный resource NetBird не являются SNI/HTTP ACL. **Нельзя просто разрешить общий
Traefik VIP**, если на нём есть невыбранные приложения. До пилота нужен выделенный
IP/listener для выбранных сервисов либо отдельный default-deny frontend с allowlist
Host/SNI, запретом IP/default-vhost/прочих SNI. Такой frontend сейчас не обнаружен,
его адреса не выдуманы; это deployment blocker. `endpoint_ip_port_scope_reviewed=true`
означает именно проверку этой границы, а не формальное согласование списка URL.

## Что действительно проверено read-only

SSH существующими ключами/алиасами, без TOFU/отключения HostKey checking:

```sh
ssh -o BatchMode=yes -o HostName=109.173.40.247 \
  -o 'HostKeyAlias=[socrat.alchemmist.xyz]:2222' socrat-0 'hostname; ip -4 route'
# socrat-1: тот же override, HostKeyAlias [socrat.alchemmist.xyz]:2223
ssh -o BatchMode=yes socrat-2-direct 'hostname; ip -4 route'
```

Наблюдались socrat-0 LAN `192.168.0.23`, WG `10.250.0.1`; socrat-1 LAN
`192.168.0.24`, WG `10.250.0.3`, дополнительный `192.168.0.250/32`; VPS socrat-2
`176.98.185.59`, WG `10.250.0.2`. Pod routes `10.42.0.0/16` уже используют Flannel.
На VPS есть host routes к `.23/.24` через WG; это **не** разрешение расширять mesh.
На socrat-0 `sudo -n wg …` и `sudo -n kubectl …` отказаны (нужен пароль).
Поэтому актуальные AllowedIPs/handshakes, firewall, pod readiness, ingress и все
прикладные listeners **не подтверждены** этим обследованием. Секреты не читались.
`109.173.40.247` — override только для обследования SSH, не утверждение о новом DNS,
Ingress или STUN endpoint. Существующий Authentik FQDN взят из repo values, доступность
с внешнего клиента в этой работе не проверена.

## Release, security, license: официальные источники

Проверены 2026-11-02, повторить перед утверждением deployment:

| Источник | Результат |
|---|---|
| [Latest release API](https://api.github.com/repos/netbirdio/netbird/releases/latest), [v0.82.0](https://github.com/netbirdio/netbird/releases/tag/v0.82.0) | Latest stable v0.82.0, опубликован 2026-10-29; dashboard v2.96.0 |
| [Security advisories](https://github.com/netbirdio/netbird/security/advisories), [API](https://api.github.com/repos/netbirdio/netbird/security-advisories) | На момент запроса опубликовано 9 advisories, перечислены ниже; v0.82.0 выше всех опубликованных fixed versions, **не** гарантия отсутствия неизвестных уязвимостей |
| [LICENSE v0.82.0](https://github.com/netbirdio/netbird/blob/v0.82.0/LICENSE) | BSD-3-Clause вне management/signal/relay/combined; эти server-каталоги AGPLv3; [dashboard v2.96.0](https://github.com/netbirdio/dashboard/blob/v2.96.0/LICENSE) AGPLv3 |
| [HA](https://docs.netbird.io/selfhosted/maintenance/scaling/high-availability) | Active-active Management и Signal — **Enterprise commercial license**, не бесплатное Community HA |
| [IdP](https://docs.netbird.io/selfhosted/identity-providers), [Authentik](https://docs.netbird.io/selfhosted/identity-providers/authentik) | Embedded IdP + внешний Authentik OIDC, JWT group sync; SCIM отсутствует в open-source Community, предлагается Cloud/Commercial |
| [Routing peers](https://docs.netbird.io/manage/networks/how-routing-peers-work) | Multiple routing peers/failover — отдельная data-plane функция; не лицензия на HA Management/Signal |

Advisories: GHSA-28q5-j9qm-gx35 (daemon file read, fixed 0.76.1),
GHSA-xmg2-v32j-x2hf (SSH Match injection, 0.74.7), GHSA-v5w2-pqxj-6r94
(relay unauthenticated gob, 0.75.0), GHSA-7wwh-vfq4-v488 (SOCKS bind, 0.74.7),
GHSA-jxxc-7jxf-v8hm (SSH dependency, 0.74.4), GHSA-fhw6-5mff-2gfh
(relay WebSocket DoS, 0.68.0), GHSA-qcpp-8vwj-hhwr (IPC privilege escalation,
0.76.0), GHSA-rxmp-8h9v-56cx (admin→owner escalation, 0.65.3),
GHSA-4g2w-p87c-hxch (Windows MSI repair escalation, 0.49.0).
Release 0.82.0 дополнительно исправляет SSH root aliases/env handling, proxy account
validation и masking URL credentials. Не включать ненужные SSH/SOCKS/proxy функции.
Client daemon socket — локальная привилегированная поверхность; не публиковать его
и не монтировать в обычные приложения. До production отдельно проверить SBOM/CVE
для образов и пользовательских installer packages, security advisories dashboard,
поддерживаемые платформы и возможность security обновления после пилота.

AGPL не запрещает внутреннее использование; при модификации сетевого server-компонента
есть обязательства по предоставлению соответствующего исходного кода его пользователям.
Юридическое согласование перед внешним сервисом/дистрибуцией; это не юридическое заключение.
**Не масштабировать Community replicas до 2** и не обещать transparent management failover.
Enterprise HA требует отдельного проекта с лицензией, PostgreSQL HA, Redis, NATS,
LB и отдельными relay endpoints. Пилот этого не реализует.

### Верифицируемые pins

`deploy/netbird/images.lock.json`: index digest и Linux amd64/arm64 manifest digests,
из Docker Hub Registry v2. Воспроизводимая проверка сравнивает header
`Docker-Content-Digest`, SHA256 **самих bytes** index и platform entries:

```sh
/tmp/homelab-iam-tests/bin/python scripts/netbird-pilot.py verify-images
```

В manifests/Compose используется `repository:tag@sha256:…`, не `latest`.
Это integrity pin, **не** проверка подписи издателя. Перед production проверить
происхождение/подписи по доступному механизму издателя и утвердить конкретные digests.
Upstream installer использован только как reference, **не запускался** и не должен
запускаться через `curl | sh`. URLs/SHA256 reference files и docs commit зафиксированы
в `upstream.lock.json` (docs commit `f9fcde283a90733c38f701f1def05a6db68ebeb0`).

## Точные недостающие входы / prerequisites

`deploy/netbird/pilot.inputs.json` намеренно не deployable. Заполнить в отдельном
reviewed локальном файле (не подставлять тестовые fixtures):

1. `management_fqdn`: утверждённый публичный FQDN, A/AAAA, внешний TCP 443,
   TLS secret/certificate (`tls_secret_name`, namespace `netbird-pilot`), renewal,
   `ingress_class`, Traefik CRD/HTTP2 h2c/WebSocket forwarding. Не направлять неработающий AAAA.
   **Repo `charts/traefik-edge/values.yaml` сейчас не watches `netbird-pilot`, а CRD
   provider ограничен namespace `argocd` и edge-transport label selector.** Поэтому
   отрендеренный IngressRoute сам по себе не создаёт публичный endpoint. Нужен отдельный
   reviewed ingress plan: выделенный controller с точным namespace/class scope либо
   узкое расширение текущего scope без отключения guardrails для остальных CRD.
   Автоматическое изменение существующего edge в этот commit намеренно не включено.
   Bootstrap Authentik и Management/Dashboard **доступен до установки VPN**.
   Private-only Authentik/Management создаёт circular bootstrap и запрещён.
2. `management_node`, `storage_class`: реальная нода, свободные CPU/RAM/disk,
   storage locality, PVC backup/restore, release-compatible K3s/Traefik. `stun_node_port`:
   свободный UDP NodePort, внешний UDP **3478 → выбранная нода:NodePort**, firewall/NAT,
   сохранение mapping после restart, внешний STUN test. Другим нодам этот NodePort
   не forward-ить: `externalTrafficPolicy=Local`.
3. `overlay_cidr`: отдельный IPv4 `/16…/24`; проверить все routes клиента, LAN,
   CGNAT, другие VPN, Docker, Kubernetes. Встроенный запрет известных CIDR — не полная
   inventory проверка. Настроить account range **до** enrollment любых peers.
4. `routing_peers`: ровно два `{name, host, failure_domain, metric}`. Утвердить реальные
   DNS/IP размещения, разные физические failure domains, recovery SSH/console, Linux
   kernel/netfilter/TUN/Docker Compose, endpoint reachability, target SNAT/firewall,
   независимый путь обоих peers. Не переносить эти функции на существующие узлы.
5. `oidc_client_id`, подтверждённый `authentik_issuer` (предзаполнен только repo-based
   candidate slug), `login_group`; точные source group names, pilot users/devices,
   owner/break-glass custody. Клиентский secret и setup keys — **не входной JSON**.
6. `resources`: `{name, kind, address, ports, source_group, dns_name}` для каждого
   утверждённого private `/32`, web `[443]`, ssh `[2222]`. Список пока пуст:
   **не выбраны приложения, backend IP/listeners, SSH hosts и их группы**.
   Нужны DNS records/split-DNS и TLS/SNI для выбранных FQDN без public wildcard fallback.
   IP должен быть достижим с обеих VM; не app/pod ephemeral IP. Общий ingress VIP
   без отдельного сетевого барьера запрещён (см. выше).
7. Все шесть `review` gates должны явно стать `true` после фактической проверки.
   Нужны ответственные/окно изменений, вне-VPN recovery, SLA failover/revocation,
   rollback, внешний тестовый клиент и второй контрольный непривилегированный клиент.

Дополнительно после initial control-plane setup нужны реальные IDs `network_id`,
`source_groups`, `resource_groups`, `peer_ids`, свежий read-only API snapshot и
независимый diff review. Генератор **не угадывает** API IDs, DNS, IP или credentials.

## Воспроизводимая подготовка, без production writes

```sh
PY=/tmp/homelab-iam-tests/bin/python
$PY -m unittest discover -s tests -p 'test_netbird_pilot.py' -v
$PY scripts/netbird-pilot.py validate             # ожидаемый BLOCKED с repo inputs
# После заполнения /protected/pilot.inputs.json:
$PY scripts/netbird-pilot.py validate --inputs /protected/pilot.inputs.json
$PY scripts/netbird-pilot.py render --inputs /protected/pilot.inputs.json --out /tmp/netbird-reviewed
```

Выходной каталог не должен существовать. Результат: management Kubernetes YAML,
два отдельных router Compose, account settings **merge fragment**, OIDC public fields,
access intent. Это не Argo application и не команда apply. Файлы не содержат секретов.
Не помещать rendered каталог в `deploy/argocd/apps` или watched Argo source.

Дополнительная upstream contract проверка (опционально нужен `jsonschema` в test venv):

```sh
curl -fsSL https://raw.githubusercontent.com/netbirdio/netbird/v0.82.0/shared/management/http/api/openapi.yml \
  -o /tmp/netbird-v082-openapi.yml
NETBIRD_OPENAPI_FILE=/tmp/netbird-v082-openapi.yml $PY -m unittest discover -s tests -p 'test_netbird_pilot.py' -v
```

Тест проверит SHA256 против lock и JSON request bodies по официальным schemas.
Успешный schema/unit test не доказывает runtime семантику IdP/маршрутов.

### Фактически выполненная проверка исходников (2026-11-02)

- 17 новых tests PASS в `/tmp/homelab-iam-tests`, включая optional pinned upstream
  OpenAPI contract test; без `NETBIRD_OPENAPI_FILE` этот один тест явно SKIP.
- Digest verification трёх images PASS (index bytes + amd64/arm64 manifests).
- Отрендеренные **синтетические test fixtures**, не production: семь объектов core
  Kubernetes прошли strict JSON schemas v1.34.0; IngressRoute — официальный CRD schema
  Traefik v3.5; оба Compose прошли `docker-compose config -q` и Compose schema.
  Это не server-side dry-run целевого кластера и не запуск контейнеров.
- Существующие Authentik tests: 30 PASS; identity tests: 14 PASS.
- Существующий WireGuard suite: 28 tests, 26 PASS, **2 baseline failures** в
  `test_wireguard_admin_client`: `test_profile_does_not_capture_dns` (template уже
  содержит условный DNS) и `test_dns_is_privileged_and_scoped_to_dns_tag` (ожидается
  ≥4 `become: true`, в baseline 2). Эти tests/шаблоны/roles не изменены пилотом;
  их исправление не включено в узкий commit. Первоначально отсутствовавший `jinja2`
  добавлен только в test venv, после чего suite повторён без import errors.
- Default `validate/render` намеренно BLOCKED до filesystem output. Live probes,
  actual NetBird runtime config parsing, IdP login, failover, revocation, restart,
  restore и production acceptance **не выполнялись**.

## Только после явного reviewed deployment approval

Следующие шаги — **план будущих production writes**, в этой работе не выполнялись.

1. Снять защищённый baseline `ip addr/route/rule`, WG public peer IDs/AllowedIPs/
   handshakes (никогда `wg showconf`/`wg … dump` с private key), firewall, Node Ready,
   cross-node pod/DNS, ingress/SSH probes. Проверить console/public recovery и backup.
   Не сохранять эти данные в Git. Вне VPN убедиться в DNS/TLS Authentik и нового edge.
2. Защитить first-owner bootstrap: временный edge source-IP allowlist оператора или
   authenticated administrative tunnel до initial setup. Нельзя открыть незанятый
   `/api/setup` всем и ждать, пока настоящий owner успеет первым. Сначала namespace,
   TLS secret/cert и runtime config; затем отревьюенный singleton manifest.
3. Runtime secret injection: secret manager выдаёт **разные** `NB_RELAY_SECRET`
   (не менее 32 случайных символов), `NB_COOKIE_KEY`, `NB_STORE_KEY` (оба base64 от
   32 random bytes). Не печатать/передавать значения CLI arguments, Git, shell history,
   CI logs, `set -x`, env dumps. Запускать от доверенного оператора в защищённом
   процессе; `runtime-config` пишет новый файл 0600 и не следует symlink:

   ```sh
   # Переменные уже инжектированы secret manager; здесь НЕТ их значений.
   $PY scripts/netbird-pilot.py runtime-config --inputs /protected/pilot.inputs.json \
     --out /run/user/"$(id -u)"/netbird-config.yaml
   # Только после approval; runtime file находится на tmpfs, не в repo:
   kubectl -n netbird-pilot create secret generic netbird-runtime \
     --from-file=config.yaml=/run/user/"$(id -u)"/netbird-config.yaml
   ```

   Команда предполагает уже созданный namespace. Удалить временный файл после injection,
   убрать env из сессии; Secret шифровать в etcd/backup, ограничить RBAC. Сохранять
   encryption/cookie keys вместе с encrypted backup — не генерировать заново при restore.
   Secrets отсутствуют → server не запускается; не создавать placeholder Secret.
4. Первым owner через защищённый initial setup создать только pilot account.
   **Сразу удалить Default allow-all policy и любые legacy Routes, до enrollment**.
   Установить account settings merge fragment через read-modify-write текущего account,
   сохранив unrelated settings. Не считать fragment полным PUT account body.
   Никакого canary или routing peer до проверки deny-by-default/overlay range.
5. Authentik: отдельные OAuth2 confidential provider/application для NetBird pilot;
   оставить существующие app providers/bindings/SSH IAM без изменений. Применить
   отдельную group application binding (deny для посторонних), существующую MFA policy,
   signing key. Issuer — точный application issuer с завершающим `/`.
   В NetBird Settings → Identity Providers выбрать Generic OIDC, runtime client secret,
   скопировать **реальный Redirect URL из UI** в Authentik как Strict; не угадывать
   callback, не regex/wildcard. Опциональный strict logout callback брать из UI/docs.
   Dashboard использует embedded issuer `/oauth2`; Authentik — upstream connector,
   не подменять dashboard authority на Authentik.
6. Проверить profile/groups scope mappings и `Include claims in id_token`.
   Если стандартный profile не выдаёт корректный array group names, отдельный mapping
   для NetBird, например filtered allowlist `{"groups": [g.name for g in request.user.ak_groups.all() if g.name in APPROVED_NAMES]}`
   (APPROVED_NAMES заменить reviewed значениями). В UI выбрать существующие scopes
   `openid profile email groups` при наличии mapping; проверить реальные access token
   claims, а не только id_token. Не логировать сами токены. Если embedded connector
   не переносит groups в выдаваемый NetBird access JWT — **STOP**, доступ не открывать.
   JWT group sync=`groups`, propagation=true, JWT allow groups=`login_group`.
   Проверить owner входит в login group до сохранения allowlist (иначе lockout).
   Source groups **создаются sync из JWT**, не вручную с совпадающим именем:
   совпадающая API-created группа не становится автоматически JWT-synced.
7. Только после deny/account settings: зарегистрировать две VM разными single-use
   setup keys, usage_limit=1, short expiration, auto-group только routers, не user
   access groups; revoke setup keys после enrollment. Файл setup key 0400/0600 из
   secret manager, `NETBIRD_SETUP_KEY_FILE` указывает на него; Compose монтирует file
   secret и использует `NB_SETUP_KEY_FILE`, без значения в environment/arguments.
   Сначала проверить `docker compose config -q`/`docker-compose … config -q` с runtime
   file path (не печатать полный config). Проверить reconnect после key expiry с
   сохранённым state volume; router keys не должны создавать ephemeral peers. State
   volume содержит private identity: backup защищать, не клонировать одну identity
   на обе VM. Для canary установить проверенный клиент **0.82.0**, не `latest`,
   на отдельное внешнее устройство без одновременно активного административного WG
   (иначе /32 resource routes могут перехватить путь recovery). После approval:
   `netbird up --management-url "https://$REVIEWED_MANAGEMENT_FQDN" --allow-server-ssh=false --disable-dns`.
   Это сохраняет системный DNS; selected names должны разрешаться утверждёнными
   public-private-A или split records до enrollment. Единичный пользовательский canary
   может войти для materialization JWT groups, пока политик **ноль**: доступа к ресурсам нет.
8. Создать **пустой** Network `netbird-pilot` и пустые API destination groups
   `pilot-resource-<resource.name>` (без peers/resources). Собрать в защищённый local
   JSON snapshot ответы GET `/api/policies`, `/api/routes`, `/api/groups`, `/api/peers`,
   `/api/networks` как keys `policies`, `routes`, `groups`, `peers`, `networks`.
   Токен API read-only на чтение, не печатать auth headers; snapshot может содержать PII.
   Bindings JSON имеет keys `network_id`, `source_groups` (имя→ID), `resource_groups`
   (resource.name→ID), `peer_ids` (router.name→ID). Затем:

   ```sh
   $PY scripts/netbird-pilot.py compile-access --inputs /protected/pilot.inputs.json \
     --bindings /protected/bindings.json --snapshot /protected/snapshot.json \
     --out /protected/access-requests.json
   ```

   Компилятор требует отсутствие **всех** policies/legacy routes, отдельный Network,
   JWT source groups, пустые destination groups, две distinct router IDs. Выход —
   упорядоченный список API requests, **не auto apply и не idempotent reconciler**.
   Перед ручным выполнением повторить свежий snapshot/diff; stale snapshot не защита
   от concurrent writes. Проверить Network ещё без ресурсов/routers. POST двух routers,
   затем resources и narrow policies, без Default policy. Повторный POST создаёт
   дубликаты — после частичного сбоя сначала inventory/reconcile вручную, не replay.
9. Проверить независимую reachability обоих routers, клиентский split DNS/выбранные
   FQDN и отсутствие изменения unrelated DNS. Не выдавать клиенту весь management
   subnet ради DNS; точные публичные private A records или reviewed local split records
   не требуют маршрута к `10.250.0.0/24:53`. Если нужен отдельный DNS backend, текущий
   allowlist его **не разрешает**: отдельное review/schema extension, не обход запрета.
10. Ручной change review и dry-run/schema validation на целевой версии API/CRD,
    затем один canary. Не включать остальных до acceptance ниже.

## Acceptance: авторские checks, фактически НЕ выполнены

Сохранять UTC timestamps, client/server versions, commit/input hash, topology,
результаты и chosen routing peer ID; не токены/пароли/config backups. Все fault injections
— только на новых VM/пилотных workload, в согласованное окно, не на WG/K3s/router production.

Read-only probe запускается **на внешнем pilot client**, не на routing peer:

```sh
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect allow --phase baseline > /protected/baseline.json
# При утверждённом отключении router-a, затем router-b (второй должен быть восстановлен):
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect allow --phase router-a-down --attempts 30 --interval 2 > /protected/router-a-down.json
# После отзыва доступа у того же пользователя, без logout/restart клиента:
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect deny --phase revoked > /protected/revoked.json
# Один заранее выбранный запретный endpoint/порт, не сканирование:
$PY scripts/netbird-pilot-probe.py --inputs /protected/pilot.inputs.json \
  --expect deny --phase negative --negative-ip "$REVIEWED_DENIED_IP" \
  --negative-port "$REVIEWED_DENIED_PORT" > /protected/negative.json
```

Probe делает новые TCP connections, web — CA/hostname-verified TLS/SNI и проверка
точного DNS A/AAAA набора против `/32`; SSH — только TCP, **не user login/host-key test**.
Для SSH отдельно выполнить обычный OpenSSH с существующими ключами/known_hosts,
`StrictHostKeyChecking=yes`, без создания пользователей или изменения authorized_keys.
Deny проверяется по прямому IP: ошибка DNS или TLS на открытом TCP **не** считается deny.
Connection refused/timeout **сам по себе** не доказывает policy deny: нужен здоровый
backend и одновременный allow probe от неотозванного контрольного пользователя.
Многократный allow probe вернёт exit 1 при любом transient failure: для failover
оценивать временной ряд/время восстановления, а не требовать нулевой потери пакетов.

| Сценарий | Критерий / необходимые доказательства |
|---|---|
| Внешний bootstrap без VPN | DNS/TLS Dashboard, Management discovery и Authentik доступны; обычные private apps без VPN недоступны; MFA/strict callback работает |
| Baseline | Selected web DNS→только утверждённый private IP, правильный CA/SNI, существующее app IAM; selected SSH host key и user login; direct/relayed status записан |
| Default deny | Посторонний user/device, peer-to-peer между пользователями, router own NetBird/LAN IP, невыбранные hosts, иные порты того же host, K3s 6443, etcd 2379/2380, Pod/Service CIDR, LAN и Internet exit не предоставлены. Unrelated интернет/DNS идут прежним путём |
| Shared IP bypass | Другой Host/SNI, IP URL, unknown/default vhost, IPv6 и альтернативный public endpoint не дают доступа к невыбранным private apps. Найден bypass → STOP |
| Каждый router отдельно | Поочерёдно изолировать **только NetBird process/VM** primary и standby. При отказе primary новые соединения восстанавливаются через standby в утверждённый SLA; клиентский `netbird status -d`, `netbird networks ls`, switch reason + counters на уцелевшем router подтверждают другой путь. При отказе standby primary продолжает работать. Затем поменять metrics в отдельном review, чтобы доказать оба направления |
| Hard failure и relay | Не только clean stop: потеря VM/NetBird network (relay может обнаруживать примерно минуту). Проверить прямой и принудительно relayed path, reconnect/roaming/sleep; не блокировать WG production. Согласовать SLA до внедрения, provisional pilot budget 120 s, измерить detection отдельно от connect |
| Failback / SNAT | После возврата lower-metric router клиент failback автоматически; masquerade меняет source, TCP/SSH могут reset. Fresh connection работает, **не обещать бесшовное сохранение SSH** |
| Оба routers down | Selected endpoints fail closed, нет fallback через public ingress/другой VPN; после восстановления снова only allowlist |
| Management/Signal/Relay outage | Отдельно выключить pilot Deployment/закрыть pilot edge. Записать: existing direct sessions могут продолжаться, новые enroll/policy/reconnect могут не работать; relay outage ломает relayed data. Это не HA acceptance. Нельзя обещать немедленный revoke при недоступной management плоскости |
| Удаление группы Authentik | С уже подключённого клиента убрать web/SSH группу; проверить новый JWT после refresh/reauth, NetBird user group и propagation на **все устройства**, обе routing ACL. Без reauth может действовать старый JWT: записать реальную задержку. Login-group removal должен запрещать новый login, но не считать это доказательством разрыва старых туннелей |
| Emergency revoke | NetBird block user + revoke/delete **всех его peers**, не только setup key/session; на живом подключённом клиенте проверить новые TCP и уже открытые web/SSH sessions через оба routers. Здоровый control-user работает. Если established conntrack/старые maps продолжают доступ — STOP до согласованного targeted pilot containment, не чистить общую conntrack/firewall WG |
| Offline/stale client и control-plane down | Повторить revoke при offline/спящем клиенте, refresh/подключении, затем недоступной management. Зафиксировать границы: JWT sync не push SCIM и не real-time revoke. Для строгой немедленной изоляции нужен независимый target/routers firewall kill path и отдельный проект; пилот без этого не соответствует такому SLA |
| Restart/restore | Каждая VM, server pod и approved NAT restart; тот же state identity, TLS renewal, backup restore в изоляции, deny не исчезает |
| Неизменность production | До/после: адреса/WG public peer IDs/AllowedIPs, routes, K3s Ready, cross-node pod/DNS, существующие private web/SSH/recovery и пользовательский VPN; отличия вне pilot namespace/VM отсутствуют |

Peer login expiry=3600s уменьшает lifetime, но **не является гарантией немедленного
сетевого revoke**. Setup-key expiry/revoke не отзывает уже enrolled peer. Нужны
операционный emergency runbook, мониторинг задержки group sync и отсутствие ручных
дополнительных memberships, которые переживут удаление JWT группы.

## Rollback / эксплуатационные риски

До rollout утвердить owner и recovery contact. При утечке/широком доступе сначала
отключить pilot policies/peers или остановить **обе новые router VM**, не менять
`wg-socrat`/маршруты K3s. Удалить pilot profiles/split-DNS на клиентах; снять только
новый edge/STUN mapping; остановить только pilot workloads, сохранить protected
backup/PVC и keys для разбора. Не удалять cluster-wide Traefik/cert-manager и существующий
Authentik; убрать только отдельный NetBird provider/application после прекращения sessions.
Восстановить до/после health baseline. Удаление namespace/PVC — отдельное решение о данных.

Риски перед production: SPOF Management/Signal/Relay/IdP/storage; общая LAN/WAN у двух
routers; NAT и SNAT resets; shared-ingress lateral access; stale JWT/maps/conntrack;
привилегированные router capabilities и daemon IPC; непроверенные target firewalls;
непройденные runtime acceptance/restore/upgrade; ограниченный observability Community.
Backup включает SQLite store/events/embedded IdP DB и encryption keys; делать согласованно
со stopped singleton или штатным verified backup, не копировать живую SQLite без consistency.

**Deployment-ready:** локальный воспроизводимый compiler/intent, runtime-secret contract,
pins, offline tests и план acceptance. **Не deployment-ready:** actual topology/DNS/TLS,
endpoint/group allowlist, IdP provider, recovery/revocation SLA и реальные acceptance.
Только после закрытия всех blockers и отдельного reviewed approval возможен canary deploy.
