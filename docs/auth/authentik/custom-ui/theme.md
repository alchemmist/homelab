# Theme ownership, CSS and form controls

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
