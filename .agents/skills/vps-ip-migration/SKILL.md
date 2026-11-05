---
name: vps-ip-migration
description: "Смена публичного IPv4 VPS socrat-2 в homelab: обязательный Ansible playbook для детерминированной host/source-фазы, безопасные ситуационные действия с DNS glue, 3x-ui, WireGuard, Collector, NetBird, GitOps и проверка реальной доставки. Использовать при замене IP провайдером, плановом переносе или восстановлении после недоступности адреса."
---

# Переезд socrat-2 на новый публичный IPv4

## Назначение и обязательная граница

Используй **`ansible/playbooks/vps-ip-migration.yml`**, а не цепочку несохранённых
`sed`/SQL/SSH-команд. Playbook — воспроизводимая основа, **не автоматическое
подтверждение завершения всего переезда**. Этот skill обязателен до и после него.

Автоматизация: [`scripts/vps-ip-migration.py`](../../../scripts/vps-ip-migration.py)
(пути ниже всегда от корня репозитория). Инвентарь, владельцы и реальные грабли
предыдущего переезда: `docs/vps-ip-migration-20261105.md`.

- **Playbook:** явные old/new IPv4, все четыре preflight, allowlist исходников,
  приватные preimages, точечные host-файлы, endpoints WireGuard без перезапуска
  интерфейса, native Knot/TCP transport/guard, только `hosts.address` в SQLite.
- **Skill:** выбор маршрута доступа, анализ отказов и новых владельцев,
  согласование перерывов, registrar, Kubernetes/GitOps, секреты, Collector,
  реальный внешний VPN-тест, подписки, клиентские профили и критерии приёмки.
- Список ниже — обязательный checklist, не разрешение игнорировать новые
  зависимости. Если schema/identity/ownership изменились, остановись и исследуй.

## 0. Разрешение, изоляция, доступ

1. Получи точные старый и новый адреса от оператора/провайдера. Не угадывай их
   по DNS: DNS может быть split, кешированным или перехваченным. Не объявляй
   ТСПУ доказанным только по тайм-ауту или ответу поддержки.
2. Уточни, адрес уже назначен или только запланирован, сохраняется ли старый IP,
   разрешены ли короткие перерывы VPN/NetBird, нужен ли экстренный backup.
   Сама замена IP не означает переустановку ОС или необходимость обновить все ПО.
3. Проверь `git status`, прочитай действующие project instructions. При грязном
   исходном checkout используй отдельный worktree от свежего main. Не stash,
   reset, force-push и не перезаписывай чужие изменения. Один writer/worktree.
4. Проверь приватный доступ `10.250.0.2` и независимый путь SSH/консоль
   провайдера. Не переключай единственный работающий путь до проверки нового.
   Сохрани pinned host key: замена IP не основание отключать StrictHostKeyChecking.
5. Проверь новый адрес на интерфейсе, исходящий маршрут, доступность DNS/HTTPS
   наружу. Gateway может оставаться из старого префикса по схеме провайдера:
   **не вычисляй новый gateway по адресу** и не переписывай маршрут наугад.
   Проверь, сохранено ли назначение адреса после reboot; без необходимости не reboot.
6. Пароли только из существующего private controller/Ansible Vault. Никогда не
   печатай secret YAML, токены, subscription URL/QR, SQL dump, ключи и raw логи
   пользователей. Evidence — counts, hashes, адреса инфраструктуры, HTTP codes.

## 1. До изменений — данные и полная инвентаризация

- Backup вне VPS важнее ещё одной копии на нём. Уточни, что уже завершено и
  проверено; `.partial` не backup. Не удаляй готовые экстренные архивы после
  восстановления доступа. Preimages playbook **не заменяют backup сервера**.
- Для SQLite — online backup API + quick_check. Для PostgreSQL — pg_dump(all),
  для embedded etcd — штатный k3s etcd-snapshot. Файловый tar работающей БД не
  гарантирует согласованность; запись файла/хеш не доказывает восстановимость.
- Найди старый IP в актуальных исходниках, live specs, ConfigMaps/Secrets,
  native configs и профилях. Читай секреты приватно; выводи только пути/счётчики.
  Не заменяй адрес массово в Git history, старых receipts, backup и manifests
  исторического доказательства. Новые активные файлы добавь в allowlist после review.
- Инвентаризируй mounts: `tar --one-file-system` не копирует другие файловые
  системы и виртуальные mount views. Установи, где действительно лежат данные.
