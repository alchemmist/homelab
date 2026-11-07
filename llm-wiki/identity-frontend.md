# Authentik / Quiet Mono: frontend, CSS, inspector и сопровождение

## Текущая граница — 7 ноября, снятие внешних auth gates

Удалены11 obsolete Authentik Applications (включая старую Kuma bookmark-карточку)
и10 Proxy Providers; outpost assignments сняты.10 native OIDC Applications,
их UUID/client credentials/callbacks/policy bindings сохранены. n8n,3x-ui, Kuma
и Syncthing используют собственный login; SearXNG и опубликованные SPI artifacts
публичны без Authentik и NetBird. Reader допускает только GET/HEAD, проверяет
manifest/hash и выдаёт безопасные типы inline. [Контракт и границы](../docs/identity/native-browser-auth.md).

При проверке: домашний публичный вход41/41; второму входу нельзя приписывать success.
`socrat-2` Node Ready=Unknown с17:04:42UTC; `k3s` inactive (exit17:03:56UTC),
на443 отвечает Caddy с TLS internal_error. Причина остановки не установлена;
Caddy/k3s/VPN не перезапускали. Старый xui gateway Pod/Deployment ожидает обычного
завершения на недоступной ноде; force-delete/finalizer bypass не выполнялся.
Остальные7 затронутых Argo apps Synced/Healthy, edge Synced/Progressing.


> Текущий срез7 ноября: [логины, первый вход и native роли](identity-current-state.md),
> [NetBird/сеть](network-access.md), [владельцы мониторинга](observability-current.md).
> Датированные rollout/smoke ниже — история своего этапа, не общая readiness.

Начало: [identity.md](identity.md). Подробный engineering runbook текущего дизайна.

## 1. Что работает в production

**Quiet Mono v5**: полноэкранное nature photo, светлая полупрозрачная матовая панель,
реальная маска Socrat, точный Wiki favicon, CourierCyr UI и жирный Computer Modern
для заголовков. Без маркетинговых панелей/приветствий. Production использует
фиксированное согласованное озеро; случайная owner photo collection не внедрена.

В браузере остаётся **нативный Authentik 2026.8.5**:

- `ak-flow-executor` исполняет server challenges;
- native identification/password, TOTP/validation, consent и redirect stages;
- `ak-flow-card` рисует карточку;
- `ak-flow-inspector-button` / `ak-flow-inspector` — штатные debug controls;
- `ak-drawer#flow-drawer` — штатная немодальная панель.

Наш login JS не подменяет executor и не проверяет пароли. Нельзя копировать в
production `quiet-mono.js` из demo: там только synthetic offline navigation/MFA.
Он не является OIDC client или middleware и никогда не должен получать реальные secrets.

## 2. Карта файлов и владение

| Путь | Назначение |
|---|---|
| `prototypes/authentik/01-frost.html` … `05-typewriter.html` | Исторические визуальные варианты; выбран v5 |
| `prototypes/authentik/05-consent.html`, shared CSS/JS | Offline demo, не backend auth |
| `deploy/authentik/quiet-mono/reference/` | Frozen approved reference; manifest sizes/SHA-256 |
| `deploy/authentik/quiet-mono/theme.css` | Production native Brand CSS |
| `deploy/authentik/quiet-mono/assets.json` | Reviewed asset names, paths, digests |
| `deploy/authentik/quiet-mono/static-image.json` | Digest-pinned nginx provenance |
| `deploy/authentik/quiet-mono/README.md`, `ACCEPTANCE.md` | Rollout/rollback, parity, measured checks |
| `ansible/roles/authentik/files/branding.py` | Brand/native presentation reconciliation + private backups |
| `ansible/roles/authentik/files/branding_static.py` | Детерминированные isolated static Kubernetes resources |
| `ansible/roles/authentik/files/flow_titles.py` | Neutral authorization titles, отдельный guarded rollback |
| `ansible/playbooks/authentik-branding.yml` | Explicit prepare/apply/rollback, без IdP upgrade/restart |
| `scripts/identity-branding-controls-check.py` | Read-only real native component CSS probe |
| `scripts/identity-branding-smoke.py` | Реальный temporary observer MFA/OIDC roundtrip |
| `tests/test_authentik_branding.py`, `test_authentik_flow_titles.py` | Offline regression/security contracts |

