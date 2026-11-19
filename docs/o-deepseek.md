# o-deepseek: как это устроено

Техническая записка для следующего ресёрча. Секретов, ключей, cookie и URL подписок здесь нет.
Состояние на 18 ноября 2026.

## Зачем это было

Публичное имя модели в LiteLLM: `o-deepseek`.
Это не официальный API DeepSeek и не Venice. Это бесплатный веб-чат `chat.deepseek.com`,
обёрнутый в OpenAI-совместимый прокси и выставленный в общий каталог LiteLLM.

Рядом живут две другие модели, их путать нельзя:

| Публичное имя | Откуда ответ |
|---|---|
| `qwen3.8-27b` | свой vLLM, `http://vllm.llm.svc.cluster.local:8000/v1` |
| `v-deepseek-uc` | мост Venice, upstream id `openai/venice-agentic-deepseek-v4.1-flash-uncensored` |
| `o-deepseek` | веб-сессия DeepSeek через под `free-deepseek-api` |

Префикс `openai/` в LiteLLM и в OpenHands — это протокол клиента (OpenAI-compatible),
а не вендор модели.

## Репозитории и образы

База прокси: <https://github.com/ForgetMeAI/FreeDeepseekAPI>, зафиксированный коммит `648e708498bf`.
Это Node 22, HTTP-сервер на порту **9655**, OpenAI-совместимые `/v1/chat/completions` и `/v1/models`.
Авторизация upstream — не API-key DeepSeek, а снимок веб-сессии: `token` + `cookie`
в файле формата их `auth.json`. Proof-of-work запроса считается их `lib/pow.js`
и wasm SHA3 с `https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.*.wasm`.

Свой слой лежит локально и **не закоммичен** в `origin/main`:

- `charts/free-deepseek-api/` — Helm chart, которым поднят живой релиз.
- `services/free-deepseek-api/` — ранний свой образ (Chrome+Xvfb+noVNC внутри того же контейнера). Он собран, но как основной путь отвергнут.

Живой прокси-образ:

`harbor.socrat.alchemmist.xyz/homelab/free-deepseek-api@sha256:3af669f85def59d13ceb960a5f3d07da8796e8e996f44d2a2c55fead8387f82d`

тег `648e708498bf`. Собирался на `socrat-5` (linux/amd64). Локальный Mac — arm64, обычный docker build с QEMU зависал.

Браузер — не наш образ, а `lscr.io/linuxserver/chrome:amd64-latest` (Selkies, Chrome 158).
VPN-sidecar — официальный core из образа панели `ghcr.io/mhsanaei/3x-ui` (Xray **26.10.21**, панель **3.11.0**).

Argo CD этот релиз **не** управляет. Применялся `helm upgrade --install` в namespace `llm`.
Отдельный манифест `deploy/argocd/apps/free-deepseek-api.yaml` писался, но не коммитился, приложения в Argo нет.

## Как запрос доходит до DeepSeek

```text
OpenHands / Pi / другой клиент
  → LiteLLM https://llm.alchemmist.xyz/v1  (внутри: litellm.llm.svc:4000)
  → модель o-deepseek
  → litellm_params.model = openai/deepseek-chat
  → http://free-deepseek-api.llm.svc.cluster.local:9655/v1
  → Node server.js FreeDeepseekAPI
  → POST на веб-API chat.deepseek.com с token+cookie и PoW
```

В `deploy/platform/litellm/values.yaml` маршрут такой:

- `model_name: o-deepseek`
- `api_base: http://free-deepseek-api.llm.svc.cluster.local:9655/v1`
- `api_key: os.environ/DEEPSEEK_PROXY_API_KEY` — ключ **нашего** прокси, не DeepSeek
- `num_retries: 0`, timeout/stream_timeout 600

У ключа LiteLLM `openhands-monori` в рантайме `max_parallel_requests` поднимали с 1 до 8:
агент OpenHands шлёт несколько запросов сразу, лимит 1 давал `RateLimitError`.
Скрипт `scripts/provision-openhands.py` при **создании** ключа всё ещё ставит `1` и только модель `v-deepseek-uc`. Повторный прогон скрипта это перезатрёт.

## Под: четыре контейнера на socrat-5

Namespace `llm`, Deployment `free-deepseek-api`, nodeSelector `kubernetes.io/hostname: socrat-5`.
Один под, общий network namespace. PVC `free-deepseek-chrome`, `local-path`, 8Gi, ReadWriteOnce.
Стратегия по сути Recreate: том нельзя смонтировать вторым подом.

| Контейнер | Образ | Роль |
|---|---|---|
| `chrome` | linuxserver chrome amd64 | постоянный профиль Google Chrome и веб-десктоп |
| `service-vpn` | 3x-ui / Xray 26.10.21 | SOCKS `127.0.0.1:1080` в зарубежный выход |
| `session` | `python:3.12-alpine` | слот сайдкара; живой код обновления сессии сейчас не здесь |
| `proxy` | наш Harbor-образ FreeDeepseekAPI | OpenAI-прокси и сбор сессии |