- Проверяй **все таблицы 3x-ui**, не только settings/inbounds. В прошлом адреса
  оказались в `hosts.address`. Нельзя заменять строки в бинарном `.db` файле!
- Запиши baseline: Ready/nodes, pod UID/container IDs/restart counts, identities
  backend/DB, native services, resource ownership, исходные alert states.
  Существующий OutOfSync не повод делать общий sync/prune.

## 2. Обязательная детерминированная фаза через Ansible

Перед запуском прочитай playbook, defaults роли и helper. Они deliberately
не устанавливают пакеты, не меняют ключи, не deploy-ят все charts и не делают
автоматический Git commit.

Создай **вне Git** файл параметров, mode 0600:

```yaml
vps_ip_migration_old_ip: "<OLD_PUBLIC_IPV4>"
vps_ip_migration_new_ip: "<NEW_PUBLIC_IPV4>"
vps_ip_migration_apply: false
# Источник истины должен быть чистым отдельным worktree.
# Defaults backup roots: root-owned /var/backups/... на узлах,
# private ~/Library/Application Support/homelab/vps-ip-migration на контроллере.
```

Проверь routing inventory. Если старое DNS-имя уже недоступно, добавь отдельный
private override inventory с существующими SSH aliases/проверенными адресами.
Не меняй глобально SSH/credentials, не используй `--limit`, чтобы обойти preflight.
В inventory все четыре узла должны быть доступны. У стандартного запуска сначала
идёт только audit. Ansible `--check` тоже не применяет миграцию.

```sh
cd /path/to/isolated-homelab/ansible
CROOT="$HOME/Library/Application Support/homelab/otel-controller"
ANSIBLE_NOCOLOR=1 ANSIBLE_SSH_EXECUTABLE="$CROOT/bin/ssh" \
  ansible-playbook -i inventory/hosts.yml \
  playbooks/vps-ip-migration.yml \
  -e @"$CROOT/become.yml" -e @/private/path/ip-migration.yml
```

Если требуется override, добавь второй `-i /private/path/access-override.yml`.
Проверь план каждого узла и source diff. Адрес должен уже быть назначен VPS;
если ещё нет, playbook остановится, а не начнёт публиковать неработающий IP.

Только после review и разрешения на native service restarts:

```sh
# Тот же запуск/инвентарь/секреты, плюс:
-e vps_ip_migration_apply=true \
-e vps_ip_migration_allow_service_restarts=true
```

Порядок: preflight всех → source → VPS → socrat-0/1/3 serially.
В default audit ничего не переписывается; remote Ansible temp scripts — не backup.

### Что делает host phase

- Installed DNS renderer/refresh; на VPS также Knot listener, `/etc/hosts`,
  WireGuard installer params и retained installer metadata.
- Persistent `wg-socrat.conf`; runtime меняет **только endpoint соответствующего
  peer**, не `wg-quick down/up` и не private/public keys, AllowedIPs или весь mesh.
- TCP transport server/client config; guard добавляет новую узкую owned rule
  прежде удаления её точного старого аналога. **Нет flush firewall**.
- Только затронутые **уже активные** native units: Knot, TCP transport, guard.
  Не запускает неожиданно dormant native fallback/legacy VPN.
- На VPS согласованная копия primary/retained-legacy SQLite; транзакционно
  заменяет только **точное** `hosts.address == OLD`. Сравнивает все остальные
  поля/таблицы внутри write transaction, проверяет quick_check. Не меняет IDs,
  credentials, лимиты, ports, subscription IDs и не восстанавливает старую БД.
- JSON receipts без чувствительных строк. `xui_reload_required` означает
  обязательную следующую фазу, **не выполненный restart Kubernetes**.

### Ошибка / повторный запуск

При любой ошибке остановись. Preimages и receipt остаются приватными. Нет
автоматического rollback на уже заблокированный IP. Частичный запуск с receipt
`applying`/`partial-failure-stop-and-investigate` запрещает слепой rerun.

Проверь фактическое состояние каждого затронутого файла, DB, runtime endpoint и
service. Приватно зафиксируй восстановление/доведение до согласованного состояния.
Только после явного решения и evidence пометь именно этот receipt как
`manually-reconciled`, сохранив исходный receipt отдельной копией. Снова audit.
Это не способ скрыть ошибку; source/host partial changes могут требовать ручного
доведения. Не откатывай живые данные целиком, не теряй новые записи/traffic counters.
Успешный повторный apply должен быть no-op, но **no-op не доказывает приёмку**.
Проверь прошлые receipts: необходимость reload могла остаться после предыдущего apply.

