# Inspector, redirects and interface language

## 8. The inspector: real data and rights

The native inspector is a debug tool, not an ordinary user timeline.
Data access is checked by the backend permission `authentik_flows.inspect_flow`.
A normal anonymous/observer does not get it. The native `?inspector=available` may
show a toggle without admin rights, but the API must still refuse 403/404.
The visible icon itself is **not proof** of permission to read the context.

The history is built by the native `FlowInspector.ts` from the API `flows/inspector/<slug>/`.
The backend reads `authentik/flows/history`, filters by flow UUID, not by a specific
application/login. `stage_ok` keeps a deep copy of the plan; a cancel deliberately does not delete
the history. A provider may set a new plan before the executor, bypassing the no-plan reset.
Therefore a shared authorization flow accumulates repeating consent/final pairs.

In the two owner-saved pages: first 26 completed + current/pending, then 28
completed. This is 13 former pairs and one more that finished, not 28 independent MFA
checks of LiteLLM. By the names you cannot restore the applications/time of each pair.
Refreshing the inspector replaces the state, it does not append generated frontend records.
`Dynamic In-memory stage: Final stage, restores params from Flow` is a standard
OAuth fulfillment stage, not an assistant hallucination and not an extra consent.

The production CSS limits the history to **22rem / 18rem mobile** with scrolling.
All entries are kept, the order is not changed, there is no CSS-deduplication/truncation.
If a real "only this login" filter or grouping by authorization
attempt is needed, that is a separate reviewed component/backend work, not a CSS falsification.

## 9. The magnifier, drawer and Follow redirect

Toggle: fixed viewport offsets 24px desktop / 17px mobile, a square 39px, a centered
18px vector CSS mask instead of the unsuccessful native search-plus glyph. The real button,
ARIA label and handler are kept. The Mask CSP was verified in a real browser.

The drawer is a native non-modal: without dimming, inert, focus trap and document scroll lock.
On a wide desktop, a 600px panel and a 300px shift of the form center at a 1440px viewport;
the flex/transform transitions are synchronized at 180ms, reduced motion is accounted for.
On narrow screens the panel folds below the form, rather than overlapping it with a modal layer.

With the **inspector open**, the native RedirectStage deliberately holds the navigation
and shows a URL + **Follow redirect**. This is a debug pause, not an extra SSO consent.
Without an open inspector, an ordinary transition is automatic. Do not remove this protection
for a pretty instant redirect and do not rewrite the handler.

JSON syntax highlighting and a working Copy were in the offline demo, but were **not added
to the native inspector**. CSS can style a `<pre>`, but it cannot tokenize JSON or
implement the Clipboard API. A separate component enhancement is needed, with a review of
rights, safe DOM rendering and clipboard failures. Do not promise CSS-only parity.

## 10. Headings and language

The shown `Redirecting to %(app)s` turned out to be a raw Python-style placeholder. Instead
of hiding the text, CSS changed the native `title` of two default authorization flows to a
literal **Redirecting**. `flow_titles.py` stores the original titles and flow IDs in a
private `authorization-flow-titles-original.json`; rollback checks identity.
The other native messages/stages are not renamed by this.

The language picker is hidden, including from Tab; Brand default en/light. But this is **not
a hard enforcement of English on all old sessions**. The upstream precedence 2026.8.6:
`?locale=` -> `sessionStorage["authentik:locale"]` -> hint -> navigator -> fallback.
A fresh ru-browser was verified with an English UI; an old override/URL may win.
CSS does not clear the browser storage, the user attributes were not forcibly rewritten.
