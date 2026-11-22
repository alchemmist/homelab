# Socrat — sign-in page prototypes

> **Production update — 2026-11-01:** approved Quiet Mono v5 is frozen in
> [`deploy/authentik/quiet-mono/reference/`](../../deploy/authentik/quiet-mono/reference/).
> Native production branding has now been applied; rollout/recovery are documented in
> [the production README](../../deploy/authentik/quiet-mono/README.md), with explicit
> [parity gaps and pending owner acceptance](../../deploy/authentik/quiet-mono/ACCEPTANCE.md).
> The “no cluster changes” statements below describe earlier prototype iterations only.


Open `index.html` in a browser. No build, server or internet is needed to view them.

```sh
open /Users/antonmoss/code/homelab/prototypes/authentik/index.html
```

These are standalone visual HTML mockups, not changes to the running Authentik.

## Variants

| File | Title | Idea |
| --- | --- | --- |
| `01-frost.html` | Frost | Centered form, moderate rounding, Wiki typography. |
| `02-editorial.html` | In the margins | Window on the left, large book-style heading, fields with an underline. |
| `03-liquid.html` | Glass | Window on the right, soft corners, strong blur and a light edge. |
| `04-gallery.html` | Atelier | One wide window with two columns: a large mask and the form. One column on a phone. |
| `05-typewriter.html` | Quiet Mono | Narrow almost-paper window, CourierCyr, square corners and an outlined button. |

Common principles: full-screen photo, light theme, a single matte panel, no ad
blocks, external captions or extra cards. The matte effect is a CSS
backdrop-filter, not a full optical refraction of macOS Liquid Glass. Without
blur support, a nearly opaque light backing is used. prefers-reduced-motion and
prefers-reduced-transparency are respected.

## What is taken from the existing design

Local sources studied:

- `../blog/site/assets/style.css`: CourierCyr and restrained typography.
- `../hugo-docs/assets/admin.css`, `layouts/partials/docs/system-page.html`: the
  minimalist former Wiki form, book-style heading and small field labels.
- `../lms/site/static/site.css`, `../lms/site/hugo.toml`: the same book/monospace
  approach; `../lms/frontend/src/index.css`: the ink-blue palette `#15223c`.

Fonts were copied from the local `../blog/site/public/assets/fonts/`: CourierCyr
regular, Computer Modern Roman regular/bold. The existing font rights are not
changed; this directory does not declare them free and does not add a new license.

The mask was extracted from `deploy/litellm/branding/socrat-logo-light-v1.svg`.
In the source SVG, the image is embedded as a 1200×1800 PNG; it is **not vector
outlines**. Transparent margins were cropped and a 320px-high WebP (~17 KiB)
prepared. On large screens the maximum displayed height is 157px. A real vector
is not needed for these mockups.

## Backgrounds and random selection

Two local photographs: a mountain lake and a forest. Sources and license links
are in `assets/sources.json`. For each photo there are 1920px and 960px wide
WebPs. The mobile version is selected by CSS at widths up to 700px.

Any variant file accepts:

- `?scene=lake` — the lake, the default background;
- `?scene=forest` — the forest;
- `?scene=random` — a random choice of one of the two on open/reload.

The random mode is only a demonstration of **client-side** selection in the
prototypes, not a server-side implementation for Authentik. A random pick can
repeat the previous photo. The background does not change while entering data
or moving on to MFA. The gallery switches the background immediately for all
variants; the same default photo helps compare the designs themselves.

Later the photos will be replaced with the user's collection. For a real
implementation, separately define the selection mechanism, refresh behavior,
focal points/cropping, caching, sizes/AVIF/WebP and a fallback background.
Authorization and MFA must keep working with Authentik's standard components;
static HTML by itself is not a ready-made Brands theme. After a design is
chosen, the capabilities of the installed version and support for error
screens, MFA and recovery must be verified.

## Mockup safety

