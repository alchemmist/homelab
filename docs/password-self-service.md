# External: самостоятельная смена пароля

Адрес: **https://auth.socrat.alchemmist.xyz/change-password**.
Пользователь остаётся External, admin/staff группы не нужны. `/if/user/` у
External закрыт самим Authentik; прежнее обещание открыть там настройки неверно.

Мини-сервис `password-self-service` развёрнут через отдельный Argo CD Application,
источник `charts/password-self-service`, namespace identity. nginx проверяет
действующую cookie-сессию через Authentik `/api/v3/core/users/me/` без admin token;
анонимный посетитель направляется в штатный authentication flow с возвратом на
`/change-password`. Ошибки проверки не разрешают доступ. После проверки сессии мини-сервис
перенаправляет в том же окне на `/if/flow/socrat-change-password/`. Нативный flow
использует существующие domain Brand/CSS/случайный фон и password/repeat prompts.
Iframe больше нет; адрес `/change-password` служит постоянной входной ссылкой.
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
После двух исправлений владелец сообщил: «ага, вроде заработало». Это
подтверждение работоспособности страницы со стороны владельца, не доказательство
полного password-change/logout/re-login/MFA цикла каждого External-пользователя.
Успешную смену реального пароля не заявлять без отдельного подтверждения.
Пароль Владислава/других реальных людей не меняли, MFA не сбрасывали.

Private preimages: socrat-0 `~/.cache/homelab-authentik/password-self-service-*`;
initial apply `password-self-service-6nds08hm`. Никакого полного Authentik restart,
SQL workaround, cluster-wide sync/prune или изменения app admission не было.

## Исправления, которые нельзя откатывать

1. `6a2c14b5`: первоначальный iframe блокировался нативным
   `X-Frame-Options: DENY`. Теперь только top-level redirect; защиту Authentik
   от framing не отключать и не удалять заголовок.
2. `4216e51c`: относительный nginx redirect после успешной проверки сессии
   раскрывал внутренний `http://auth…:8080`. Оба redirect используют константный
   публичный HTTPS origin; Host/next посетителя не выбирают адрес назначения.
   Повторный HTTP probe с временной External-сессией подтвердил корректный
   `Location`; Argo Synced/Healthy именно на `4216e51c`.

Исходники мини-сервиса/flow: `d21935e8`; документация первого этапа `9407b4c4`.
Все эти изменения опубликованы в origin/main. Текущий closeout меняет только
документацию, не запускает новую смену пароля, rollout или вход за человека.

## Authentik Application Dashboard

Registered providerless application **Change password**, category **Account**,
launch URL `https://auth.socrat.alchemmist.xyz/change-password`. All card metadata
is English. No new OAuth provider, credentials, user memberships, admin rights or
admission bindings: this is a self-service link, not an app-role grant. The route
and native flow still require authentication. Users able to open the Authentik
Dashboard can see the card; this does not lift External `/if/user/` restrictions.
External users should keep the direct link.

Declarative metadata: `deploy/identity/password-self-service-application.json`.
Bounded additive registration: `ansible/roles/authentik/files/password_application.py`.
Standalone plan/apply playbook: `ansible/playbooks/password-self-service-application.yml`
(use existing pinned `ansible_host=socrat-0` alias on owner Mac; apply only with
`password_application_apply=true`). No full Authentik bootstrap is required.
Existing drift stops rather than overwriting. Live create/detail GET verified;
second run made no changes. Private receipt on0:
`~/.cache/homelab-authentik/password-dashboard-166gap0q`.
This is an Authentik dashboard registration, separate from the Argo Application;
no new Kubernetes deployment was needed for the card.
