# Inspector, redirects and interface language

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
