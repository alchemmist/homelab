# External: самостоятельная смена пароля

## Исправление browser framing

Первоначальный iframe браузер блокировал: нативный flow отдаёт
`X-Frame-Options: DENY`. Мини-сервис исправлен на top-level redirect после
проверки сессии. `/change-password` остаётся входной ссылкой; после входа адрес
меняется на `/if/flow/socrat-change-password/`. Защита от framing не ослаблялась.
Ниже iframe-описание первоначальной реализации историческое и заменено этим fix.

Адрес: **https://auth.socrat.alchemmist.xyz/change-password**.
Пользователь остаётся External, admin/staff группы не нужны. `/if/user/` у
External закрыт самим Authentik; прежнее обещание открыть там настройки неверно.

Мини-сервис `password-self-service` развёрнут через отдельный Argo CD Application,
источник `charts/password-self-service`, namespace identity. nginx проверяет
действующую cookie-сессию через Authentik `/api/v3/core/users/me/` без admin token;
анонимный посетитель направляется в штатный authentication flow с возвратом на
`/change-password`. Ошибки проверки не разрешают доступ. Страница same-origin
встраивает нативный `socrat-change-password` flow в полноэкранный iframe: он
использует существующие domain Brand/CSS/случайный фон и password/repeat prompts.
Нативная кнопка пока называется Continue/Продолжить, заголовок — Update password.
После обновления появляется подтверждение; Continue завершает сеанс штатным
logout flow и возвращает к странице (потребуется войти с новым паролем).

Новый flow: authenticated-only → существующий password/repeat prompt с прежней
password policy → существующий never-create UserWrite → success message.
Обработчик пароля остаётся в Authentik; мини-сервис не принимает пароли, не имеет
API-токена, ServiceAccount token, PVC или БД. Cache-Control no-store, CSP,
read-only/nonroot контейнер, pinned image. Локальные external пароли поддержаны;
пароль внешнего upstream IdP этот сценарий не меняет. App группы/тип/UUID не меняются.

Создание flow: `ansible/roles/authentik/files/password_self_service.py` (GET-only
по умолчанию; явный --apply создаёт отсутствующие собственные ресурсы, останавливается
на drift). Первоначальная exact-path redirect route остаётся приоритетом150;
Argo mini-service имеет160 и обслуживает страницу. Не удалять shared login flow,
Brand, password policy, shared write/prompt stages при rollback. Для rollback
маршрута сначала убрать только новый ingress, а не общую авторизацию.

Live acceptance: Argo Synced/Healthy, Deployment ready; публичный anonymous GET
даёт302 на нормальный Authentik login с next=/change-password. Native integration
на временном zero-group External fixture: anonymous denied, password/repeat fields,
CSRF missing denied, mismatch rejected, новый пароль записан нативным flow,
success prompt достигнут, External/zero groups сохранены. Fixture удалена.
Authenticated fixture session создавалась native test helper — это **не browser
login/MFA E2E**. Первые прогоны harness исправлены под подписанные Authentik cookies,
custom CSRF header и цепочку redirects; права/защиты production не ослаблялись.
Браузерный инструмент не стартовал: профиль занят другой сессией; её не закрывали.
Визуальная browser-приёмка и настоящий вход пользователя остаются для проверки.
Пароль Владислава/других реальных людей не меняли, MFA не сбрасывали.

Private preimages: socrat-0 `~/.cache/homelab-authentik/password-self-service-*`;
initial apply `password-self-service-6nds08hm`. Никакого полного Authentik restart,
SQL workaround, cluster-wide sync/prune или изменения app admission не было.