Frozen reference не редактировать, чтобы замаскировать production limitations.
Новая owner revision оформляется отдельно с описанием отличий. Старые фразы
«no cluster changes» в прототипах относятся к историческому этапу до rollout.

## 3. Где хранится фактический theme config

Domain-specific Brand `auth.socrat.alchemmist.xyz`, не blanket replacement default
Brand для всех доменов. `branding_custom_css` содержит rendered `theme.css`.
Brand также задаёт logo/favicon/background и light/en defaults. Эти поля лежат
в Authentik DB; файл в Git — reproducible source, но сам commit DB не меняет.

Native presentation changes помимо CSS:

1. `default-authentication-flow` title — `Sign in`.
2. Identification использует уже существующий default Password Stage: username
   и password в одной native форме, без нового authentication backend.
3. Native allow-show-password включён; глаз работает штатным кодом.
4. Explicit/implicit authorization flow title — literal `Redirecting`.
5. MFA/consent bindings и их разрешения не ослаблялись ради оформления.

Для identification PATCH у данной версии требуется `user_fields`; нельзя считать
пустой minimal payload универсально допустимым. DRF обрезает whitespace CSS,
поэтому reconciler нормализует `.strip()` для настоящей идемпотентности.

## 4. Shadow DOM: почему обычный CSS иногда не работает

У Lit components отдельные shadow roots. Селектор из document не проникает
произвольно внутрь `ak-stage-*`. Authentik AKElement применяет Brand CSS к своим
components; поэтому `:host(ak-stage-consent)` работает внутри соответствующего root,
а `:host([part='challenge'])` — в native challenge stage.

Примеры действующих scopes:

```css
:host(ak-flow-executor) .pf-c-login__main { /* панель */ }
:host(ak-flow-card) h1 { /* native heading */ }
:host([part='challenge']) input.pf-c-form-control { /* поля */ }
:host([part='challenge']) :is(button,a.pf-c-button).pf-m-primary { /* primary */ }
:host(ak-flow-inspector-button) button.inspector-toggle { /* лупа */ }
ak-drawer#flow-drawer::part(drawer-panel) { /* exported part */ }
```

`ak-drawer` — **обычный LitElement, не AKElement**. Его private root не получает
Brand CSS обычным способом. Для него используются внешние exported parts:
`drawer-content`, `drawer-panel`, `drawer-main`, `drawer-body`. Не добавлять
случайный deep selector и не заявлять success без computed style/geometry.

Часть селекторов version-specific; после upgrade проверять реальный DOM/source,
не только сохранённый screenshot. `!important` здесь осознанно перебивает native
component rules, но новые overrides ограничивать конкретным host/part, не всем UI.

## 5. Контракт полей и primary actions

- Поля имеют простую рамку; hover/focus/Tab не добавляют outline/glow.
- Validation сохранена: invalid input получает error border, а не всегда «чистый» вид.
- Eye button — native control внутри input group; не декоративная картинка.
- Primary: прозрачный фон, тёмный текст, тонкая рамка, Courier, стрелка.
- Hover: ink tint **4.5%**, arrow **3px / 160ms**, без dark/light inversion.
- `prefers-reduced-motion` выключает движение. Browser может сериализовать alpha
  с округлением до 8-bit; CSS `.045` не переписывать по одному computed RGB string.
- `Follow redirect` — **anchor**, не button; оба охватывает `:is(button,a.pf-c-button)`.
  Ранее из-за button-only selector эта ссылка оставалась синей с плохим контрастом.
- Keyboard/ARIA/events не заменялись. Лупа имеет отдельный focus-visible indicator;
  требование «без focus glow» для text inputs не запрещает видимый фокус у кнопки.

Не стилизовать только English text match: перевод/динамический label поменяет текст,
а component/class contract останется. Не скрывать реальные validation messages.

## 6. Статика без expiring URL

Первые signed media URLs Authentik оказались непригодны для persistent CSS: JWT
подпись истекает. Brand не должен хранить такой URL как постоянный background/font.
Вместо этого используется same-origin endpoint:

```text
https://auth.socrat.alchemmist.xyz/-/quiet-mono/v1/<sha256-prefix>-<filename>
```

`branding.py` проверяет локальный digest каждого asset, строит content-hashed URL,
проверяет served bytes по HTTPS и заменяет `__ASSET_*__` placeholders. Если hash
не совпал или placeholder остался, apply не должен продолжаться.

