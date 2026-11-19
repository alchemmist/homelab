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
рядом с чартом: `charts/deeperseeker/files/proxy-wiring.patch`. Тег `1b1148ec1e2a`
совпадает с коммитом форка, digest — с уже пропатченным деревом. Повторная сборка
из чистого клона без патча снова пойдёт в DeepSeek напрямую.

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

Ключ `openhands-monori` получил `o-deepseek`. `v-deepseek-uc` — отдельный маршрут Venice, не этот мост.

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
токен, WAF и PoW живы. Он не говорит, что аккаунт не уперся в лимит по темпу. Счётчика созданных
чатов в Grafana нет: запросы в минуту этого не заменяют.

### Что стоит сейчас

| Где | Значение | Зачем |
| --- | --- | --- |
| LiteLLM `o-deepseek` `rpm` | 8 | общий потолок на все ключи; это не `rpm: 1` |
| LiteLLM `max_parallel_requests` | 1 | один запрос к модели одновременно |
| LiteLLM `max_retries` и `num_retries` | 0 | клиентский ретрай не добивает уже упершийся в лимит аккаунт |
| `DEEPSEEKER_MAX_UPSTREAM_ATTEMPTS` | 1 | дефолт форка 3 на 429 давал бы ещё два удара |
| `DEEPSEEKER_RATE_LIMIT_COOLDOWN` | 300 | 60 секунд возвращали токен в ту же очередь |
| `DEEPSEEKER_CALL_GAP_SECONDS` | 4 | пауза после хода, не вместо `rpm` |
| `DEEPSEEKER_TOKEN_CONCURRENCY` | 1 | не поднимать |
| `DEEPSEEKER_PERSIST_SESSIONS` | `true` | чарт теперь задаёт явно; рестарт без этого открывает новый чат на каждый следующий ход |

Источники: `deploy/platform/litellm/values.yaml`, `charts/deeperseeker/values.yaml`,
`charts/deeperseeker/templates/deployment.yaml`. Argo берёт чарт и поверх него
`deploy/deeperseeker/values.yaml`; этот overlay лимиты не перетирает.

Ключи LiteLLM, которым выдан `o-deepseek`: `alchemmist` и `openhands-monori`.
У `openhands-monori` свой `max_parallel_requests` тоже 1, и он ограничивает все модели этого ключа,
включая `v-deepseek-uc` и `qwen3.8-27b`. Модельный `rpm: 8` общий: агент и ручные вызовы
делят одни восемь запросов в минуту. `scripts/provision-openhands.py` по-прежнему пишет
новому ключу только `v-deepseek-uc`. Повторный provision снимет `o-deepseek` с живого ключа.

На проверке перед выкатом алиас `main` уже был `QUARANTINED`, в `sessions` было 19 строк.
Readiness моста требует 200 от `/health?deep=1`, поэтому после рестарта под остаётся `1/2`
(VPN готов, мост нет в endpoints), пока токен не выведут из карантина. Это штатное поведение
проба, не недокатанный конфиг.

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