Сервисы:

- `free-deepseek-api` ClusterIP **9655** — только внутри кластера.
- `free-deepseek-desktop` ClusterIP **3001** — HTTPS-десктоп Selkies, basic auth. Ingress нет. Снаружи открывался только `kubectl port-forward` на `127.0.0.1:3001`.

Пока контейнер `proxy` не ready (`/readyz` = 503 без живой сессии), Service не включает под в endpoints. Проброс на Service тогда пустой; рабочий проброс — прямо в Pod.

### Почему браузер именно так

Одноразовый экспорт cookie отвергнут: токен DeepSeek умирает, а ключи Google привязаны к устройству. Нужен постоянный профиль Chrome, в котором человек один раз логинится в Google и через него в DeepSeek.

Chrome 158 **не** слушает `--remote-debugging-port`, если `--user-data-dir` — каталог по умолчанию. Штатный `/usr/bin/wrapped-chrome` у LinuxServer содержит голый `--user-data-dir`, который съедает следующий аргумент (`--ozone-platform=wayland`). Свой wrapper копируется поверх него до `/init`:

- `--user-data-dir=/config/chrome-profile`
- `--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins=*`
- `--ozone-platform=wayland`, `--no-sandbox`, `--password-store=basic`

`CHROME_CLI` нельзя забивать вторым `--user-data-dir`: Chrome снова уходит в дефолтный профиль и выключает DevTools. Сейчас в `CHROME_CLI` только флаги и стартовый URL `https://chat.deepseek.com`.

Десктоп: Selkies, порт 3001, самоподписанный TLS, basic auth из Secret `free-deepseek-api` (ключи `desktop-user`, `desktop-password`). Это не публичный VNC.

### Как сессия попадает в прокси

`server.js` upstream читает auth-файл один раз на старте и в неинтерактивном режиме падает, если аккаунта нет. Свои правки:

1. Перед стартом пишется пустой `{"token":"","cookie":""}`, чтобы процесс не умер, пока человек ещё не залогинен.
2. В обработчик HTTP вшит `reloadDeepSeekAuthIfChanged()`: если mtime `DEEPSEEK_AUTH_PATH` изменился, вызывается `loadDeepSeekConfig({ fatal: false })`. Патч есть и в образе (Containerfile), и в ConfigMap `start.js` на случай старого слоя.
3. Рядом с сервером крутится `refresh-auth.js` (каждые `AUTH_REFRESH_MS`, по умолчанию 30 с).

Сбор auth, по приоритету:

1. **CDP** на `127.0.0.1:9222`. Берётся page target `deepseek.com`. Через DevTools: `localStorage.userToken`, `localStorage.hif_leim_cached`, `Network.getCookies` для `https://chat.deepseek.com/`.
2. Если CDP недоступен — запасной путь по файлам профиля: копия SQLite `Cookies` (хост `%deepseek.com`) и грубый поиск строки `userToken` в LevelDB. Этот путь уже один раз отдал неверный токен (`INVALID_TOKEN` / код DeepSeek 40003). Рабочий источник — CDP.

Файл пишется атомарно в общий volume `/data/deepseek-auth.json` и содержит поля, которые ждёт upstream:

`token`, `cookie`, `hif_dliq`, `hif_leim`, `wasmUrl`, `baseUrl`.

`hif_dliq` оставляли пустым. `wasmUrl` зашит на конкретный файл `sha3_wasm_bg.7b9ca65ddd.wasm` — при смене статики DeepSeek PoW сломается, даже если логин жив.

Python-контейнер `session` когда-то делал тот же файловый сбор. В текущем `refresh.py` перед этим циклом стоит `sleep(3600); return`, то есть процесс только занимает слот. Логи `[auth-refresh]` идут из Node в контейнере `proxy`.

`/readyz` смотрит, что в загруженном аккаунте есть токен. Он становится `ready:true` по **последнему успешному снимку**. Если Chrome уже разлогинен, а файл ещё не перезаписан пустым, readiness врёт, и LiteLLM продолжает слать запросы в мёртвую сессию.

### VPN только для капчи и Google

С домашней сети IPv4 до anycast Cloudflare `104.16.0.0/12` и `104.19.0.0/16` устанавливает TCP, но TLS ClientHello остаётся без ответа. `js.hcaptcha.com` имеет только A-записи в `104.19.229.21` / `104.19.230.21`, без AAAA. Поэтому и на маке, и в поде страница DeepSeek писала `Captcha failed to load`. Google по IPv4 при этом открывался, `1.1.1.1` тоже, Cloudflare по IPv6 тоже. Ломать локальный IPv4 не стали.

Выход сделан по runbook `llm-wiki/service-vpn-egress.md`:

- своя identity 3x-ui `svc-free-deepseek`, группа `services`, без квоты и без expiry (`totalGB=0`, `expiryTime=0`), `limitIp=1`;
- привязка только к существующему VLESS/REALITY inbound порт **32053** (запись inbound id 1), endpoint из подписки `91.189.82.238`;
- подписка только в Secret `free-deepseek-service-vpn`, ключ `subscription-url`, native JSON `https://vpn.alchemmist.xyz/<subJsonPath>/<subId>`;
- init `prepare-service-vpn` качает подписку по HTTPS без редиректов, проверяет ровно один VLESS/REALITY на этот endpoint и пишет `/vpn-runtime/client.json` в memory emptyDir mode 0600;
- sidecar слушает **только** `127.0.0.1:1080` SOCKS, без TUN, NET_ADMIN, hostNetwork и без смены маршрутов ноды;
- Chrome: `--proxy-server=socks5://127.0.0.1:1080` и `--proxy-bypass-list` на `chat.deepseek.com`, `*.deepseek.com`, `cdn.deepseek.com`, `fe-static.deepseek.com`, loopback.

Итого через VPN идут hCaptcha и Google. Сам чат DeepSeek и wasm PoW идут напрямую. После включения VPN `js.hcaptcha.com` из пода ответил HTTP 200 за ~0,3 с, и клик «Log in with Google» впервые открыл iframe challenge hCaptcha.

Этот VPN-sidecar наложен на живой Deployment и **не описан в закоммиченном chart**. Следующий `helm upgrade` из чарта без этих кусков его сотрёт.

## Что дописывали сами, а что взяли как есть

Взято как есть:

- протокол веб-чата, PoW и OpenAI-обёртка FreeDeepseekAPI;
- LinuxServer Chrome / Selkies как удалённый рабочий стол;
- 3x-ui и Xray как VPN-as-service, по тому же приёму, что `svc-n8n-google` (там узкие `dokodemo-door` только на два хоста Google, здесь SOCKS, потому что у Chrome много хостов капчи и OAuth).

Своё:

- постоянный профиль вместо экспорта cookie;
- wrapper Chrome ради недефолтного `--user-data-dir` и живого CDP;
- hot-reload auth-файла в `server.js`;
- сбор сессии по CDP с файловым fallback;
- пустой auth на старте, чтобы прокси не падал до логина;
- отдельный service-клиент VPN и proxy-bypass, чтобы капча грузилась, а DeepSeek не заворачивался в туннель;
- маршрут LiteLLM `o-deepseek` и выдача его ключам (`alchemmist`, `openhands-monori` и другим, кому нужен был бывший `venice-deepseek` уже как `v-deepseek-uc`).

Не делали и не надо делать в ресёрче как «обход»:

- автоматический клик «Login with Google» и решение hCaptcha;
- подмену PoW, обход бана аккаунта, второй аккаунт ради обхода блокировки.

## Почему это ломалось

1. **Профиль без `userToken`.** Обновлятор пишет `Chrome profile has no DeepSeek session yet`. Прокси ещё держит старый снимок, `/readyz` зелёный, следующий completion получает `DeepSeek PoW response has no data.biz_data.challenge`. Так было дважды. Chrome в этот момент оказывался снова на `https://chat.deepseek.com/sign_in`.
2. **hCaptcha не грузилась** до VPN: TLS к `104.19.229/230.21` молчал и на маке, и в поде.
3. **Кнопка Google ничего не делала визуально**, потому что ждала скрипт hCaptcha ~30 с и не открывала ни iframe, ни окно аккаунта.
4. **Лимит ключа OpenHands** `max_parallel_requests=1`.
5. **Аккаунт веб-чата заблокирован DeepSeek** до 21 ноября 2026, 23:48, текст: violation of user policies. Пока бан активен, новый логин этого аккаунта `o-deepseek` не оживит. `v-deepseek-uc` от этого бана не зависит.

## Что проверять следующему агенту

- Меняется ли у DeepSeek контракт PoW (`data.biz_data.challenge`) и URL wasm. Имеет смысл сравнить текущий `server.js` / `lib/pow.js` коммита `648e708` с upstream.
- Почему веб-сессия умирает, хотя профиль на диске: истечение cookie, отзыв `userToken`, рестарт Chrome, бан аккаунта. Не считать `/readyz` доказательством живого логина.
- Файловый парсер LevelDB лучше не чинить «ещё одним regex»: он уже выбирал ложный `userToken`. Источник правды — CDP `localStorage.userToken`.
- Chart и VPN-sidecar разъехались. Либо дописать sidecar в `charts/free-deepseek-api` и закоммитить, либо живой helm-релиз будет затёрт.
- `refresh.py` сейчас мёртвый цикл. Либо удалить контейнер `session`, либо не описывать его как сборщик сессии.
- Поле `wasmUrl` захардкожено. Имеет смысл брать актуальный URL со страницы чата.
- Бан до 2026-11-21 23:48. Ресёрч протокола полезен, боевой трафик `o-deepseek` до конца бана бессмысленен.