Do not enter real credentials. The mockups have no backend, fetch, analytics,
cookies or localStorage. Form HTML additionally forbids network connections
and form submission via CSP. In Quiet Mono, after the test MFA, only local
navigation to `05-consent.html` occurs. JS only switches demo states. Enter any
test login/password, then any 6 digits for the MFA example. The password
is cleared when moving to MFA; nothing is stored.

The password visibility toggle, empty-form errors, going back and restarting
work. Help links do not lead to real recovery procedures. The gallery and its
captions are not part of the proposed authorization pages.

## Verification

Verified in Chromium via Playwright: all 5 variants at 1440×960, 390×844 and
320×568; no horizontal overflow; local fonts load; visibility toggle/password
clearing and the demo MFA work; background switching in the gallery works; no
JavaScript errors or external HTTP(S) requests. The desktop contact sheet and
the mobile variant were reviewed visually.

No cluster changes, deployments or Git pushes were performed.

## Refinements of the chosen Quiet Mono variant

- The entire mockup and gallery interface is translated into English; the
  original heading of every form is `Sign in`, with no greetings.
- In Quiet Mono the heading uses Computer Modern Bold, 31px, weight 700; the
  remaining elements are CourierCyr.
- Quiet Mono dropped the visual hover/click effects: button inversion,
  field background/border changes, eye highlight, help underline, button shift
  and transitions. On hover, buttons still show a pointer; fields a text cursor.
  This initial behavior is refined below; input errors remain distinguishable.
- All HTML use an exact copy of the live Wiki favicon (`/images/socrat.svg`),
  without scaling or redrawing. This is a resource separate from the mask
  inside the form.
- Verified: computed styles unchanged on hover/click, keyboard focus, MFA and
  widths 1440/390/320px; the mobile variant was reviewed visually.

## Quiet Mono: full set of screens and latest edits

Open `05-typewriter.html` (sign-in) or `05-consent.html` (consent before
redirecting to Argo CD). The shared gallery has a separate link to the consent
screen.

### Interaction changes

- Fields have **no extra outline on click or Tab**. The original thin border
  stays unchanged. Validation errors are still marked separately.
- The main bottom button (`Sign in`, `Verify code`, `Continue`) gets a light
  ink-colored fill with 4.5% opacity and the arrow shifting by 3px over 160ms.
  The text color is not inverted. Hover is not enabled on touch devices; with
  prefers-reduced-motion the arrow does not move.
- The password toggle uses two separate SVGs: a crossed-out eye when the
  password is hidden and an open one when shown. aria-label and aria-pressed
  are updated too. This is not the previous opacity change of a single icon.

### Consent / Argo CD

The structure was studied from an owner-saved Authentik page: the heading
Redirecting to Argo CD, the current account and Not you?, the permission list,
Continue, language selection, Flow inspector. The source HTML was not executed
and not copied into the repository; real users, session IDs and other
identifiers were not carried over.

The prototype shows `demo-user` and the `email`/`profile` permissions.
Continue **does not grant permissions and does not open the real Argo CD**: it
switches to a local explanation with the ability to return to the consent
mockup. `Not you?` and `Back to sign in` open the local form.

### Shared tools

- Top-right corner of both screens: language and the inspector magnifier,
  styled in Quiet Mono.
- English and Russian genuinely switch, including the form, MFA, errors, consent,
  panel and available captions. English is default; Russian can be opened via
  `?lang=ru`. Switching languages does not clear fields. Language and the
  selected photo are passed between local screens via query parameters.
- The inspector is a side modal dialog: Next stage (name/type/object), Plan
  history with expandable stages, Current plan context and a deliberately
  fictional `prototype-session`. The state depends on the mockup's current
  step. It closes via cross/Escape, traps Tab inside the panel and returns
  focus to the magnifier.
- This is **not the real Authentik inspector API**. All data is synthetic and
  explicitly labeled as prototype. On a future rollout, keep Authentik's
  standard authorization/access restrictions to diagnostics; do not expose
  sessions or plans of ordinary users via a separate public API.

### Checks of this iteration

