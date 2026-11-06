# Диагностика входа: native SSO и MFA-шлюзы

> Сетевой итог 6 ноября: [network-access.md](network-access.md). Указанный в старых приёмках `176.98.185.59` — бывший VPS; текущий `109.120.141.97`. Grafana/Rancher теперь имеют reviewed публичные entrances, Mac resolver overrides сняты, Kuma status/admin boundary завершён. Исторические diagnostic symptoms ниже не считать текущим live-срезом.

Срез: **2 ноября 2026**. Индекс: [identity.md](identity.md).
Этот документ фиксирует проверенные результаты и открытые проблемы; не заменяет live-проверку.

## 1. Почему после Authentik остаётся форма приложения

SSO — единый вход; OIDC и SAML — протоколы его реализации. Кнопка/плитка сама по себе не добавляет поддержку протокола приложению.

| Приложение | Что реализовано | Что увидит пользователь |
|---|---|---|
| Argo CD | Native OIDC, short bearer + server-side refresh | Вход через Authentik; отдельный native пароль не нужен для SSO-пути |
| 3x-ui 3.11.0 | Внешний Authentik forward-auth gateway | Authentik MFA/допуск → **штатный логин 3x-ui** |
| n8n, текущая Community-инсталляция | Embedded Authentik proxy охраняет browser UI/rest | Authentik MFA/допуск → **возможен штатный логин n8n**; native SSO не внедрён |

Если родительская сессия Authentik активна, первый этап может пройти автоматически. Отсутствие кнопки Authentik в 3x-ui — ожидаемое свойство этой реализации, не доказательство обхода. В native форме используется существующий пароль приложения, не пароль Authentik. Автоматической привязки по email/name или создания native аккаунтов нет.

Один вход вместо двух потребует поддерживаемой интеграции в самом приложении, reviewed доработки или миграции. Не имитировать SSO сохранённым admin-паролем/автозаполнением через прокси и не обходить лицензионные ограничения n8n.

## 2. Argo CD: новое согласие offline_access

Текст `Access to request new tokens without interaction` — native consent на scope `offline_access`. Email/profile могут отображаться как уже выданные, offline-access — как новое разрешение. Это нужно для refresh коротких токенов и **не выдаёт admin-роль, не отключает MFA**.

Подтверждать только самостоятельно начатый вход в ожидаемое приложение на доверенном Authentik hostname. Не скрывать/подделывать consent ради косметики. Подробности и реальные expiry-тесты: [Argo refresh](../docs/identity/argocd-refresh.md).

## 3. 3x-ui: исправленный Failed to fetch на Login

**Воспроизведён и исправлен дефект gateway**, а не ошибка пароля:

1. При свежей gateway-сессии native CSRF и POST с пустыми полями возвращали штатный JSON200.
2. После удаления только proxy-cookie у временного fixture фоновый POST перенаправлялся в OAuth/Authentik.
3. Cross-origin redirect фонового fetch приводил к `TypeError: Failed to fetch`.

Gateway теперь возвращает **same-origin401 без redirect** для native XMLHttpRequest, fetch cors/same-origin, WebSocket и небезопасных методов. Только обычная безопасная навигация браузера запускает OAuth. Штатная 3x-ui3.11 уже умеет обрабатывать401 через top-level `location.replace`; новый authentication JS не добавлялся.

Проверены оба public edges: свежий CSRF/POST JSON, отсутствующая proxy-cookie →401 без Failed to fetch, **нажатие реальной native кнопки Login →401 → возврат через top-level SSO**. Синтетические данные формы не достигли native backend; это не проверка настоящего owner-пароля. Временные observer users/admission bindings удалены. Источники:

- `scripts/build-xui-auth-gateway.py`, `deploy/xui-auth-gateway/{nginx.conf,resources.yaml}`;
- `scripts/identity-xui-gateway-smoke.py --run [--public-edge IP]` — временные identity/admission writes, не read-only;
- [Полный runbook](../docs/identity/xui-gateway.md).