## 3. Source review, GitOps и остальные live владельцы

После source phase проверь diff: актуальные inventory/direct address,
WireGuard/TCP defaults, public DNS, Traefik edge, blackbox target, Bot webhook,
NetBird/STUN и auth egress RustFS. Не меняй образы/базы/ownership заодно.

- Прогони targeted tests и Helm render. Не называй весь suite зелёным, если
  проверялась только выборка. Сравни существующие failures с baseline;
  не ослабляй тесты/алерты для получения зелёного статуса.
- Коммить только свои файлы, fetch/rebase свежего main, обычный push.
  При одобренном HTTPS helper используй command-scoped
  `git -c credential.helper='!gh auth git-credential' ...`; не меняй глобальные
  remotes/credentials и не force-push. При ошибке push сначала проверь remote tip.
- Hard refresh только нужных Argo apps. Сверь effective values/parameters,
  revision и rollout — commit на GitHub не равен применению.
- NetworkPolicies должны попасть в **правильные namespace**. Рендери с
  `helm template ... --namespace rustfs`; отдельно проверь identity gateway.
  Никогда не apply разноимённые namespaces вслепую под одним `-n`.
- Live spec audit: Services/externalIPs, Deployments/args/env, NetworkPolicies,
  StatefulSets/DaemonSets/Ingresses. Не переписывай generated status/IP и
  Rancher publicEndpoints как постоянный source of truth (там бывает pod name).
- ConfigMap/Secret audit: значения приватно, отчёт только namespace/name/key/count.
  Замена одного поля — JSON patch с resourceVersion/precondition, не полный dump
  конфигурации в терминал. Сохрани private preimage. Не обновляй все Secret подряд.

### 3x-ui и подписки — обязательная проверка после host phase

1. Fresh consistent preimage и инварианты уже делает playbook. Если helper/schema
   не соответствуют текущей панели, не обходи его assert — изучи новую схему/API.
2. После изменения `hosts.address` согласуй короткий разрыв и пересоздай **только
   один точно идентифицированный pod x-ui** под действующим Deployment. Проверить
   namespace, UID, image и hostPath до действия; дождаться Ready. Не рестартуй VPS,
   k3s, Postgres, Collector и не запускай параллельного writer этой SQLite.
3. Проверь все enabled plain **и JSON** subscriptions, не публикуя subId/URL/body.
   Декодируй base64 и vmess; проверяй actual destination, а не только raw substring.
   Посчитай subscriptions/links, OLD/NEW/other и ошибки. Other destinations
   классифицируй: это могут быть сохранённые домены, а не ошибка.
4. Ключи/пароли/IDs/ports неизменны. Успешный SQL update или restart **не доказывает**
   обновление выдаваемых ссылок. Сверь результат до/после, quick_check и инварианты.

### Native Collector — отдельный владелец метрик

ServiceMonitor/Helm chart не перенастраивает автоматически уже сохранённый
`otel-cluster-config.data.scrape.yaml`. Prometheus — OTLP storage/evaluation,
**не возвращай ему scraping**.

- Найди ровно VPS blackbox job по job ownership + `service_id=edge-vps`, не номеру
  `.../26` и не общему replace всего YAML. `scripts/otel-scrape-config.py` и
  `otel-production-cluster.py` уже нормализуют captured bundle по chart target.
- Сохрани private CM preimage; меняется только target, все остальные jobs и
  `collector.yaml` byte-for-byte прежние. Валидируй pinned Collector candidate.
- CM projection должна реально обновиться. Для activation используй существующий
  `ansible/playbooks/otel-cluster-logs-activate.yml` с **свежими** pod UID,
  exact running container ID, actual imageRef, config/scrape SHA256. Проверь full
  binary SHA; read playbook, не выдумывай значения из старого receipt.
- **Нельзя** restart shared pod/StatefulSet: Prometheus/Thanos/reloader не должны
  менять IDs/restart counts. Только точный Collector container lifecycle.
- До/после — receiver refused/failed, exporter failed/enqueue, queue/drain,
  sent metric/log deltas, readiness и age. Краткий scrape gap сообщи честно.
- Старый failing series может жить до lookback expiry. Не удаляй series и не
  отключай alert. Дождись `probe_success=1` именно с NEW instance и снятия alert.

### NetBird и Telegram

- NetBird STUN binding и advertised URI — разные настройки. STUN-only listener
  идёт через GitOps; URI может лежать в private `netbird-runtime` Secret. Меняй
  только нужное поле, остальные bytes/credentials сохраняй. Secret projection
  не означает, что сервер перечитал конфиг; отдельный точечный reload/one-pod
  recreate с Ready gate. Не ротируй setup keys и не меняй policy при смене IP.