Chromium/Playwright: field styles under mouse/keyboard focus, the two eye
SVGs and aria states switching, soft hover without inversion, both locales
without input loss, focus and inspector expansion, the full sign-in → MFA →
consent route, the absence of a real redirect/permission grant, local returns
preserving language and background, 1440×960 / 390×844 / 320×568, no
horizontal overflow, reduced motion, the link from the gallery. No JavaScript
errors or external HTTP(S) requests. Desktop consent/inspector and mobile
sign-in with the language menu were reviewed visually. The cluster was not
changed.

## Inspector redesign: native-style pipeline and Wiki JSON

The panel was reworked after visual review: 600px width on desktop, a light
opaque work surface, sections in readable cards, the main CourierCyr enlarged.
The sign-in form was not redone. On a wide screen the form shifts into the
remaining space rather than ending up under the panel.

Plan history is vivid again: a connected vertical pipeline, green checkmarks
for completed stages, blue for Current and neutral for Pending. States are
labeled with text, not color alone; the current node carries aria-current=step.
Any stage expands into JSON. Plan snapshots are kept in a separate expandable
block. Real Authentik may have repetitions/re-plannings; the demo's five steps
are not a model of the real API.

The JSON reuses the exact Wiki files: Chroma syntax.css and CM Typewriter WOFF2.
The light-block styling is adapted from the Wiki hugo-content; token
highlighting, local horizontal scrolling of long lines and Copy with
unavailable-clipboard handling were added. JSON is rendered via safe DOM
text/span, not innerHTML.

The basic checks of both forms/languages/sizes passed again. Additionally
verified: completed/current/pending, stage/snapshot expansion, highlight
classes, JSON round-trip, Copy, the Wiki font and expanded data on mobile.
Desktop pipeline, desktop expanded JSON and mobile expanded JSON were
reviewed. Focusable-element filtering inside the modal was fixed for closed
details elements.

**Important:** the real rollout mechanism and CSS boundaries are described in
[AUTHENTIK-THEMING.md](AUTHENTIK-THEMING.md). The sources studied are exactly
version/2026.8.5. The plan is to keep the native Flow executor/inspector and
their access rights. The CSS does not add JSON syntax highlighting or a working
Copy button: those mockup details must not be silently promised as CSS-only.
The cluster was not changed.

## Inspector motion (prototype only)

Opening and closing the panel is now synchronized with the form's movement:
180ms, cubic-bezier(.2,.65,.3,1), no spring/overshoot, opacity effects or
blur animation. The panel moves via transform; the form via a FLIP from its
current visible position to the new layout. On wide screens the form shifts by
300px; on narrow ones it stays in place and the panel slides over it. With
reduced motion both operations are instant; toggling the setting mid-motion
finishes the animations. Escape and the cross use the same animated close.
Modality, focus and stage history are preserved.

Playwright verified both pages: initial/final positions without a jump,
several intermediate frames with equal normalized panel/form progress,
canceling the open via Escape, a repeated Escape, return to the original
coordinates, no leftover animations, mobile behavior and reduced motion. The
form, locales, inspector, MFA and local navigation checks passed again. The
real Authentik was not changed.

## Non-modal inspector: form remains interactive

Removed showModal(), the dimming backdrop, the scroll lock and trapping Tab in
the panel. It now uses a plain non-modal dialog.show() with aria-modal=false:
the form, password and language toggles, MFA and Continue are available with
the inspector open. The panel does not impose inert on the rest of the page.
When closing from an input field, focus stays in the field; Escape and the
cross keep the 180ms animation. The top tools shift with the layout on wide
screens so the language control does not end up under the panel.

Below 1100px width, the panel is placed below the form instead of covering it;
the page scrolls freely. This replaces the earlier mobile full-screen
overlay. The inspector=1 parameter keeps the inspector open on the local
MFA → consent transition.

Verified: real mouse/keyboard input into the form with the panel open,
language switching without input loss, the eye, MFA, consent, absence of
:modal/inert/scroll lock, free Tab, Escape from a field without losing focus,
no form/panel overlap at widths 1000/390/320. Synchronization and absence of
animation jumps on both screens, quick Escape and reduced motion were checked
again. The desktop non-modal screen was reviewed visually. The cluster was
not changed.