`branding_static.py` создаёт immutable ConfigMap, sandboxed nginx Deployment,
Service и prefix-only Ingress. Только reviewed `.webp`, `.svg`, `.woff2`, GET/HEAD,
`nosniff`, годовой immutable cache. Нет JS login bundle, произвольного `/data`
или private backup directory. API/token/login пути продолжают обслуживаться IdP.

Nginx: digest закреплён в `static-image.json`, non-root, read-only FS, no SA token,
no escalation/capabilities, ограниченный `/tmp`, requests 5m/16Mi, limits 100m/64Mi.
Секрет TLS `authentik-tls` общий для домена; ingress priority/prefix изолируют статику.
Это не HA и не justification для доступа к Kubernetes API из auth server.

Kubernetes apply особенности, уже исправленные:

- client-side last-applied annotation для binary ConfigMap превышала 256KiB:
  используется **server-side apply** с выделенным field manager;
- `kind: List` приводил к недоступному OpenAPI-v2 fallback: CLI выдаёт **отдельные
  JSON-as-YAML documents**, сохраняется strict OpenAPI-v3 validation;
- не добавлять `--validate=false` как обход этих ошибок.

При замене asset меняются bytes, SHA и URL; старый immutable URL не перезаписывать.
Проверить разумный размер bundle (renderer guard 900000 bytes) и mobile image.
Старые ConfigMaps/resources очищать отдельно после acceptance, не во время rollback.

## 7. Иконки application dashboard — отдельный слой

Источник `assets/service-icons/`, manifest `sources.json` содержит URL/revision,
SHA/provenance/license; README объясняет derivation. Это не favicon всего Authentik.
`icons.py` загружает pinned assets и меняет только `meta_icon` существующих apps;
не трогает provider/policies/launch URLs, включая Argo CD вне foundation registry.

У Argo CD — официальный pinned `homarr-labs/dashboard-icons` знак. Wiki больше
не использует BookStack artwork: исходный круглый Socrat из
`deploy/litellm/branding/socrat-icon-v1.png` (2349px) уменьшен до 512px и упакован в
SVG с embedded PNG без перерисовки. После уточнения владельца LiteLLM в dashboard
использует официальный product monogram SVG из pinned BerriAI/litellm revision;
круглый Socrat остаётся у Wiki.
Логотип login — отдельная маска; favicon Authentik — точный Wiki SVG.

Все девять текущих app icons проверены через разрешённый media URL: HTTPS200 и
совпадение bytes digest. Для media URL запрашивать свежий native resolved URL,
не сохранять его signed query в Git. Checksum-sensitive line endings не «чистить»
глобальным formatter: `.gitattributes` сохраняет нужные asset bytes.

## 8. Инспектор: реальные данные и права

Native inspector — debug tool, не обычный пользовательский timeline.
Доступ к данным проверяется backend permission `authentik_flows.inspect_flow`.
Normal anonymous/observer его не получает. Native `?inspector=available` может
показать toggle без admin rights, но API всё равно обязан отказать 403/404.
Сам видимый значок **не доказательство** разрешения читать контекст.

History строит native `FlowInspector.ts` из API `flows/inspector/<slug>/`.
Backend читает `authentik/flows/history`, фильтрует по flow UUID, не по конкретному
приложению/входу. `stage_ok` сохраняет deep copy плана; cancel намеренно не удаляет
историю. Provider может поставить новый план до executor, минуя no-plan reset.
Поэтому shared authorization flow накапливает повторяющиеся consent/final пары.

В двух owner-saved страницах: сначала 26 completed + current/pending, затем 28
completed. Это 13 прежних пар и завершившаяся ещё одна, а не 28 независимых MFA
проверок LiteLLM. По названиям нельзя восстановить приложения/время каждой пары.
Refresh inspector заменяет state, не дописывает сгенерированные frontend записи.
`Dynamic In-memory stage: Final stage, restores params from Flow` — штатный
OAuth fulfillment stage, не галлюцинация ассистента и не дополнительное согласие.

Production CSS ограничивает history до **22rem / 18rem mobile** с прокруткой.
Все entries сохранены, порядок не изменён, CSS-deduplication/truncation нет.
Если нужен настоящий фильтр «только этот вход» или grouping по authorization
attempt, это отдельная reviewed component/backend работа, не фальсификация CSS.

