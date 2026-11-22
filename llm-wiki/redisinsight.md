# Redis Insight: вход через Authentik

Адрес: `https://redis.socrat.alchemmist.xyz`. Это одна панель для логических Redis-сервисов. [GitOps](../deploy/platform/redisinsight/resources/ui.yaml): namespace `redis`, один pod на `socrat-5`, сохранение настроек на retained PVC `redisinsight-data`. Redis Insight слушает только loopback. Единственный Service публикует oauth2-proxy; UI, API и WebSocket закрыты Authentik. Строгий callback `/oauth2/callback`, PKCE, группа `homelab-owner`. Не заменять OIDC проверкой переданного клиентом заголовка.

`redis-common` задан штатными переменными преднастройки. При первом входе владельцу предлагается лицензионное соглашение Redis Insight; до принятия UI не импортирует преднастроенные подключения. Условия за владельца не принимались. Redis-пользователь `insight-browser` может читать значения `litellm:*` и контрольный ключ пробы, но не записывать и не администрировать сервер. SCAN показывает имена ключей всего инстанса; это инструмент владельца, не интерфейс для арендаторов. Чтобы добавить другой Redis, нужны отдельный ACL и сетевой доступ к его адресу. Беречь PVC и `redisinsight-runtime` (ключ шифрования настроек); не переносить Redis control credentials в UI.

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

**Срез 22 ноября:** pod 2/2, PVC Bound, OIDC discovery и owner binding проверены. Через шлюз анонимный `/` дал 302 на Authentik, API и `/socket.io/` — 401. Из UI-контейнера проверены TLS с валидацией имени, Redis AUTH/PING; ACL DRYRUN не разрешил SET. Публичная A-запись и выдача сертификата ожидают интерактивного DNS-шага; публичный вход пока не принят.
