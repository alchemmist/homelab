# DeeperSeeker: веб-сессия DeepSeek для `o-deepseek`

Срез приёмки **19 ноября 2026**, лимиты и границы бана — **после выката того же дня**
(коммит `1687e0d8`, в истории `main`). Это рабочая память, не public wiki и не разрешение
печатать токены, API-ключи или URL подписки. Git задаёт чарт и LiteLLM; живой токен
и подписка лежат только в Secret. Актуальные правила обращения с аккаунтом — в разделе
«Защита от бана» ниже; срез 19 ноября до него не переписывать.

Это единственный мост веб-сессии. Имена подов ниже — снимок приёмки, не контракт.

## Зачем отдельный сервис

Форк [artyom08-dev/deeperseeker](https://github.com/artyom08-dev/deeperseeker)
на коммите `1b1148ec1e2a` (пакет 7.0). Поверх апстрима там есть
пауза между вызовами, least-in-flight выбор токена, карантин после 403 и
регенерация WAF-cookie через Patchright. Длинный контекст мост сам режет и
перекладывает; заявленное окно модели `v4.1flash` — 369228 входа и 8192 выхода.

Отдельный namespace обязателен: PVC `local-path` ReadWriteOnce. Второй под в тот же
claim на `socrat-5` не встанет. Данные: claim `deeperseeker-data`, 2Gi, mount
`/app/data`. Процесс в образе — uid 10001.

## Что задеплоено

| Что | Где |
| --- | --- |
| Application | `deploy/argocd/apps/deeperseeker.yaml`, namespace `deeperseeker`, prune выключен |
| Чарт | `charts/deeperseeker`, values `deploy/deeperseeker/values.yaml` |
| Образ | `harbor.socrat.alchemmist.xyz/homelab/deeperseeker@sha256:696884aa3c846f4471b6876b4b3455e8fa047dfd2638f050c5f0b8cf270e16ac` |
| Узел | `socrat-5`, стратегия Recreate |
| Service | ClusterIP `deeperseeker:4000`. Ingress нет |
| VPN sidecar | `ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b` |

Образ — не чистый git форка. В него входит локальная проводка прокси; патч лежит
рядом с чартом: `charts/deeperseeker/files/proxy-wiring.patch`, копия для повторной сборки —
`deploy/deeperseeker/patches/proxy-wiring.patch`. При смене коммита форка патч накладывается заново. Поверх текущего digest собран, но не выкачен `harbor.socrat.alchemmist.xyz/homelab/deeperseeker:1b1148ec1e2a-hints` (`sha256:3cab7de3a4c23787e808d62364abc079ff98c60b8b8713edb55e1800e840d1df`). В нём те же слои и Chromium 156, плюс `log-created-chat-session.patch` и `client-hints-follow-ua.patch`. Values на него не переведены: роллаут после смены выхода, одним `helm upgrade`.
Тег `1b1148ec1e2a` совпадает с коммитом форка, digest — с уже пропатченным деревом.
Повторная сборка из чистого клона без патча снова пойдёт в DeepSeek напрямую.

Первый локальный `RepoDigest` (`sha256:8bda1721…`) Harbor не отдавал: манифест
тега другой, `sha256:696884aa…`. Пока values ссылались на первый digest, под был в
`ImagePullBackOff` / `not found`.

## VPN

Штатный путь из [service-vpn-egress](service-vpn-egress.md): init читает подписку,
оставляет один VLESS/REALITY на `91.189.82.238:32053`, sidecar слушает только
`127.0.0.1:1080` (SOCKS, без UDP). Чужого HTTP-proxy и hostNetwork нет.

Egress идёт через уже существующую identity **`svc-free-deepseek`**.
Secret `deeperseeker-service-vpn` в namespace `deeperseeker`, ключ `subscription-url`.
Отзыв этого клиента гасит выход моста. Имя клиента не менять вместе с удалением старого пода:
это текущий выход DeeperSeeker.

На приёмке выход через SOCKS был `109.120.141.60`, прямой выход пода — `94.29.124.139`.
`https://chat.deepseek.com/` через SOCKS ответил за ~0.3 с HTTP 403 (WAF без браузерной
сессии, не обрыв туннеля).

### Почему не хватило HTTPS_PROXY

В форке ни Patchright, ни `curl_cffi` переменные `HTTPS_PROXY` / `ALL_PROXY` сами не
читают. Chromium запускается без `proxy=`, `AsyncSession` создаётся без `proxy=`.
Upstream-вызовы идут через curl_cffi, не через aiohttp.

Патч добавляет:

- `DEEPSEEKER_BROWSER_PROXY` (запасной `ALL_PROXY`, затем `HTTPS_PROXY`) в три
  `chromium.launch`, bypass `localhost,127.0.0.1`;
- `DEEPSEEKER_UPSTREAM_PROXY` в `AsyncSession`;
- `DEEPSEEKER_TOKEN_CONCURRENCY` — в форке cap был зашит единицей.

Чарт задаёт браузеру `socks5://127.0.0.1:1080`, upstream — `socks5h://127.0.0.1:1080`
(DNS через туннель), `DEEPSEEKER_CALL_GAP_SECONDS=4`, concurrency `1`. В коде форка
дефолт паузы был `0`, не `4`, как в README.

## Секреты (без значений)

| Secret | Namespace | Ключи | Назначение |
| --- | --- | --- | --- |
| `deeperseeker` | `deeperseeker` | `admin-user`, `admin-password`, `api-key` | дашборд и Bearer моста |
| `deeperseeker-service-vpn` | `deeperseeker` | `subscription-url` | подписка `svc-free-deepseek` |
| `deeperseeker-harbor-pull` | `deeperseeker` | dockerconfigjson | pull Harbor |
| `deeperseeker-upstream` | `llm` | `api-key` | тот же Bearer, что у моста, для LiteLLM |

Копия логина дашборда на маке оператора: `~/.config/homelab/deeperseeker-credentials`,
mode 0600, в git не входит.

## Пробы

`/health` без токена в пуле — **503** `{"status":"degraded"}`. Это живой процесс, не
смерть. Liveness поэтому **tcpSocket :4000**. HTTP liveness на `/health` уводил под в
CrashLoop ещё до логина (на старом поде было 20 рестартов).

`/health?deep=1` без Bearer — **401**. С ключом и без токена — **503**,
`reason: no ACTIVE token in pool`, upstream не вызывается. С живым токеном глубокий
проб делает read-only `users/current` (не создаёт пустой чат: пустые сессии ловят
40003). Readiness — exec внутри пода: тот же URL с `DEEPSEEKER_API_KEY` из env.
Пока проб не 200, пода нет в endpoints.

Первая версия readiness была голым HTTP без ключа. После импорта токена под оставался
1/2 при уже зелёном ручном `deep=1`. Исправление: `8cde6d07`.

## Как попал токен

Логин с домашнего IP, не из кластера. Playwright-окно капчу не принимает: после
верной галочки DeepSeek пишет try again, потому что клиент палится как автоматизация.
Обычный Chrome с уже открытой сессией на `chat.deepseek.com` сработал.

В консоли этой вкладки (`Cmd+Option+J`):

```js
copy(JSON.parse(localStorage.getItem("userToken")).value)
```

`copy()` возвращает `undefined`. Это не ошибка: строка уже в буфере. В чат и в git её
не класть. Вставка — дашборд моста (`port-forward` на `svc/deeperseeker:4000`,
`/login`, затем форма токена). Алиас приёмки: **`main`**.

Если `userToken` отсутствует, консоль кидает TypeError про `null`, а не `undefined`.

На момент приёмки `cookies_valid` был false: файл WAF-cookie пуст. Глубокий проб и
короткий чат при этом прошли. Регенерация cookie через Patchright в поде отдельно не
принималась.

## Приёмка моста

Под `deeperseeker-cf68c6dbd-ccwcv`, **2/2 Running**, рестартов 0.

- `GET /health?deep=1` с ключом моста: **200**, `active_tokens: 1`, `pow_ok: true`,
  `upstream_reachable: true`, latency 645.5 мс, `chat_created: false`.
- `POST /v1/chat/completions`, модель `v4.1flash`, короткий user-prompt: **200**,
  текст `pong`.

## LiteLLM `o-deepseek`

Values: `deploy/platform/litellm/values.yaml`. Имя модели для клиентов не менялось.

| Поле | Было | Стало |
| --- | --- | --- |
| `api_base` | `http://deeperseeker.deeperseeker.svc.cluster.local:4000/v1` |
| upstream model | `openai/v4.1flash` |
| ключ | `DEEPSEEK_PROXY_API_KEY` ← `deeperseeker-upstream` |
| `max_input_tokens` | 32768 | 369228 |
| `max_output_tokens` | 8192 | 8192 |

На приёмке 19 ноября здесь были только `num_retries: 0` и timeout 600. Темп добавлен позже,
см. «Защита от бана». Сеть между `llm` и `deeperseeker` не режется NetworkPolicy
(отдельной политики на мост нет).

Проверка из пода LiteLLM мастер-ключом, после первого rollout: `model=o-deepseek` вернул
**200** и `pong`. Это один короткий вызов, не сутки стабильности и не нагрузка агента.

`v-deepseek-uc` — отдельный маршрут Venice, не этот мост. `openhands-monori` к `o-deepseek` не подключён.

## Чего эта приёмка не закрывает

- Имя VPN-identity `svc-free-deepseek` старше самого сервиса. Клиент живой и обслуживает только DeeperSeeker.
  Не отзывать его вместе с уборкой старого пода.
- Дашборд снаружи кластера не опубликован. Вход оператора — `kubectl port-forward`.
- Пока readiness красный, LiteLLM может слать в него только если сам не смотрит на
  endpoints. Сейчас под Ready; при 401/пустом пуле снова выпадет.
- Капча и логин из Playwright/Patchright в кластере не являются рабочим путём.
  Повторять логин надо из обычного браузера дома и заново вставлять `userToken`.
  После копирования вкладку закрыть. Logout на сайте отзывает сессию, и уже скопированный
  токен умирает вместе с ней.

## Защита от бана

Срез после выката лимитов. Коммит `1687e0d8`. На кластере проверены env пода и
`litellm-config`. Это не новая приёмка чата и не снятие карантина с токена.

Один `userToken` — одна веб-сессия DeepSeek. Новый логин в браузере или второй мост с тем же
токеном отзывает предыдущую. Мост получает HTTP 200 с кодом `40003 INVALID_TOKEN` и
считает это 401.

Опасен не сам параллелизм, а число новых веб-чатов. `DEEPSEEKER_TOKEN_CONCURRENCY=1`
выстраивает очередь на один токен, но не задаёт темп. Разные истории диалога имеют разные
signature и открывают разные чаты upstream. Обрыв стрима выбрасывает сохранённую сессию, следующий ход
создаёт чат заново. Rollover открывает ещё и служебный чат ради саммари.
`DEEPSEEKER_CALL_GAP_SECONDS=4` срабатывает после хода, а не между созданиями чатов. Единственный темп-лимит
в цепочке — `rpm` на модели в LiteLLM. Пачка новых сессий ведёт к «слишком частым сообщениям»,
затем к `RATE_LIMITED` и к отзыву `40003`.

Глубокий проб `/health?deep=1` ходит в `users/current` и чат не создаёт. Зелёный проб говорит, что
токен, WAF и PoW живы. Он не говорит, что аккаунт не уперся в лимит по темпу. Счётчика созданных чатов в Grafana нет: запросы в минуту этого не заменяют.
Алерт `SocratDeeperSeekerSessionLoggedOut` стреляет, когда контейнер `deeperseeker` жив, но не Ready 5 минут. Так readiness выглядит после разлогина и `40003`. Остановленный контейнер это правило не зажигает.

При разборе `SocratDeeperSeekerSessionLoggedOut` различать локальный статус и ответ upstream. Зафиксирован случай: один токен `ACTIVE`, `cookies_valid=true`, но авторизованный локальный `/health?deep=1` вернул 503, `deep.upstream_reachable=false`, в `deep.reason` — 401. Это не локальный 401 пробы: её API-ключ принят. Не делать Restore уже активного токена и не ослаблять readiness. Проверить состояние аккаунта обычным входом; если требуется обновление сессии, использовать штатный интерфейс, не передавать токен через Git или чат. После восстановления проверить HTTP 200 глубокой пробы, Ready обоих контейнеров и снятие трёх связанных алертов.

### Что стоит сейчас

| Где | Значение | Зачем |
| --- | --- | --- |
| LiteLLM `o-deepseek` `rpm` | 6 | общий потолок всех ключей; 8 уже на пороге «слишком частых» новых чатов |
| LiteLLM `max_parallel_requests` | 1 | один запрос к модели одновременно |
| LiteLLM `max_retries` и `num_retries` | 0 | клиентский ретрай не добивает уже упершийся в лимит аккаунт |
| `DEEPSEEKER_MAX_UPSTREAM_ATTEMPTS` | 1 | дефолт форка 3 на 429 давал бы ещё два удара |
| `DEEPSEEKER_RATE_LIMIT_COOLDOWN` | 300 | 60 секунд возвращали токен в ту же очередь |
| `DEEPSEEKER_CALL_GAP_SECONDS` | 4 | пауза после хода, не вместо `rpm` |
| `DEEPSEEKER_TOKEN_CONCURRENCY` | 1 | не поднимать |
| `DEEPSEEKER_PERSIST_SESSIONS` | `true` | чарт теперь задаёт явно; рестарт без этого открывает новый чат на каждый следующий ход |
| `DEEPSEEKER_BROWSER_PLATFORM` | `Linux` | токен снимается в Selkies, не на Windows |
| `DEEPSEEKER_BROWSER_USER_AGENT` | Chrome/156 на X11 Linux | движок в образе — Chrome for Testing 156.0.8078.4; 158 врал бы относительно бинарника |
| `DEEPSEEKER_CLIENT_VERSION` | `2.8.0` | не снято: и прямой curl, и headless Chromium через SOCKS моста получили HTTP 403 до JS. Снять в Selkies до возврата аккаунта |
| `DEEPSEEKER_COOKIE_HEADLESS` | `true` | headful без рабочего X падает; вернули headless |
| `DEEPSEEKER_WARMUP_NON_HEADLESS` | `false` | то же |

Источники: `deploy/platform/litellm/values.yaml`, `charts/deeperseeker/values.yaml`,
`charts/deeperseeker/templates/deployment.yaml`. Argo берёт чарт и поверх него
`deploy/deeperseeker/values.yaml`; этот overlay лимиты не перетирает.

Ключ LiteLLM с `o-deepseek`: `alchemmist`. У `openhands-monori` модели `qwen3.8-27b` и `v-deepseek-uc`, `max_parallel_requests` 3 (в живой базе тоже 3; скрипт не опускает его ниже этого значения и не возвращает `o-deepseek`). Модельный `rpm` общий, поэтому агент с parallel 3 выедал весь потолок ручного чата.

19 ноября 2026 токен `main` был `QUARANTINED`. Один Restore вернул его в `ACTIVE`, один короткий ход ответил `40003 INVALID_TOKEN`, и мост снова поставил карантин. Второй Restore не делался. До 21 ноября 2026, 23:48, это не лечится новым логином того же аккаунта, если `main` и есть забаненный аккаунт; совпадение по-прежнему не доказано, но сессия отозвана.

`Argo Health=Degraded` при `QUARANTINED`-токене — ожидаемое поведение, readiness честно красный, откатывать лимиты не надо.

График веб-чатов убран с публичного `socrat-llm-keys`: свободное место зарезервировано для четвёртой модели. Диагностика остаётся в Loki. Правило Loki `deeperseeker:web_chats:created:1h` ищет строки `chat_session/create`. Образ `1b1148ec1e2a` пишет эту строку при ошибке и молчит при успешном создании, поэтому цифра — не число чатов. На неё не опираться. Следующая сборка образа накладывает `deploy/deeperseeker/patches/log-created-chat-session.patch` после прокси-патча: успех пишет `created chat_session`. До проверки нового образа не считать строки лога числом чатов.

### Сбросить сессии перед возвратом аккаунта

Делать это в последние минуты перед первым разрешённым логином, не раньше: рестарт пода до конца бана прогревает браузер и трогает upstream. `POST /tokens/{id}/purge` и `/tokens/purge_all` не использовать: они шлют `chat_session/delete_all` на `chat.deepseek.com`.

1. Убедиться, что чат на `o-deepseek` никто не шлёт (ключ `openhands-monori` этой модели не имеет).
2. Посмотреть алиасы, не печатая токен:

```bash
kubectl -n deeperseeker exec deploy/deeperseeker -c deeperseeker -- python -c 'import sqlite3; c=sqlite3.connect("/app/data/deeperseeker.db"); print(c.execute("select id, alias, status from tokens").fetchall())'
```

3. Для id этого алиаса стереть только локальные signature. `device_id` не трогать.

```bash
kubectl -n deeperseeker exec deploy/deeperseeker -c deeperseeker -- python -c 'import sqlite3,sys; tid=int(sys.argv[1]); c=sqlite3.connect("/app/data/deeperseeker.db"); c.execute("delete from sessions where token_id=?", (tid,)); c.execute("delete from session_map where token_id=?", (tid,)); c.commit(); print("cleared", tid)' ID
```

База на PVC: `/app/deeperseeker.db` — ссылка на `/app/data/deeperseeker.db`. После очистки следующий ход не найдёт старый чат и откроет один новый, а не пачку по старым signature.

Старый под в namespace `llm` снят: чарт, образ в `services/` и Application удалены из Git.
PVC профиля и секреты этого пода удаляются вместе с ним. Secret `deeperseeker-service-vpn` не трогать.

### Границы, которые нельзя переходить

- Один аккаунт — один клиент. Второй мост с тем же `userToken` не поднимать.
- Пока мост работает, не открывать `chat.deepseek.com` под этим аккаунтом «проверить». Новый логин выкидывает токен в пуле.
- Токен снимать из обычного браузера, вставить в дашборд, вкладку закрыть. Не делать logout: он отзывает сессию на сервере.
- Не поднимать `tokenConcurrency`, не убирать паузу 4 секунды, не ставить `MAX_UPSTREAM_ATTEMPTS` больше 1, не укорачивать cooldown ниже 300, не включать ретраи LiteLLM на `o-deepseek`.
- Не дёргать `/health?deep=1` по расписанию сверху readiness. Проб и так ходит туда, пока под не Ready.
- После `40003`: один Restore и один короткий ход. Повторный `40003` — новый токен, не второй Restore. Цикл «Restore → логин → Restore» — лестница к бану: форк карантинит токен именно затем, чтобы его не слали снова каждую минуту.
- Веб-аккаунт, который банили до 21 ноября 2026, 23:48, новым логином не оживить. Совпадает ли текущий `main` с тем аккаунтом, этот срез не устанавливает.
- `v-deepseek-uc` от бана веб-сессии не зависит. Его не переводить на этот мост ради обхода лимита.

## Headful, версия клиента, дедлайн выката

19 ноября: в образе есть `/usr/bin/Xvfb` и `xvfb-run`, `DISPLAY` у процесса пустой, код форка Xvfb не запускает. Прогрев при старте пропускает `QUARANTINED` токены, поэтому рестарт не пишет строк cookie. Отдельный запуск Patchright: `headless=True` проходит, `headless=False` даже при живом `Xvfb :99` падает `SIGTRAP`. Headful оставлен выключенным. Отдельная задача на образ: поднять X так, чтобы Chrome из `/ms-playwright/chromium-1248` жил в headful, и только потом снова ставить `DEEPSEEKER_WARMUP_NON_HEADLESS=true`. `/ms-playwright/chromium-1248/chrome-linux64/chrome --version` печатает `Google Chrome for Testing 156.0.8078.4`. Пути `chrome-linux/chrome` в образе нет. `proxy-wiring.patch` путь к Chrome не задаёт. В образе бинарник только `chrome-linux64/chrome`, пути `chrome-linux/chrome` нет.

Образ `sha256:3cab7de3` проверен локально на amd64, в под не выкатывался. Процесс стартует, `GET /v1/models` с ключом возвращает `v4.1flash`. Мок `chat_session/create` на `127.0.0.1` получил `User-Agent` Chrome/156 и `sec-ch-ua` с `Google Chrome";v="156"` и `Chromium";v="156"`. В лог написалось `created chat_session mock-1`. Патч подставляет только мажор в строку, которая раньше была от 157: `Not-A.Brand` v=99 и порядок брендов не взяты из цикла Chrome 156. Это слабый сигнал, не отдельный баг рестарта.

Пока крутится digest `696884aa`, исходящий запрос несёт UA 156 и зашитый `sec-ch-ua` 157. Это не чинить отдельным рестартом. Один upgrade потом: новый digest, UA 156 (в values уже Linux, не Windows) и новый выход. Токен рождается в Selkies, там может быть Chrome 158, а мост работает как 156. Так и оставлять: браузеры обновляются вразнобой, обратно на 158 не выравнивать.

Образ Selkies `lscr.io/linuxserver/chrome:amd64-latest` в Git и в Deployment кластера не найден, digest запинить некуда.

`x-client-version` снимать сначала в Selkies: там headed Chrome, он может открыть страницу там, где headless с этого SOCKS получил 403. Если и Selkies получает 403, выход мёртв. Логин откладывается до смены выхода, а не до следующей попытки тем же адресом.

`x-client-version` снять до возврата аккаунта, логин не нужен. В Selkies открыть `chat.deepseek.com`, DevTools → Network, на любом запросе прочитать заголовок `x-client-version`, записать в `DEEPSEEKER_CLIENT_VERSION` обоих values и выкатить. Пока там `2.8.0`, мост называет сборку, которой на сайте может уже не быть.

`progressDeadlineSeconds` у Deployment — 604800, чтобы карантин не превращался в `KubeDeploymentRolloutStuck`. Это не единственный сигнал. `SocratDeeperSeekerSessionLoggedOut` смотрит `ready=0` при `running=1` пять минут и не зависит от Argo и от дедлайна выката. Silence `22ebf64b-6d3a-44bc-b2ee-60ec1eda0933` гасит его до 2026-11-21 23:48 +0300. Не продлевать: после этого красный снова значит разлогин. Останов контейнера и частые рестарты ловит `SocratContainerRestartsFrequent` (три рестарта за 30 минут), не недельный дедлайн.

## Устройство и возврат аккаунтов

До 21 ноября 2026, 23:48, ни в один из двух забаненных аккаунтов не логиниться. Один контролируемый рестарт для проверки X уже сделан. Дальше до конца бана под не рестартовать, кроме выката, который возвращает headless.

### Снять реальный Shumei `device_id`

Один аккаунт — один постоянный `device_id`. Он переиспользуется при каждом следующем логине. Значение хранить рядом с заметкой об аккаунте, не в Git и не в чате.

1. Открыть `https://chat.deepseek.com` в том браузере, где потом будет логин. На страницу зайти без логина.
2. Консоль (`Cmd+Option+J`):

```js
SMSdk.getDeviceId()
```

3. Скопировать строку. Если `SMSdk` ещё нет, подождать загрузку скрипта и повторить. Не логиниться ради этой команды.
4. Когда аккаунт уже можно возвращать, записать это значение в колонку `device_id` строки токена до первого хода моста. Генератор форка подставляет UUID, если поле пустое.

`DEEPSEEKER_DEDUPLICATE_DEVICE_IDS=true` даёт уникальность, но не достоверность: генерируемый UUID — фейковое устройство. Реальный идентификатор, снятый в браузере, предпочтительнее.

### Расписание возврата

- 21 ноября 2026 после 23:48 — аккаунт A (бан до 23:48). Только руками, сутки. Мост не подключать.
- 22 ноября 2026 после 15:11 — аккаунт B (бан до 15:11). Тоже только руками, сутки.
- Мост подключать к аккаунту не раньше чем через сутки после его разбана и только к одному из двух. Второй в это время остаётся ручным.

### Один логин — один токен

После `40003` сделать один Restore в дашборде и один короткий ход. Повторный `40003` означает переход на другой аккаунт, а не второй Restore и не новый логин того же. Вкладку после копирования `userToken` закрыть без logout.

## Резидентный выход — отдельная задача, без реализации

В homelab резидентного egress нет. Выход моста — sidecar 3x-ui, identity `svc-free-deepseek`, endpoint `91.189.82.238:32053`. Это датацентровый VPN, тот же класс адресов, что и узел `socrat-5`. NetBird и личный SSH — доступ оператора, не выход приложений. Другого service-identity с домашним или мобильным IP в чартах нет.

Оба забаненных аккаунта за всю жизнь не имели ни одного касания с резидентного IP. 19 ноября headless Chromium через тот же SOCKS получил HTTP 403 на `https://chat.deepseek.com/`. Cookie-регенерация идёт с этого же выхода, поэтому 21-го она может не пройти даже с живым токеном. Токен, снятый с домашнего IP, мост всё равно потратит с датацентра.

403 до JavaScript с текущего SOCKS — отказ эджа по адресу. 21-го с этим выходом можно не дойти ни до страницы, ни до токена. Ждать и «проверить в тот день» нельзя: это третий бан.

Смена выхода, в этом порядке:

1. Домашняя сторона звонит наружу, кластер слушает. Дом часто за CGNAT, входящий WireGuard к маку не поднимется. Сервер туннеля — `socrat-4`. Инициатор — домашнее устройство. Identity новая, не `svc-free-deepseek`. Межнодовый WireGuard и NetBird под в домашний IP не выпускают.
2. Устройство всегда включено. Роутер или NAS лучше. Если только мак: `caffeinate -dims` и проверка, что туннель сам встаёт после сна.
3. Split-tunnel в обе стороны. Через туннель только `chat.deepseek.com` и статические домены DeepSeek, включая `fe-static.deepseek.com` (wasm). Весь трафик моста через дом положит аплоад на первой генерации.
4. Если за сутки туннель не собран — временный покупной резидентный прокси, тоже отдельной identity и с тем же split.
5. До 21-го, не в тот день: `curl -sI https://chat.deepseek.com` с адреса туннеля. Пока там 403, к аккаунтам не подходить. `91.189.82.238` для возврата не использовать.

Контрольный эксперимент, единственный способ разделить окружение моста и регистрацию: новый аккаунт открывается с резидентного IP, к мосту не подключается, неделю используется только руками из того же браузера. Выжил — виновато окружение моста. Не выжил — виноваты регистрация и IP.
