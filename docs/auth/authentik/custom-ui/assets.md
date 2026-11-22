# Static assets, icons and backgrounds

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
локальных initials: [текущий identity status](../operations/identity-current-state.md#аватары).
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
сравниваются полностью. [Assets/receipt contract](../../../../assets/service-icons/README.md).