Остаётся ограничение: native outpost делает browser roundtrip при истечении proxy-сессии; бесшовный refresh, как у Argo CD, не доказан. После простоя возможны reload и повторный ввод native полей. Bearer TTL не увеличивали ради сокрытия проблемы. Не воспроизводить POST с паролем после OAuth автоматически.

MFA, owner-only admission, native CSRF и отдельные machine credentials не ослаблены. Bearer API exception по-прежнему удаляет Cookie и проверяется самой 3x-ui; invalid Bearer →401. VPN-транспорт, подписки, native x-ui и Traefik этим исправлением не перезапускались — только новый gateway.

## 4. n8n: открытое сообщение владельца, не исправленная проблема

Владелец сообщил о проблеме с авторизацией, **конкретный симптом и этап пока не уточнены**. Нельзя считать проблему решённой или автоматически приписывать её причине из 3x-ui.

Зафиксированные первичные проверки на **обоих** edges `109.173.40.247` / `176.98.185.59` с корректным HTTPS/SNI:

| Проверка | Результат | Что это доказывает |
|---|---|---|
| `GET /` без сессии | 302 | Срабатывает browser gateway |
| Чистый Chromium → n8n | Native Authentik identification/password, без JS errors | Начальный переход работает, не end-to-end owner login |
| `GET /healthz` | 200 | Backend жив и health не зависит от интерактивного входа |
| `GET /api/v1/workflows` без API key | 401 | Machine API не стал публичным и не получает login redirect |
| n8n и Authentik pods | Running/Ready, без текущих рестартов | Нет наблюдаемого падения этих pod на момент проверки |

**Не проверены:** личная owner-сессия, native login n8n, работа UI/rest после простоя, reconnect/WebSocket и действующий owner API key. Во время этой диагностики конфигурация n8n/IdP не менялась, fixture users не создавались.

Следующий шаг — получить безопасное описание: на каком экране сбой; точный текст; сразу или после простоя; проблема в native n8n форме, Authentik/MFA, editor/rest или зацикливании. Затем воспроизвести именно этот сценарий. Не переносить XHR401-конфигурацию 3x-ui вслепую: n8n использует **proxy mode embedded outpost**, а 3x-ui — nginx forward-auth.

Источники n8n: `deploy/identity/n8n-gateway.yaml`, `deploy/identity/services.json`, `ansible/roles/authentik/files/configure.py`. UI/rest owner-only; отдельные reviewed routes для webhook/forms/health/API/OAuth credential callbacks сохраняют собственную native authentication. Не включать их в wildcard browser gate и не открывать весь `/rest` ради обхода ошибки login.

## 5. Безопасный порядок диагностики

1. Уточнить этап и свежая ли вкладка. Private window — отдельная проверка, не удаление owner MFA devices.
2. Проверить публичный HTTPS с обоих разрешённых edges без отключения проверки сертификата; не менять системный DNS/WireGuard ради теста.
3. Сравнить навигацию документа с XHR/fetch: 302 в cross-origin flow, 401, 403/CSRF и JSON с ошибкой пароля — разные причины.
4. Не копировать пароли, Authorization/Cookie, callback query, OTP/QR, полный HAR или приватный DOM в чат/Git. Для скриншота убрать секреты и параметры адресной строки.
5. Сначала read-only проверки; реальные тестовые identities/admission bindings — отдельный явный scope с точной cleanup. Не менять факторы владельца.
6. Не расширять TTL bearer, роли, bypass paths, trusted headers или отключать CSRF/TLS/MFA ради исчезновения ошибки.
7. Исправлять authoritative GitOps source, дождаться Synced/Healthy; не бороться с selfHeal. Fixtures не являются личной owner acceptance.

## 6. Актуальный frontend

Nature: один scene CSS с inline preview того же фото, один HQ AVIF/WebP, immutable image cache; не два полных случайных кадра. Plan History занимает естественную высоту **без внутреннего scroll**; история/повторы/права не менялись. Подробности и тесты — [identity-frontend.md](identity-frontend.md), §§15–16. Эти изменения внешнего вида не являются исправлением сессий n8n.
