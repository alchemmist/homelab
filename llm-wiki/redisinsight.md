# Redis Insight: вход через Authentik

Адрес: `https://redis.socrat.alchemmist.xyz`. Это одна панель для логических Redis-сервисов. [GitOps](../deploy/platform/redisinsight/resources/ui.yaml): namespace `redis`, один pod на `socrat-5`, сохранение настроек на retained PVC `redisinsight-data`. Redis Insight слушает только loopback. Единственный Service публикует oauth2-proxy; UI, API и WebSocket закрыты Authentik. Строгий callback `/oauth2/callback`, PKCE, допуск по любой из двух групп: `homelab-owner` или `redisinsight-readers`. Не заменять OIDC проверкой переданного клиентом заголовка.

`redis-common` задан штатными переменными преднастройки. При первом входе владельцу предлагается лицензионное соглашение Redis Insight; до принятия UI не импортирует преднастроенные подключения. Условия за владельца не принимались. Redis-пользователь `insight-browser` может читать значения `litellm:*` и контрольный ключ пробы, но не записывать и не администрировать сервер. SCAN показывает имена ключей всего инстанса; это общая панель для доверенных читателей, не интерфейс для изолированных арендаторов. Чтобы добавить другой Redis, нужны отдельный ACL и сетевой доступ к его адресу. Беречь PVC и `redisinsight-runtime` (ключ шифрования настроек); не переносить Redis control credentials в UI.

## Выдать или отозвать доступ

Authentik → Directory → Groups → `redisinsight-readers` → Users: добавить или удалить личную учётную запись. Назначать `homelab-owner` не нужно. После добавления войдите заново. После удаления новый вход не разрешён, если пользователь не владелец; ранее выданная cookie шлюза может действовать до 30 минут. Группа не предоставляет пароль Redis или доступ к порту 6379. Участники видят общие сохранённые подключения; не сохранять в этой панели привилегированные учётные записи. Отдельной изоляции настроек интерфейса по пользователям нет.

## Первичная публикация DNS

Как для pgAdmin, публичная A-запись указывает **только на HOME**: не расширять область наблюдения VPS ingress на database namespace. Использовать штатный playbook: он проверяет изменения на всех четырёх авторах зоны, сверяет общий хеш плана и только затем обновляет их по одному. На настроенном операторском Mac используются существующие SSH aliases с закреплёнными ключами. Запускать из корня репозитория в интерактивном терминале, sudo-пароль вводить **только в локальном приглашении Ansible**:

```sh
cd ansible
inv='socrat-0,socrat-1,socrat-2,socrat-4,'
ansible-playbook -i "$inv" playbooks/redisinsight-public-dns.yml --ask-become-pass
# Сверить четыре plan_hash и единственное изменение redis.socrat; затем:
read -r hash  # вставить проверенный plan_hash и нажать Enter
ansible-playbook -i "$inv" playbooks/redisinsight-public-dns.yml --ask-become-pass \
  -e redisinsight_public_dns_apply=true -e "redisinsight_public_dns_hash=$hash"
```

Проверить авторитетные DNS-ответы и `kubectl -n redis wait --for=condition=Ready certificate/redisinsight-tls --timeout=5m`. Затем без `--resolve` и без отключения проверки TLS открыть UI, проверить редирект на Authentik и отказ анонимному `/api/databases`. Владелец проверяет интерактивный вход и видимость подключения. Не сбрасывать MFA или сертификаты ради проверки.

**Срез 22 ноября:** pod 2/2, PVC Bound, OIDC discovery и owner binding проверены. Через шлюз анонимный `/` дал 302 на Authentik, API и `/socket.io/` — 401. Из UI-контейнера проверены TLS с валидацией имени, Redis AUTH/PING; ACL DRYRUN не разрешил SET. Публичная A-запись применена на 0/1/2/4; все три авторитетных NS возвращают только HOME. Сертификат Let’s Encrypt Ready. После исправления имени порта Service (`http`: TLS завершается на Traefik) обычный HTTPS без DNS overrides даёт 302 на Authentik, анонимные API и Socket.IO — 401. Редирект с проверкой TLS независимо подтверждён с московской ноды. Интерактивный вход владельца/MFA и принятие EULA не выполнялись.
