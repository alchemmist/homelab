# DeeperSeeker: веб-сессия DeepSeek рядом с free-deepseek-api

Срез приёмки **19 ноября 2026**. Это рабочая память, не public wiki и не разрешение
печатать токены, API-ключи или URL подписки. Git задаёт чарт и LiteLLM; живой токен
и подписка лежат только в Secret.

`free-deepseek-api` в namespace `llm` не заменялся и не обновлялся helm-ом.
DeeperSeeker поднят рядом. Имена подов ниже — снимок приёмки, не контракт.

## Зачем отдельный сервис

Форк [artyom08-dev/deeperseeker](https://github.com/artyom08-dev/deeperseeker)
на коммите `1b1148ec1e2a` (пакет 7.0). Поверх апстрима FreeDeepseekAPI там есть
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
| VPN sidecar | тот же Xray, что у free-deepseek: `ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b` |

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

По явному решению владельца взята уже существующая identity **`svc-free-deepseek`**,
а не новый `svc-deeperseeker`. Secret `deeperseeker-service-vpn` в namespace
`deeperseeker`, ключ `subscription-url`, скопирован из `llm/free-deepseek-service-vpn`.
Это общее отзывное и лимитное ведро с free-deepseek. Отзыв одного клиента погасит
оба сервиса.

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
mode 0600, в git не входит. `llm/free-deepseek-upstream` больше не используется
моделью `o-deepseek`.

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
| `api_base` | `http://free-deepseek-api.llm.svc.cluster.local:9655/v1` | `http://deeperseeker.deeperseeker.svc.cluster.local:4000/v1` |
| upstream model | `openai/deepseek-chat` | `openai/v4.1flash` |
| ключ | `DEEPSEEK_PROXY_API_KEY` ← `free-deepseek-upstream` | тот же env ← `deeperseeker-upstream` |
| `max_input_tokens` | 32768 | 369228 |
| `max_output_tokens` | 8192 | 8192 |

`num_retries: 0`, timeout 600. Сеть между `llm` и `deeperseeker` не режется
NetworkPolicy (отдельной политики на мост нет).

Проверка из пода LiteLLM мастер-ключом, после rollout: `model=o-deepseek` вернул
**200** и `pong`. Это один короткий вызов, не сутки стабильности и не нагрузка агента.

OpenHands и `v-deepseek-uc` на этот мост не переводились. Selkies у free-deepseek
оставлен.

## Чего эта приёмка не закрывает

- P0 по живому free-deepseek (sidecar только в рантайме, readiness по mtime, параллелизм
  OpenHands, `scripts/provision-openhands.py`) этим срезом не делался.
- Общий VPN-клиент с free-deepseek — осознанное исключение из правила «одна identity
  на сервис».
- Дашборд снаружи кластера не опубликован. Вход оператора — `kubectl port-forward`.
- Пока readiness красный, LiteLLM может слать в него только если сам не смотрит на
  endpoints. Сейчас под Ready; при 401/пустом пуле снова выпадет.
- Капча и логин из Playwright/Patchright в кластере не являются рабочим путём.
  Повторять логин надо из обычного браузера дома и заново вставлять `userToken`.
