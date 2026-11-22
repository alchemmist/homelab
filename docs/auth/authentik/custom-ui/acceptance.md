# Historical browser acceptance

## Текущая граница — 7 ноября, снятие внешних auth gates

Удалены11 obsolete Authentik Applications (включая старую Kuma bookmark-карточку)
и10 Proxy Providers; outpost assignments сняты.10 native OIDC Applications,
их UUID/client credentials/callbacks/policy bindings сохранены. n8n,3x-ui, Kuma
и Syncthing используют собственный login; SearXNG и опубликованные SPI artifacts
публичны без Authentik и NetBird. Reader допускает только GET/HEAD, проверяет
manifest/hash и выдаёт безопасные типы inline. [Контракт и границы](../../applications/native-browser-auth.md).

Повторная приёмка после восстановления socrat-2: **82/82** публичных проверок
на HOME и VPS, обычная проверка TLS без отключения верификации. Все4 ноды Ready;
socrat-2 Ready с17:55:34UTC7 ноября. Все8 затронутых Argo apps Synced/Healthy.
Старые xui gateway Application/Deployment/Service/ConfigMap и Pod отсутствуют;
force-delete не потребовался.10 native OIDC регистраций/providers/bindings и
сохранённые поля иконок не изменились; Proxy Providers0. Опубликованный artifact
проверен через оба входа: anonymous GET/HEAD/206, manifest/SHA-256, inline,
PUT/POST/PATCH/DELETE405. [Приёмка](../../applications/native-browser-auth.md#recovered-vps-final-acceptance).
Это протокольная приёмка, не новая проверка входа от имени каждого человека.


> Текущий срез7 ноября: [логины, первый вход и native роли](../operations/identity-current-state.md),
> [NetBird/сеть](../../../network/README.md), [владельцы мониторинга](../../../observability/monitoring/observability-current.md).
> Датированные rollout/smoke ниже — история своего этапа, не общая readiness.

Начало: [identity.md](../../architecture/identity.md). Подробный engineering runbook текущего дизайна.