## 9. Лупа, drawer и Follow redirect

Toggle: fixed viewport offsets 24px desktop / 17px mobile, square 39px, centered
18px vector CSS mask вместо неудачного native search-plus glyph. Реальный button,
ARIA label и handler сохранены. Mask CSP проверен в настоящем браузере.

Drawer — native non-modal: без dimming, inert, focus trap и document scroll lock.
На широком desktop 600px panel и 300px сдвиг центра формы при 1440px viewport;
flex/transform transitions синхронизированы на 180ms, reduced motion учитывается.
На узких экранах panel складывается ниже формы, а не перекрывает её модальным слоем.

При **открытом инспекторе** native RedirectStage специально удерживает navigation
и показывает URL + **Follow redirect**. Это debug pause, а не лишний SSO consent.
Без открытого inspector обычный переход автоматический. Не удалять эту защиту
ради красивого мгновенного редиректа и не переписывать handler.

JSON syntax highlighting и работающий Copy были в offline demo, но **не добавлены
в native inspector**. CSS может оформить `<pre>`, но не токенизировать JSON и не
реализовать Clipboard API. Нужна отдельная component enhancement с review прав,
безопасной DOM rendering и clipboard failures. Не обещать CSS-only parity.

## 10. Заголовки и язык

Показанный `Redirecting to %(app)s` оказался raw Python-style placeholder. Вместо
скрытия текста CSS изменён native `title` двух default authorization flows на
literal **Redirecting**. `flow_titles.py` хранит original titles и flow IDs в
private `authorization-flow-titles-original.json`; rollback проверяет identity.
Остальные native messages/stages этим не переименовываются.

Language picker скрыт, в том числе из Tab; Brand default en/light. Но это **не
жёсткое принуждение всех старых сессий к English**. Upstream precedence 2026.8.5:
`?locale=` -> `sessionStorage["authentik:locale"]` -> hint -> navigator -> fallback.
Fresh ru-browser проверен с английским UI; старый override/URL может победить.
CSS не очищает browser storage, user attributes насильно не переписывались.

## 11. Как применить / откатить theme

Из `ansible/`:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=apply
```

Default `prepare` **не read-only dry-run**: копирует и apply/verifies static server,
но не меняет Brand/flow settings. `apply` меняет reviewed presentation. Никакого
IdP restart, DNS/WG modification или replacement authentication JS.

Private root `/home/alchemmist/.cache/homelab-authentik/`: `quiet-mono/`, rendered
CSS/media map, `theme-backups/`, `quiet-mono-brand-journal.json`. Journal указывает
последний pre-change snapshot; не путать последний CSS backup с baseline всего rollout.

Полный original baseline `theme-backups/quiet-mono-original-baseline.json` собран
из самых ранних snapshots: отсутствие domain Brand, старые title/separate password/
eye settings. Для полного rollback использовать именно его, не более поздний v5 backup:

```sh
ansible-playbook playbooks/authentik-branding.yml \
  -e ansible_host=109.173.40.247 \
  -e 'ansible_ssh_common_args="-o HostKeyAlias=[socrat.alchemmist.xyz]:2222"' \
  -e authentik_branding_action=rollback \
  -e authentik_branding_backup=/home/alchemmist/.cache/homelab-authentik/theme-backups/quiet-mono-original-baseline.json
