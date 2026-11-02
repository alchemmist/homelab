# 3x-ui: Authentik MFA-шлюз, не native SSO

## Граница

Панель `vpn.alchemmist.xyz` (3x-ui 3.11.0) не предоставила native OIDC/SAML в проверенной версии. Поэтому браузер проходит **Authentik MFA → собственный логин 3x-ui**. Пароли, native MFA, пользователи, API-токены, клиенты и база панели не заменяются; автоматического создания/слияния аккаунтов нет. Сам шлюз не превращает Authentik-группы в роли 3x-ui.

- Приложение `xui-panel`, provider `homelab-xui-panel`, `forward_single`; допуск только `homelab-owner`.
- Используется существующий embedded outpost; другие providers сохраняются.
- Nginx без SA-токена, non-root/read-only, pinned image, на `socrat-2`. Браузерные обращения проверяются native forward-auth.
- `offline_access` добавлен только этому provider, bearer validity оставлена **5 минут**, refresh grant validity — 8 часов. **Ограничение native outpost:** реальный expiry-тест обнаружил browser roundtrip через IdP даже с offline-access; это не бесшовный server-side refresh как у исправленного Argo CD. Активный родительский SSO вернул fixture к native login без нового ввода пароля/TOTP; API/XHR при истёкшем proxy cookie может потребовать обновить страницу. Не увеличивать bearer TTL, чтобы скрыть это; отдельное решение — reviewed gateway с полноценным native OIDC refresh.
- Proxy cookies проверены как `Secure`/`HttpOnly`; native cookies на публичном HTTPS получают `Secure`. Callback-коды и запросы не пишутся в access/error-логи шлюза (error level `crit`).
- API без browser MFA разрешён **только** под `/.../panel/api/` с каноническим `Authorization: Bearer …`. Проверяет токен сама 3x-ui; gateway удаляет входящий Cookie. Неверный Bearer не превращается в cookie-вход и не отправляется на IdP. Browser/cookie-only API остаётся за MFA. Вход по логину/паролю — не unattended API-исключение.
- Подписки text/JSON и существующий Trojan WebSocket имеют отдельные прежние backends, priority 200; панель — gateway с priority 100. Они не зависят от IdP. Native Bearer-ветка не делает auth subrequest; отложенный DNS lookup позволяет gateway стартовать без доступного DNS/IdP. Это не заявление о полном cold-start/HA всей инфраструктуры.

## Прямой порт и recovery

До изменения публичный `176.98.185.59:18082` отвечал HTTP 404 и обходил будущий MFA-шлюз. Теперь отдельная nftables-таблица `inet homelab_xui_panel_auth` закрывает TCP 18082 на публичных адресах, включая обращения к public IP через локальный/VPN exit. Не меняются WireGuard, forwarding/NAT, SSH, подписки, VPN-порты или transport-конфигурация.

Оставлены только private destination `10.250.0.2` и loopback, через существующие trusted interfaces. Это **сознательная внутренняя recovery/workload trust boundary**, не универсальное принуждение Authentik ко всем возможным локальным обращениям. Доступ к private backend всё ещё требует native credentials. Не выдавать его как публичный альтернативный URL; owner recovery — через доверенный SSH/WireGuard путь. Уже имеющий root/control над узлом или privileged workload способен обходить эту границу.

`homelab-xui-panel-auth.service` — persistent oneshot, до k3s/VPN-сервисов, `CAP_NET_ADMIN`, только своя таблица. Stop сервиса **не открывает порт**. Инсталляция выполнена явной одноразовой cluster-owner Job: host PID/ROOT read-only, `SYS_CHROOT`, две writable managed directories, без SA-токена. Это административная host-операция, а не новое право обычных workloads/SSH-пользователей; sudo/SSH policy не менялась. Job удаляется TTL-контроллером.

## Источники и повторение

- Gateway: `deploy/xui-auth-gateway/`, renderer `scripts/build-xui-auth-gateway.py`.
- Официальный неизменённый upstream favicon: `icon-source.json`, закреплённый revision/SHA256; отдельный публичный immutable image endpoint, не auth-обход для других ресурсов.
- Argo Application: `deploy/argocd/apps/xui-auth-gateway.yaml`, `Synced/Healthy` проверяется **до** переключения ingress.
- Публичные маршруты: `charts/traefik-edge/{values.yaml,templates/ingress.yaml}`. Активация не меняет Deployment/listeners Traefik.
- Host firewall: `deploy/xui-auth-gateway-host/`. `python3 scripts/xui-panel-firewall-job.py` только печатает reviewed Job. Owner применяет его явно, ждёт Complete, проверяет persistent service и недоступность public 18082. Не оставлять этот шаг «на потом»: иначе raw backend обходит шлюз.
- Узкий IdP reconciler: `ansible/roles/identity_integrations/files/xui_gateway.py`, config `deploy/identity/xui-panel.json`. Это отдельная forward-auth интеграция, не replay всего foundation/controller.

На owner node защищённый root `~/.cache/homelab-authentik/` содержит существующий `credentials.json`, `xui-panel-journal.json` с точными PK/UUID и `xui-panel-launch.json` с полным HTTPS URL native панели (`{"url": "…"}`). Файлы 0600, каталог 0700; не печатать/публиковать их. Provider/app с совпадающим именем без защищённого journal **не усыновляется**. Initial creation требует launch-файла; повторный `--action check` read-only, `--action apply` reconciles только эти managed objects/owner binding/outpost provider addition. Пример после защищённой доставки файлов:

```sh
python3 xui_gateway.py ~/.cache/homelab-authentik xui-panel.json --action check
```

После реальной проверки разрешены `apply`, затем ещё `check`; нельзя изменять реальные owner factors ради тестов. Новое приложение root Argo применяет из опубликованного `main`, а не борьбой с selfHeal. Отсутствие IdP — fail-closed для публичной human-панели, не повод открыть raw порт или убрать native MFA.

## Приёмка 2026-11-01/02

- Два независимых свежих browser fixture runs: public edges 176.98.185.59 и 109.173.40.247, TLS/SNI проверяется, системный DNS не изменяется.
- Реальный native password/TOTP enrollment; обычный observer получает native Permission denied. После временного точного user-binding он достигает **только native password screen 3x-ui**, без native входа/доступа к VPN-администрированию. Inspector 404, spoofed identity headers не обходят gateway, invalid Bearer 401 даже с gateway cookie. Все fixture users/bindings удалены.
- Реальный аутентифицированный Trojan TLS/WebSocket-туннель до и после: HTTPS 200 к example.com. Тест читает действующую machine credential только в памяти/защищённом временном config, не печатает её и не меняет VPN server.
- 15 уникальных активных subscriptions: 30 успешных native text/JSON HTTPS ответов без IdP HTML/redirect.
- Хеши native users/settings/API tokens/inbound configuration совпали; исходный VPN pod UID/restart counts и ingress pod template не изменились. VPN/Traefik не перезапускались. Перезапускался только **новый** gateway при исправлении/развёртывании его конфигурации.
- Первая browser попытка выявила относительный nginx redirect на HTTP/backend port; исправлено на canonical публичный HTTPS и повторно проверено. Первые host installer attempts завершились до записи файлов (D-Bus PID visibility / неверное имя проверяемой службы); успешная установка и последующий reload затронули только firewall oneshot. Ранние неуспешные harness attempts не считаются приёмкой. Отдельная строгая проверка «никаких IdP navigation после 5 минут» не прошла; это явно сохранённое ограничение native proxy, а не причина увеличивать bearer lifetime.

Повторяемый live тест (явные временные identity/admission writes, не owner):

```sh
python3 scripts/identity-xui-gateway-smoke.py --run
python3 scripts/identity-xui-gateway-smoke.py --run --wait-refresh
python3 scripts/identity-xui-gateway-smoke.py --run --public-edge 109.173.40.247
python3 -m unittest discover -s tests -p test_xui_auth_gateway.py
```

Личная owner-проверка native входа/owner recovery и valid-token API клиентом остаётся отдельной: реальные пароли/токены для неё не извлекались. `minutes=5` access и `hours=8` refresh у proxy provider — не доказанный абсолютный восьмичасовой предел и не восьмичасовой тест. Logout не гарантирует немедленного закрытия уже открытых WebSocket или уничтожения native 3x-ui sessions/API tokens.

## Откат

Сохранить private native recovery и текущий firewall. Сначала согласовать явное снятие MFA-гейта с human route (возвращает native-only публичный HTTPS вход); не затрагивать public VPN routes/backends. Только затем убрать provider из **текущего** списка embedded outpost, сохраняя чужие concurrent additions, и удалить только journal-owned application/provider/binding. Не восстанавливать весь старый outpost snapshot вслепую. Не удалять native DB/credentials и не сбрасывать MFA.

Не удалять firewall как побочный эффект rollback. Для его сознательного удаления owner отдельно отключает только `homelab-xui-panel-auth.service`, удаляет только таблицу `inet homelab_xui_panel_auth` и managed unit/rules; никакого `flush ruleset` или восстановления всех node firewall правил.


## Login Failed to fetch: expired gateway XHR correction

Reproduced the reported error without real panel credentials: a fresh gateway
session accepted native CSRF + empty-login POST (200 JSON), whereas removing only
the fixture proxy cookie caused cross-origin OAuth redirects and browser
TypeError: Failed to fetch. This is the same unauthenticated branch reached after
proxy expiry, not evidence of a wrong native password.

Named auth-login now returns **401 without redirect** for native XMLHttpRequest,
fetch cors/same-origin, websocket, and unsafe methods. Only normal safe browser
navigation starts OAuth. Native 3x-ui3.11 already handles401 by top-level
location.replace; no custom login JS, POST replay, CSRF bypass or auth exemption.
After idle, a page reauthorization/reload can still occur and inputs may need
re-entry. Five-minute token lifetime and owner MFA/admission remain unchanged;
this does not claim silent proxy refresh.

Both public edges passed: fresh native CSRF/empty-login JSON; missing-cookie
fetch401 same-origin without redirect; **actual native login button** triggering
401 then recovering via top-level SSO. Synthetic form credentials never reached
the backend (response401 asserted); no owner password/OTP was read or reset.
Temporary observer/admission fixtures removed. Earlier selector-harness timeouts
were corrected to native autocomplete attributes and are not counted as passes.
Bearer-invalid401 and spoofed-header denial remain; VPN/public subscriptions,
Traefik and native x-ui were not changed/restarted. Only gateway rolled.
