# Identity: текущий статус и первый вход

## Текущая граница — 7 ноября, снятие внешних auth gates

Удалены11 obsolete Authentik Applications (включая старую Kuma bookmark-карточку)
и10 Proxy Providers; outpost assignments сняты.10 native OIDC Applications,
их UUID/client credentials/callbacks/policy bindings сохранены. n8n,3x-ui, Kuma
и Syncthing используют собственный login; SearXNG и опубликованные SPI artifacts
публичны без Authentik и NetBird. Reader допускает только GET/HEAD, проверяет
manifest/hash и выдаёт безопасные типы inline. [Контракт и границы](../docs/identity/native-browser-auth.md).

Повторная приёмка после восстановления socrat-2: **82/82** публичных проверок
на HOME и VPS, обычная проверка TLS без отключения верификации. Все4 ноды Ready;
socrat-2 Ready с17:55:34UTC7 ноября. Все8 затронутых Argo apps Synced/Healthy.
Старые xui gateway Application/Deployment/Service/ConfigMap и Pod отсутствуют;
force-delete не потребовался.10 native OIDC регистраций/providers/bindings и
сохранённые поля иконок не изменились; Proxy Providers0. Опубликованный artifact
проверен через оба входа: anonymous GET/HEAD/206, manifest/SHA-256, inline,
PUT/POST/PATCH/DELETE405. [Приёмка](../docs/identity/native-browser-auth.md#recovered-vps-final-acceptance).
Это протокольная приёмка, не новая проверка входа от имени каждого человека.


Актуализировано **7 ноября 2026**; источники:
`deploy/identity/{account-mappings.json,lifecycle.json,browser-auth-policy.json}`,
`docs/identity/user-recreation-20261107.md` и read-only проверка IdP.
Это состояние, не автоматический reconciler паролей или выдача новых прав.

## Личные identities

| Человек | Логин Authentik | Состояние |
| --- | --- | --- |
| Владелец | `alchemmist` | Защищённый owner, личный MFA, единственный human в `homelab-owner` |
| Tim | `antropophag` | Active/internal, nonsuperuser; на проверке пароль не задан и `last_login=null` |

UUID Tim: `6015c85b-82e9-49ce-a4e3-0270c676e26d`. Старую identity удалили штатно
после явного запроса владельца. Затем изменили **только username** с `tim` на
`antropophag`, без нового UUID, смены email, групп или provider subject.
Display name Tim и Linux account `tim` остаются отдельными именами.

Группы: `homelab-observer`, `netbird-pilot-login`, `netbird-pilot-grafana`,
`netbird-pilot-ssh-socrat-2`; `netbird-internal-admins` не выдана.
Имена pilot-групп сохранены как реальные protocol/policy identifiers, а не
предложение переименовать текущую сеть или расширить доступ.

## Пароль и MFA: без выдуманной автоактивации

**Native Create user не означает, что человек сможет войти без пароля или сам
увидит установку пароля на первом входе.** Для `antropophag` пароль пока не задан;
MFA сама по себе не является способом начать первый вход.

Штатное действие администратора: **Directory → Users → antropophag → Set password**,
с приватной передачей credential и отдельной согласованной процедурой его смены.
Не называть административно заданный пароль «лично установленным пользователем»
и не обещать forced password change, пока реальный flow не настроен и не проверен.

Самостоятельная установка через штатные invitation/enrollment/recovery Authentik
требует отдельной настройки соответствующего flow и доставки. SMTP/Brand recovery
сейчас не настроены; приглашение не отправлено. Добавленный ранее отдельный
`homelab-existing-human-activation-v1` удалён вместе с owned stage/policy, токен
отозван, delivery file убран. Не воскрешать его и не выдавать старую ссылку.
Пароль и MFA за человека не устанавливать ради теста.

Активный private bootstrap journal — `antropophag-login.json`, `initialized=true`,
без plaintext password. Исторические `tim-login.json`/backups не источник действующего
credential. Не сбрасывать marker и не запускать старый initializer/app smoke ради
«восстановления» пароля. Реальный первый пароль/MFA/login всё ещё не принят человеком.

## Native app identities и исключения

- **Grafana:** сохранены native user2/UID и Viewer, обновлён exact
  `hashed_user_id` subject при пересоздании; последующее переименование username
  этот subject не меняет. Нельзя заменять его UUID/email или включать email merge.
- **WebUI:** сохранены native user и шесть чатов, роль user; OAuth subject — новый
  UUID. Active auth row нужна для OAuth; старый local password заменён discarded
  random credential, прежний session stamp отозван. Это не защита от всех будущих
  self-service password routes: reviewed policy не равна постоянному enforcement.
- **Wiki:** тот же native editor и reviewed UUID mapping; local recovery только owner.
  При смене subject обновили две map entries существующего Secret и выполнили один
  scoped Wiki rollout, без смены PVC/image/аккаунтов.
- **Rancher:** immutable principal не обходили. Текущий native SSO user
  `u-authentik-tim-v2`; у него ровно прежние reviewed user-base/cluster-member grants.
  Старые `u-authentik-tim` и legacy local `u-22wv2` отключены, история сохранена.
  Override IDs/prefix в account mapping нужны для безопасного следующего reconcile;
  переименование IdP login не требует переименовывать эти Rancher resources.
- **Umami3.4.1:** native OIDC отсутствует; доступ этого человека **suspended**,
  существующие analytics/team/sites сохранены. Не очищать `deleted_at` и не вызывать
  delete-user API. Работающий доступ — после issue#85, не после MFA gateway + password.
- Другие apps: admission и native permissions независимо; появление плитки не
  означает выдачу admin/project rights или создание пользователя в каждом сервисе.

SSH keys/Linux sudo, NetBird device policies и WireGuard recovery не менялись при
browser identity cutover. Сброс IdP не является отзывом native app sessions/API keys.
Owner recovery, robots, machine API keys и emergency identities не подменять.

## Аватары

У owner и `antropophag` API возвращал Gravatar URL; собственного avatar attribute нет.
Это штатный выбор avatar modes tenant: ссылка по хешу email, не загрузка нами фото
и не доказательство входа через Google. Тот же email после пересоздания объясняет
тот же аватар. Браузер обращается к внешнему Gravatar; локальные initials — отдельная
возможная настройка, **её в этой задаче не применяли**.

Процедуры: [операции](identity-operations.md), [интеграции](identity-integrations.md),
[NetBird](netbird.md), [SSH](ssh-user.md), [recovery](identity-recovery.md).