```

Rollback identity-guarded и не удаляет static assets. Live rollback/reapply ради
демонстрации намеренно не выполнялся: не прерывать owner login только ради теста.

## 12. Проверка и upgrade checklist

```sh
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
python3 -m unittest discover -s tests -p test_authentik_flow_titles.py -v
# Python environment с Playwright/Chromium; readonly, без fixture identities:
python3 scripts/identity-branding-controls-check.py --run
python3 scripts/identity-branding-controls-check.py --run --public-edge 109.120.141.97
```

Controls check использует fresh anonymous context, требует отказ inspector API и
local-only native redirect challenge с заблокированным benign `.invalid` target.
Это **не owner auth acceptance**, не fake API history и не server configuration.
Проверяет реальные native components: geometry, контраст, font, arrow/hover,
reduced motion, focus и click handler; не сохраняет sessions/screenshots.

Actual auth test — `identity-branding-smoke.py --run`: временный observer + native
TOTP/consent/Grafana, cleanup в finally. Реальные человеческие factors не трогать.
Owner inspector осматривался по предоставленным им HTML; не брать его browser
session и не выдавать fixtures owner/debug privileges для красивого screenshot.

Saved HTML **не сохраняет все adopted shadow stylesheets**, поэтому не считать
локальный рендер файла точной production screenshot. Для анализа держать его
private, отключить scripts/network, не публиковать context/callback code/state.
Использовать фактический live DOM/computed style для визуальной приёмки.

Перед новым Authentik release: encrypted backup; release notes и schema migration
review; source diff native components/parts/locale/redirect/inspector; staging/checks;
оба edges, 320/390/desktop, password eye, invalid input, Tab, MFA, consent, anchor,
inspector denial, reduced motion и owner existing-session check. Не снимать version
guard прежде этой проверки. После push отдельно проверить фактический rollout.


## 14. Случайные фоны из dotfiles Nature

На 2026-11-01 owner предоставил `~/code/dotfiles/wallpapers/nature/images`:
30 JPEG (~40MiB, ширина до 5120px). Репозиторий-источник не изменяется; фактические
SHA256 каждого оригинала, Git revision и версия Pillow записаны в
`deploy/authentik/quiet-mono/nature.json`. Это provenance, не передача авторских
прав на исходные фотографии. Production использует только производные WebP.

```sh
python3 scripts/build-authentik-nature.py --source ~/code/dotfiles
```

Нужен Pillow с WebP. Метаданные EXIF/ICC не переносятся. Desktop long edge <=1920,
mobile <=960; quality обычно 80, при превышении file budget понижается до 68.
Локальная сборка не деплоит. `assets.json` содержит digest всех 67 assets:
7 исходных reference assets и 60 Nature derivatives. `reference/` остаётся frozen.

Nginx `split_clients "$request_id"` почти равновероятно выбирает один из 30 ID.
`/-/quiet-mono/v1/nature/desktop` и `/mobile` возвращают **сам WebP, HTTP200**:
только GET/HEAD, `Content-Type: image/webp`, `Cache-Control: no-store`, `nosniff`.
`X-Quiet-Mono-Scene` — публичный ID фото для проверки, не user/session identifier.
Это exact locations с alias из закрытого manifest map: никакого произвольного path,
JS, внешнего CDN, user cookie, IP-based tracking или auth logic. Обычные hash URLs
по-прежнему immutable. CSS переключает mobile endpoint при width <=700px.

Во время одного SPA flow нет таймера/смены видимого фона. Новая загрузка документа
выбирает заново (повторы возможны). При смене desktop/mobile breakpoint также
может выбираться другое фото. Native initial background и drawer могут вызывать
отдельные image requests; это не обещание одного HTTP-запроса на весь документ.

Статика раскладывается на content-hashed immutable ConfigMaps, каждый <950KB
serialized; Pod видит один read-only projected volume. Общий reviewed budget 16MB.
Playbook передаёт source одним временным tar (owner-only unpack), не десятками
SSH/stat операций, и рендерит отдельные resource documents в защищённый remote
file, не огромную Ansible stdout/stdin переменную. Server-side apply и strict
validation сохраняются. Перезапускается только static Deployment при новом
content digest; Authentik и shared ingress не перезапускаются.

Применение — стандартный `authentik-branding.yml` с явным `apply`. Сохранён
protected pre-Nature snapshot `nature-before-20261101.json`; штатный Brand journal
содержит применимый guarded pre-change backup. Возврат к предыдущей lake CSS —
через этот backup, не через initial pre-branding baseline (тот отменяет всю тему).
Не печатать snapshot/journal, не удалять старые ConfigMaps во время rollback.

Проверки: 30 original/60 derivative hashes, bounded objects, nginx syntax, full
playbook apply; live desktop1440/mobile390 на обоих edges, reviewed response bytes,
no-store, стабильность после загрузки, zero JS errors. В 12 выборках каждого edge
получилось по 11 разных сцен — это evidence, не гарантия отсутствия повторов.
`python3 scripts/identity-nature-smoke.py --run` повторяет anonymous live checks без
пароля/MFA/fixtures, screenshots и сохранённых session данных. Actual owner MFA
roundtrip в этом изменении не проводился. API comparison показал изменение только
Brand CSS/background; OAuth providers, policy/flow bindings и MFA validate settings
остались прежними. Argo refresh/VPS rollout этим playbook не затрагивается.




## 15. Оптимизация Nature: preview → резкое фото (2026-11-02)

Предыдущий §14 описывает **историческую первую реализацию**. Схема на момент этого этапа
устраняет два разных полных background-запроса и не кеширует только выбор сцены,
а не сами большие фото.

- Ранний `@import /-/quiet-mono/v1/nature/scene.css`, `no-store`, выбирает один из
  30 reviewed ID через nginx request_id (исторически; выбор исправлен в §16).
  IP tracking и authentication JS не добавлялись.
- Ответ <=2481B содержит inline WebP preview124–300B **той же фотографии** и
  ссылки на SHA-pinned AVIF/WebP. CSS layered background рисует preview под HQ.
  Никакой отдельной загрузки миниатюры, чужого случайного кадра или ожидания HQ
  для native login. После загрузки фон неподвижен; breakpoint меняет размер,
  но не photo ID.
- AVIF <=1920/960: медиана78,370B desktop /22,289B mobile вместо
  WebP159,250B /49,560B. Сохранены все30 originals и60 WebP fallback; добавлены
  60 AVIF и30 checksum-pinned scene CSS. Старые source/derivative hashes сохранены.
- Большие фото `public,max-age=31536000,immutable`; повторная выбранная картинка
  отдаётся из browser cache (проверено transferSize=0). Новый документ снова
  выбирает сцену; повтор допустим. Compatibility `/nature/desktop|mobile` теперь
  no-store302 на immutable asset, Accept/AVIF negotiation и GET/HEAD403 guard.
- Единственный фон — native `body::before`, drawer прозрачен. Native default
  background-prefetch указывает на прозрачный62B immutable SVG, не второе фото.
  Это presentation field, не подмена flow/authentication code.

В обоих public edges desktop1440/mobile390 проверены ровно один scene stylesheet
и один HQ image, правильный размер, same-photo preview, кеш, hashes, random sampling,
POST403, WebP fallback, native login и отсутствие JS errors/slideshow. HQ задержан
в отдельном browser-only тесте на5секунд: preview видим, поля native login доступны.
Фото и метаданные подготовлены офлайн; Pillow/libavif version в `nature.json`.

Тест: `python3 scripts/identity-nature-smoke.py --run`. Реальный owner login/recovery
не имитировался. Protected API comparison подтвердил изменения **только Brand
CSS/background**, не providers/policies/MFA. Перезапускался только static Deployment,
несколько раз при проверке подхода; Authentik/ingress/DNS/WireGuard не менялись.
Нулевая задержка до первого сетевого ответа не обещается; остаётся нейтральный
fallback на случай сетевой ошибки. Rollback — guarded непосредственно pre-performance
Brand backup, не initial baseline. Не удалять старые immutable CMs при откате.


## 16. Plan History без вложенной прокрутки

По запросу owner сняты ограничения22rem/18rem у native progress-stepper.
`max-block-size:none;max-height:none;overflow:visible`: список занимает естественную
высоту на desktop/mobile, прокрутка остаётся у инспектора, не внутри Plan History.
Это отменяет прежнее presentation-решение о bounded history scroll, но не меняет
данные, порядок, повторы и права доступа. Оба public edges проверены на1440/390px
через local empty layout box в native компоненте; настоящая owner history не
подменялась и не извлекалась. Изменён только CSS Brand, без рестартов.


## 16. Стабильный фон на весь OIDC-проход (2026-11-03)

Причина редких скачков: `split_clients "$request_id"` выбирал новое фото при
каждом импорте `scene.css`. Внутри SPA всё выглядело стабильно, но полноценный
redirect/reload создавал новый документ и новый случайный выбор. Два одинаковых
анонимных flow URL с неизменным `next` воспроизвели смену фото.

Теперь выбор — не на документ:

- Только same-origin Referer `/if/flow/.../?next=...` с OIDC `state` даёт seed.
  Пока encoded `next` неизменён, `split_clients` возвращает тот же ID независимо
  от request_id, slug стадии/flow, смены native auth session, cookie и reload.
  Новый OIDC state заново выбирает из всех30 фото; независимые выборы могут
  совпасть. OIDC state не меняем: это только read-only presentation selection.
- На серверных ошибках и переходах без `next` берётся прежний ID из отдельной
  host-only `__Secure-qm_nature`. Только30 allowlisted ID, никакого произвольного
  пути. Secure/HttpOnly/SameSite=Lax; Path=/-/quiet-mono/v1/; Max-Age=1800.
  Cookie обновляется только ответами selector endpoints, не immutable картинками.
  Содержимое — публичный ID фото, не user UUID, callback, bearer или session token.
- Для direct/native входа без уникального OIDC контекста либо при удалённом
  Referer static-only endpoint **не видит точную границу login/logout**.
  Здесь честный fallback —30минут с последнего selector request, а не обещание
  нового фото на каждый клик Login. Приоритет — не менять фон в текущем проходе.
  Разные вкладки с разными OIDC next имеют независимый устойчивый seed; fallback
  без next разделяет cosmetic cookie браузера. Cookie не является механизмом auth.
- Никакого custom authentication JS, HTML injection, IP/UA fingerprinting,
  смены Authentik cookie, политик, времени жизни токенов или MFA. Сырые next/state
  не сохраняются в новых cookies/headers/journal; access_log статики выключен.
- По-прежнему один same-photo inline preview + один кешируемый HQ, без slideshow.
  `scene.css` no-store; Vary: Cookie, Referer. Legacy selectors также сохраняют ID.

Применение ограничено новым immutable nginx ConfigMap и guarded заменой только
`Deployment/socrat-authentik-theme.spec.template.spec.volumes[config].configMap.name`.
Старый ConfigMap сохранён; приватный backup0600 содержит прежний Deployment/config.
UID/resourceVersion/old config проверены до PATCH. Остальные identity Deployment
specs и UID Authentik pods до/после совпали. Authentik API writes:0.
Откат — guarded возврат **этого config volume** на прежний ConfigMap из private
backup; не общий rollback Authentik/Traefik и не старый pre-Nature Brand rollback.
Для воспроизводимого reconcile использовать branding playbook с action=prepare:
обновляется только public static bundle, без Brand/flow/provider/MFA API writes.

`identity-nature-smoke.py --run` на обоих входах, desktop1440/mobile390:
native login reload×3 → native server error400 → возврат в тот же flow; соседняя
OIDC-вкладка не меняет первую; повторные CSS requests и смена flow slug устойчивы;
новые synthetic OIDC journeys дают разнообразие. Это анонимные layout/network
проверки, не выдача себя за владельца и не личная end-to-end MFA acceptance.
Также проверены scoped cookie, GET/HEAD, POST403, WebP fallback, hashes, image cache
transferSize=0; preview-only login доступен при удержании HQ на5секунд. Изолированный
unexposed canary перед production проверил nginx syntax, absent/foreign referrer
и отсутствие ротации на десяти одинаковых запросах; собственный canary удалён.


## Аватарки пользователей — 7 ноября 2026

Owner и antropophag получают штатные Gravatar URLs по email hash, без custom
avatar attributes. Это не импорт Google login и не восстановление удалённой
identity. Same email даёт тот же avatar. Внешние browser requests и возможность
локальных initials: [текущий identity status](identity-current-state.md#аватары).
Initials в production этой актуализацией не включались.

## Иконки всех существующих приложений — 7 ноября 2026

В Authentik21 application: добавлены11 отсутствовавших иконок, включая NetBird,
LMS, RustFS, поиск, Syncthing и служебные aliases.20 записей используют локальные
checksum-pinned SVG;3x-ui сохранил собственный branded PNG. Manifest
`assets/service-icons/sources.json` связывает один asset с несколькими exact slugs
через `applications`. SPI evidence использует существующую иконку Socrat.

Все21 resolved URL проверены: HTTPS200 и ожидаемый SHA256. PATCH менял только
`meta_icon`; UUID, providers, URLs, visibility и прочие non-icon application fields
сохранены. Hidden gateway entries не раскрывались, роли/группы не выдавались,
приложения не создавались, рестартов не было. Это проверка API/media, не визуальная
приёмка всех карточек в реальной человеческой сессии.

Для повторного применения — только `ansible/roles/authentik/files/icons.py`,
не полный Authentik/IAM rollout. Helper использует lock, private backup, SVG/media
checksum verification и exact before/after checks; при uncertain marker сначала
reconcile. Порядок provider property-mapping M2M IDs нормализуется, сами memberships
сравниваются полностью. [Assets/receipt contract](../assets/service-icons/README.md).