- Реальный UDP Binding снаружи: transaction ID и XOR-MAPPED валидны; никакого
  случайного source-SNAT. TURN Allocate не должен создавать открытый relay.
  Source IP пользователя не печатай. Reachability STUN ≠ приёмка всего NetBird.
- Bot chart webhookIP обновляется через GitOps. `getWebhookInfo` вызывай из сети,
  где Telegram API доступен, токен только в памяти/private process input.
  Выведи только configured IP, pending count, timestamp/класс ошибки.
  Исторический last_error не равен новой ошибке. Пустая очередь не доказывает
  успешную доставку нового сообщения. Не используй drop_pending_updates.

## 4. Registrar: A-запись не равна glue

У `.xyz` делегация на `ns1.alchemmist.xyz` (дом) и `ns2.alchemmist.xyz` (VPS).
Новая запись внутри Knot не обновляет glue родителя.

1. Проверь текущий registrar и делегацию, не полагайся на историческое описание.
2. В существующей авторизованной сессии REG.RU: домен `alchemmist.xyz` →
   DNS-серверы → свой список. **Имена NS неизменны**, IP ns1 неизменен,
   меняется только IP ns2. Не переключай на DNS регистратора и не разделегируй домен.
3. Перед submit сверь обе пары имя/IP; сохрани, проверь подтверждение кабинета.
   Если нужен login/MFA, передай управление пользователю; не проси пароль в чат.
4. Проверь непосредственно минимум два authoritative сервера родителя `.xyz`
   (`dig @x.nic.xyz ... NS +norecurse`, `@y.nic.xyz`), включая ADDITIONAL glue.
   Убедись, что отвечают именно родители, а не DNS interceptor; используй
   независимую сеть при сомнении. Google/Cloudflare DoH — дополнительная проверка,
   но ответ дочерней A-записи сам по себе **не доказывает обновление glue**.
5. Пока parent отдаёт OLD — registrar принял, публикация pending. Не говори
   «просто кеш», если прямой authoritative ответ ещё старый. После NEW у parent
   recursive кеши могут держать старый ответ до TTL. Запиши observed TTL/time,
   не обещай мгновенную глобальную сходимость.

## 5. Приёмка из правильных точек

Используй checklist в `references/acceptance.md`; при отклонениях —
`references/troubleshooting.md`. Выполни его, а не только
перечисли настроенные компоненты. Никакого «готово», если обязательные пункты
остались unknown; разделяй server complete, propagation pending и client action.

Команды/выбор актуальных profiles могут требовать ситуационного анализа, но
минимальные свойства неизменны:

- TCP/TLS из домашней/мобильной/независимой сети, а не только self-hairpin VPS.
- `scripts/check-public-ingress.py --check-dns`: TLS не отключать; login redirect
  валидировать по status/target, не засчитывать любой 302 как здоровье backend.
- Реальный authenticated VPN client **вне VPS**, literal NEW endpoint,
  корректный TLS SNI/WS path и HTTPS-запросы к нейтральной цели, Telegram, ChatGPT.
  После последнего reload повтори. Результат одного профиля не означает все
  Reality/VLESS/WireGuard/AmneziaWG профили: протестируй используемые протоколы
  или явно запиши непроверенные. Не рассылай traffic по чужим credentials.
- Temporary probes: private config, bounded timeout, конкретный процесс/PID,
  без raw body/log. Удалить pod/Secret/temp bundle, подтвердить отсутствие;
  permanent backups/preimages не удалять. Не kill чужие браузеры/процессы.
- Перечитай CROOT/локальный SSH alias, generated Mac WireGuard profile и
  **реально импортированный (imported)** профиль. File update ≠ GUI profile update.
- Попроси пользователя обновить subscription на телефоне и reconnect. Статически
  импортированные IP не меняются удалённо; не заставляй менять ключи/QR без причины.
- Не объявляй предотвращение будущей блокировки частью этого skill. Это отдельная
  задача; новый IP тоже может стать недоступен.

## Итоговый отчёт

OLD → NEW, commit/revision, что applied и delivered, actual тесты и vantage,
остаточные OutOfSync/unknown, parent glue, client actions, краткие перерывы,
сохранённые backup/preimage locations (без содержимого). Отдельно сообщи failures
и исправления. Не обещай бесконечную надёжность по короткому успешному тесту.
